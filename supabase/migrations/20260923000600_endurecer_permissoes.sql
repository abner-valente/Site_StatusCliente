-- Royal Imóveis — Site de status do cliente
-- Migração 6: remove privilégios que ninguém usa e fecha o TRUNCATE.
--
-- Contexto
-- --------
-- A matriz de permissões mostrou que `authenticated` e `service_role` tinham
-- REFERENCES, TRIGGER e TRUNCATE nas cinco tabelas, herdados do padrão do
-- Supabase. Nenhum dos três é usado pelo sistema.
--
-- O buraco que isso abria
-- -----------------------
-- TRUNCATE NÃO dispara gatilhos de linha. O gatilho trg_historico_append_only
-- é `for each row`, então ele bloqueia UPDATE e DELETE mas passa reto num
-- TRUNCATE. Qualquer papel com esse privilégio podia apagar o histórico
-- inteiro — justamente o único dado do sistema que não é reconstruível a
-- partir da planilha.
--
-- Esta migração fecha isso por dois caminhos independentes: tira o privilégio
-- de quem não precisa, e adiciona um gatilho de statement que barra TRUNCATE
-- mesmo de quem ainda o tenha (inclusive o dono da tabela).


-- ---------------------------------------------------------------------------
-- authenticated: só leitura, nada além disso
-- ---------------------------------------------------------------------------
-- O cliente logado lê o próprio processo. Não referencia, não cria gatilho e
-- não esvazia tabela.
revoke truncate, references, trigger on public.processos                 from authenticated;
revoke truncate, references, trigger on public.titulares                 from authenticated;
revoke truncate, references, trigger on public.etapas_catalogo           from authenticated;
revoke truncate, references, trigger on public.processo_etapas           from authenticated;
revoke truncate, references, trigger on public.processo_etapas_historico from authenticated;


-- ---------------------------------------------------------------------------
-- service_role: mantém o que o sync usa, perde o que ele nunca usou
-- ---------------------------------------------------------------------------
-- As permissões de dados (SELECT/INSERT/UPDATE/DELETE da migração 500)
-- continuam intactas. Some só o que não tem uso e amplia o estrago em caso de
-- vazamento da chave.
revoke truncate, references, trigger on public.processos                 from service_role;
revoke truncate, references, trigger on public.titulares                 from service_role;
revoke truncate, references, trigger on public.etapas_catalogo           from service_role;
revoke truncate, references, trigger on public.processo_etapas           from service_role;
revoke truncate, references, trigger on public.processo_etapas_historico from service_role;


-- ---------------------------------------------------------------------------
-- Gatilho de statement: TRUNCATE no histórico é proibido
-- ---------------------------------------------------------------------------
-- Defesa em profundidade. O revoke acima resolve para anon, authenticated e
-- service_role; este gatilho vale também para o dono da tabela e para quem
-- ganhar o privilégio no futuro.
--
-- Para uma limpeza excepcional, o procedimento é o mesmo do gatilho de linha:
--   alter table public.processo_etapas_historico
--     disable trigger trg_historico_sem_truncate;
create or replace function public.bloquear_truncate_historico()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'processo_etapas_historico é append-only: TRUNCATE bloqueado. '
    'O histórico é o único dado do sistema que não se reconstrói a partir '
    'da planilha. Para manutenção excepcional, desabilite o gatilho '
    'trg_historico_sem_truncate.';
end;
$$;

drop trigger if exists trg_historico_sem_truncate on public.processo_etapas_historico;

create trigger trg_historico_sem_truncate
  before truncate on public.processo_etapas_historico
  for each statement execute function public.bloquear_truncate_historico();


-- ---------------------------------------------------------------------------
-- Conferência
-- ---------------------------------------------------------------------------
-- Não testa o TRUNCATE aqui: uma verificação destrutiva numa migração é risco
-- desnecessário. A prova está em supabase/tests/04_truncate_bloqueado.sql, que
-- tenta de verdade e desfaz.
do $$
declare
  sobrando text;
  gatilhos int;
begin
  select string_agg(distinct g.table_name || '.' || g.privilege_type || ' (' || g.grantee || ')', ', ')
    into sobrando
    from information_schema.role_table_grants g
   where g.grantee in ('anon', 'authenticated', 'service_role')
     and g.table_schema = 'public'
     and g.privilege_type in ('TRUNCATE', 'REFERENCES', 'TRIGGER')
     and g.table_name in ('processos','titulares','etapas_catalogo',
                          'processo_etapas','processo_etapas_historico');

  if sobrando is not null then
    raise exception 'Privilégios que deveriam ter sido revogados: %', sobrando;
  end if;

  select count(*) into gatilhos
    from pg_trigger
   where tgname in ('trg_historico_append_only', 'trg_historico_sem_truncate')
     and not tgisinternal;

  if gatilhos <> 2 then
    raise exception
      'Esperados 2 gatilhos protegendo o histórico, encontrados %.', gatilhos;
  end if;

  -- `authenticated` precisa continuar lendo: revogar demais quebraria o site.
  if not exists (
    select 1 from information_schema.role_table_grants
     where grantee = 'authenticated' and table_schema = 'public'
       and table_name = 'processos' and privilege_type = 'SELECT'
  ) then
    raise exception 'authenticated perdeu o SELECT em processos.';
  end if;
end;
$$;


-- Matriz final
select table_name  as tabela,
       grantee     as papel,
       string_agg(privilege_type, ', ' order by privilege_type) as permissoes
  from information_schema.role_table_grants
 where table_schema = 'public'
   and grantee in ('anon', 'authenticated', 'service_role')
   and table_name in ('processos','titulares','etapas_catalogo',
                      'processo_etapas','processo_etapas_historico')
 group by table_name, grantee
 order by table_name, grantee;
