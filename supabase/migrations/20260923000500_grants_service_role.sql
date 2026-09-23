-- Royal Imóveis — Site de status do cliente
-- Migração 5 de 5: permissões de tabela para o papel `service_role`.
--
-- Por que esta migração existe
-- ----------------------------
-- Mesma causa da migração 400: os privilégios padrão do Supabase não foram
-- aplicados neste projeto. A 400 concedeu acesso a `authenticated` mas não
-- generalizou para `service_role`, e o sync quebrou na primeira execução com
-- `permission denied for table etapas_catalogo`.
--
-- `service_role` ignora RLS, mas NÃO ignora GRANT. São coisas diferentes:
-- BYPASSRLS dispensa a política de linha; o grant continua sendo exigido para
-- tocar a tabela.
--
-- As permissões abaixo seguem o que o sync realmente faz, não "tudo por via
-- das dúvidas". O que está de fora está de fora de propósito.

grant usage on schema public to service_role;


-- Catálogo: o sync só lê. Quem escreve nele é a migração 200, que roda como
-- postgres.
grant select on public.etapas_catalogo to service_role;


-- Processos: sem DELETE de propósito. A regra do projeto é soft delete —
-- processo que some da planilha vira `ativo = false`, o que é um UPDATE.
-- Sem o grant de DELETE, um bug no sync não consegue apagar processo nenhum.
grant select, insert, update on public.processos to service_role;


-- Etapas: estado derivado da planilha, pode ser reconstruído. DELETE liberado
-- porque um processo que mude de modalidade precisa trocar o conjunto inteiro.
grant select, insert, update, delete on public.processo_etapas to service_role;


-- Histórico: só leitura e inserção. É append-only por desenho, e o gatilho
-- trg_historico_append_only já bloqueia UPDATE e DELETE — mas a ausência do
-- grant é a primeira barreira, antes de o gatilho precisar agir.
grant select, insert on public.processo_etapas_historico to service_role;


-- Titulares: DELETE liberado porque tirar alguém da aba Titulares precisa
-- revogar o acesso dele de verdade.
grant select, insert, update, delete on public.titulares to service_role;


-- Sequências das colunas serial/identity.
grant usage, select on all sequences in schema public to service_role;


-- Funções chamadas pelo sync.
grant execute on function public.vincular_titulares_pendentes() to service_role;
grant execute on function public.processos_do_titular()         to service_role;


-- ---------------------------------------------------------------------------
-- Conferência
-- ---------------------------------------------------------------------------
-- Falha a migração se algum grant necessário não tiver entrado, em vez de
-- deixar o erro aparecer só na próxima execução do sync.
--
-- Confere PRESENÇA, não contagem total. Contar é frágil: a mesma permissão
-- concedida por dois grantors diferentes aparece duas vezes nesta view, e o
-- projeto pode ter grants legítimos além destes. Uma versão anterior desta
-- migração exigia exatamente 14 linhas, encontrou 29 e abortou a transação —
-- desfazendo os próprios grants que tinha acabado de aplicar.
do $$
declare
  faltando text;
begin
  select string_agg(t.tabela || '.' || t.priv, ', ' order by t.tabela, t.priv)
    into faltando
    from (values
      ('etapas_catalogo',           'SELECT'),
      ('processos',                 'SELECT'),
      ('processos',                 'INSERT'),
      ('processos',                 'UPDATE'),
      ('processo_etapas',           'SELECT'),
      ('processo_etapas',           'INSERT'),
      ('processo_etapas',           'UPDATE'),
      ('processo_etapas',           'DELETE'),
      ('processo_etapas_historico', 'SELECT'),
      ('processo_etapas_historico', 'INSERT'),
      ('titulares',                 'SELECT'),
      ('titulares',                 'INSERT'),
      ('titulares',                 'UPDATE'),
      ('titulares',                 'DELETE')
    ) as t(tabela, priv)
   where not exists (
     select 1
       from information_schema.role_table_grants g
      where g.grantee        = 'service_role'
        and g.table_schema   = 'public'
        and g.table_name     = t.tabela
        and g.privilege_type = t.priv
   );

  if faltando is not null then
    raise exception 'Faltam grants para service_role: %', faltando;
  end if;
end;
$$;


-- Matriz de permissões, para conferir de uma vez em vez de descobrir a
-- próxima falta por tentativa e erro.
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
