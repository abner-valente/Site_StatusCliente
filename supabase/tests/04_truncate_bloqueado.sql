-- Royal Imóveis — teste: TRUNCATE no histórico é bloqueado
--
-- NÃO é migração. Ver o cabeçalho de 01_integridade.sql.
--
-- Por que este teste existe separado
-- ----------------------------------
-- TRUNCATE não dispara gatilho de linha. O trg_historico_append_only é
-- `for each row`, então ele barra UPDATE e DELETE mas passaria reto num
-- TRUNCATE — e o histórico é o único dado do sistema que não se reconstrói a
-- partir da planilha.
--
-- A migração 600 fechou isso com um gatilho `before truncate ... for each
-- statement`. Este arquivo prova que funciona.
--
-- Segurança do teste
-- ------------------
-- Ele tenta o TRUNCATE de verdade. Se o gatilho falhar e o comando passar, a
-- transação é abortada de propósito e o Postgres desfaz tudo — TRUNCATE é
-- transacional. O histórico real nunca corre risco, mas o resultado avisa
-- alto que a proteção não está no lugar.
--
-- PRÉ-REQUISITO: migração 20260923000600_endurecer_permissoes.sql aplicada.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.


create table if not exists public._teste_truncate (
  id      serial primary key,
  teste   text,
  status  text,
  detalhe text
);

truncate public._teste_truncate restart identity;


do $$
declare
  n_antes  int;
  n_depois int;
begin
  select count(*) into n_antes from public.processo_etapas_historico;

  -- ---------------------------------------------------------------------
  -- 1. TRUNCATE precisa ser recusado
  -- ---------------------------------------------------------------------
  begin
    truncate public.processo_etapas_historico;

    -- Chegar aqui significa que o gatilho não agiu. Levantar aborta a
    -- transação e desfaz o TRUNCATE.
    raise exception 'TRUNCATE_PASSOU';
  exception
    when others then
      if sqlerrm = 'TRUNCATE_PASSOU' then
        raise exception
          'PROTEÇÃO AUSENTE: o TRUNCATE no histórico foi aceito. '
          'A transação foi desfeita e nenhum dado se perdeu, mas aplique a '
          'migração 20260923000600_endurecer_permissoes.sql antes de seguir.';
      end if;

      insert into public._teste_truncate (teste, status, detalhe)
      values ('1. TRUNCATE no histórico é bloqueado', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- 2. O histórico continua inteiro
  -- ---------------------------------------------------------------------
  select count(*) into n_depois from public.processo_etapas_historico;

  insert into public._teste_truncate (teste, status, detalhe)
  values ('2. histórico intacto depois da tentativa',
          case when n_antes = n_depois then 'PASSOU' else 'FALHOU' end,
          n_antes::text || ' antes, ' || n_depois::text || ' depois');

  -- ---------------------------------------------------------------------
  -- 3. Os dois gatilhos de proteção existem
  -- ---------------------------------------------------------------------
  insert into public._teste_truncate (teste, status, detalhe)
  select '3. gatilhos de proteção no lugar',
         case when count(*) = 2 then 'PASSOU' else 'FALHOU' end,
         string_agg(tgname, ', ' order by tgname)
    from pg_trigger
   where tgname in ('trg_historico_append_only', 'trg_historico_sem_truncate')
     and not tgisinternal;

  -- ---------------------------------------------------------------------
  -- 4. Nenhum papel da aplicação ainda tem TRUNCATE
  -- ---------------------------------------------------------------------
  insert into public._teste_truncate (teste, status, detalhe)
  select '4. anon, authenticated e service_role sem TRUNCATE',
         case when count(*) = 0 then 'PASSOU' else 'FALHOU' end,
         nullif(string_agg(table_name || ' (' || grantee || ')', ', '), '')
    from information_schema.role_table_grants
   where grantee in ('anon', 'authenticated', 'service_role')
     and table_schema = 'public'
     and privilege_type = 'TRUNCATE'
     and table_name in ('processos','titulares','etapas_catalogo',
                        'processo_etapas','processo_etapas_historico');
end;
$$;


select id, teste, status, coalesce(detalhe, '') as detalhe
  from public._teste_truncate
 order by id;

-- Depois de conferir:
--   drop table public._teste_truncate;
