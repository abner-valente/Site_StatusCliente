-- Royal Imóveis — Site de status do cliente
-- Migração 4 de 4: permissões de tabela para o papel `authenticated`.
--
-- Por que esta migração existe
-- ----------------------------
-- RLS e GRANT são camadas diferentes e independentes. A política de RLS diz
-- QUAIS LINHAS um papel pode ver; o GRANT diz se ele pode tocar a tabela.
-- Sem o GRANT, a política nunca chega a ser avaliada e o Postgres responde
-- "permission denied for table processos".
--
-- A migração 300 confiava nas permissões padrão do Supabase para tabelas novas
-- em `public`. Neste projeto elas não foram aplicadas, e o teste de isolamento
-- (supabase/tests/02_rls_isolamento.sql) expôs a falha: todo cliente logado
-- receberia erro de permissão e o site não funcionaria para ninguém.
--
-- Lição de manutenção: não confiar em privilégio padrão. Toda tabela nova que
-- o site precise ler exige um GRANT explícito aqui.

-- O cliente do Supabase precisa de USAGE no schema mesmo antes de autenticar,
-- senão nem a tela de login sobe. Os revokes de tabela da migração 300
-- continuam protegendo os dados do visitante anônimo.
grant usage on schema public to anon, authenticated;

-- Somente leitura. Não existe grant de INSERT, UPDATE ou DELETE de propósito:
-- toda escrita vem do sync, pela service_role, que ignora RLS e GRANT.
grant select on public.processos                 to authenticated;
grant select on public.titulares                 to authenticated;
grant select on public.etapas_catalogo           to authenticated;
grant select on public.processo_etapas           to authenticated;
grant select on public.processo_etapas_historico to authenticated;

-- A função de apoio da RLS precisa ser executável por quem está logado.
grant execute on function public.processos_do_titular() to authenticated;


-- Conferência: falha a migração se algum GRANT não tiver sido aplicado.
do $$
declare
  n int;
begin
  select count(*) into n
    from information_schema.role_table_grants
   where grantee    = 'authenticated'
     and table_schema = 'public'
     and privilege_type = 'SELECT'
     and table_name in ('processos','titulares','etapas_catalogo',
                        'processo_etapas','processo_etapas_historico');

  if n <> 5 then
    raise exception 'Esperado SELECT em 5 tabelas para authenticated, encontrado %.', n;
  end if;
end;
$$;
