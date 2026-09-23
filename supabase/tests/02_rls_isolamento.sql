-- Royal Imóveis — teste de isolamento por cliente (RLS)
--
-- NÃO é migração. Ver o cabeçalho de 01_integridade.sql.
--
-- Este é o teste mais importante do projeto. Ele prova que o titular do
-- processo A enxerga zero linhas do processo B, em todas as tabelas.
-- Configuração errada de RLS não aparece na interface — só aqui.
--
-- Método: cria dois processos, dois titulares e dois usuários, depois assume a
-- identidade do titular A (role `authenticated` + claim `sub` do JWT, que é
-- exatamente o que o Supabase faz quando o cliente está logado) e conta o que
-- ele consegue ler. Ao final apaga tudo.
--
-- PRÉ-REQUISITO: a migração 20260923000400_grants.sql precisa estar aplicada.
-- Sem ela o teste falha com "permission denied for table processos", porque
-- GRANT e RLS são camadas independentes.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.


create table if not exists public._teste_rls (
  id       serial primary key,
  teste    text,
  esperado text,
  obtido   text,
  status   text
);

truncate public._teste_rls restart identity;


do $$
declare
  v_proc_a  uuid;
  v_proc_b  uuid;
  v_user_a  uuid := gen_random_uuid();
  v_user_b  uuid := gen_random_uuid();
  v_etapa   int;

  n_vinc_a  int;
  n_vinc_b  int;
  n_backfil int;

  -- Começam nulos de propósito: se a etapa de leitura falhar, o resultado sai
  -- como FALHOU em vez de dar um número enganoso.
  n_proc    int;
  n_proc_b  int;
  n_etapas  int;
  n_titul   int;
  n_hist    int;
  n_catal   int;
  n_anon    int;

  v_erro    text := null;
begin
  -- =====================================================================
  -- Preparação
  -- =====================================================================
  select id into v_etapa
    from public.etapas_catalogo where modalidade = 'avista' and codigo = 'minuta';

  insert into public.processos (uid_planilha, modalidade, imovel, corretor)
  values ('TESTERLS-A', 'avista', 'Imóvel do titular A', 'Corretor teste')
  returning id into v_proc_a;

  insert into public.processos (uid_planilha, modalidade, imovel, corretor)
  values ('TESTERLS-B', 'avista', 'Imóvel do titular B', 'Corretor teste')
  returning id into v_proc_b;

  insert into public.processo_etapas (processo_id, etapa_id, modalidade, status) values
    (v_proc_a, v_etapa, 'avista', 'concluido'),
    (v_proc_b, v_etapa, 'avista', 'concluido');

  insert into public.processo_etapas_historico
    (processo_id, etapa_id, status_de, status_para, origem) values
    (v_proc_a, v_etapa, 'nao_iniciado', 'concluido', 'carga_inicial'),
    (v_proc_b, v_etapa, 'nao_iniciado', 'concluido', 'carga_inicial');

  -- =====================================================================
  -- 1. Vínculo pelo gatilho: titular cadastrado ANTES do primeiro login
  -- =====================================================================
  insert into public.titulares (processo_id, nome, email)
  values (v_proc_a, 'Titular A', 'titular.a.teste@exemplo.com');

  -- o gatilho em auth.users deve preencher auth_uid sozinho
  insert into auth.users (id, email) values (v_user_a, 'titular.a.teste@exemplo.com');

  select count(*) into n_vinc_a
    from public.titulares where processo_id = v_proc_a and auth_uid = v_user_a;

  -- =====================================================================
  -- 2. Vínculo pelo backfill: usuário criado ANTES do e-mail entrar na planilha
  -- =====================================================================
  insert into auth.users (id, email) values (v_user_b, 'titular.b.teste@exemplo.com');

  insert into public.titulares (processo_id, nome, email)
  values (v_proc_b, 'Titular B', 'titular.b.teste@exemplo.com');

  select public.vincular_titulares_pendentes() into n_backfil;

  select count(*) into n_vinc_b
    from public.titulares where processo_id = v_proc_b and auth_uid = v_user_b;

  -- =====================================================================
  -- Assume a identidade do titular A
  -- =====================================================================
  -- Bloco próprio: se a leitura falhar, os resultados 1 e 2 sobrevivem. Sem
  -- isso, um erro aqui desfaz tudo o que o bloco externo já tinha gravado e o
  -- diagnóstico perde o contexto.
  begin
    -- Mesmo estado que o PostgREST monta quando o cliente chega logado:
    -- role `authenticated` e a claim `sub` com o id do usuário.
    perform set_config('role', 'authenticated', true);
    perform set_config('request.jwt.claims',
                       json_build_object('sub', v_user_a, 'role', 'authenticated')::text,
                       true);

    select count(*) into n_proc
      from public.processos where uid_planilha like 'TESTERLS-%';

    select count(*) into n_proc_b
      from public.processos where id = v_proc_b;

    select count(*) into n_etapas
      from public.processo_etapas where processo_id in (v_proc_a, v_proc_b);

    select count(*) into n_titul
      from public.titulares where processo_id in (v_proc_a, v_proc_b);

    select count(*) into n_hist
      from public.processo_etapas_historico where processo_id in (v_proc_a, v_proc_b);

    select count(*) into n_catal
      from public.etapas_catalogo;

    -- Visitante não autenticado
    perform set_config('role', 'anon', true);
    perform set_config('request.jwt.claims', '', true);

    begin
      select count(*) into n_anon
        from public.processos where uid_planilha like 'TESTERLS-%';
    exception when insufficient_privilege then
      -- sem permissão nenhuma também é aprovação
      n_anon := 0;
    end;

    perform set_config('role', 'none', true);
    perform set_config('request.jwt.claims', '', true);

  exception when others then
    perform set_config('role', 'none', true);
    perform set_config('request.jwt.claims', '', true);
    v_erro := sqlerrm;
  end;

  -- =====================================================================
  -- Resultados
  -- =====================================================================
  insert into public._teste_rls (teste, esperado, obtido, status) values
    ('1. gatilho liga titular no primeiro login', '1',
     coalesce(n_vinc_a::text, 'nulo'),
     case when n_vinc_a = 1 then 'PASSOU' else 'FALHOU' end),

    ('2. backfill liga titular cadastrado depois', '1',
     coalesce(n_vinc_b::text, 'nulo'),
     case when n_vinc_b = 1 then 'PASSOU' else 'FALHOU' end),

    ('3. titular A vê apenas o próprio processo', '1',
     coalesce(n_proc::text, 'erro'),
     case when n_proc = 1 then 'PASSOU' else 'FALHOU' end),

    ('4. titular A vê ZERO linhas do processo B', '0',
     coalesce(n_proc_b::text, 'erro'),
     case when n_proc_b = 0 then 'PASSOU' else 'FALHOU' end),

    ('5. titular A vê apenas as próprias etapas', '1',
     coalesce(n_etapas::text, 'erro'),
     case when n_etapas = 1 then 'PASSOU' else 'FALHOU' end),

    ('6. titular A não vê o titular do outro processo', '1',
     coalesce(n_titul::text, 'erro'),
     case when n_titul = 1 then 'PASSOU' else 'FALHOU' end),

    ('7. titular A vê apenas o próprio histórico', '1',
     coalesce(n_hist::text, 'erro'),
     case when n_hist = 1 then 'PASSOU' else 'FALHOU' end),

    ('8. catálogo de etapas é legível por quem está logado', '19',
     coalesce(n_catal::text, 'erro'),
     case when n_catal = 19 then 'PASSOU' else 'FALHOU' end),

    ('9. visitante não autenticado não vê nada', '0',
     coalesce(n_anon::text, 'erro'),
     case when n_anon = 0 then 'PASSOU' else 'FALHOU' end);

  if v_erro is not null then
    insert into public._teste_rls (teste, esperado, obtido, status)
    values ('ERRO durante a leitura como titular A', '-', v_erro, 'FALHOU');
  end if;

  -- =====================================================================
  -- Limpeza
  -- =====================================================================
  alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
  delete from public.processos where uid_planilha like 'TESTERLS-%';
  alter table public.processo_etapas_historico enable trigger trg_historico_append_only;

  delete from auth.users where id in (v_user_a, v_user_b);

exception when others then
  perform set_config('role', 'none', true);

  insert into public._teste_rls (teste, esperado, obtido, status)
  values ('ERRO GERAL (fora da leitura)', '-', sqlerrm, 'FALHOU');

  begin
    alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
    delete from public.processos where uid_planilha like 'TESTERLS-%';
    alter table public.processo_etapas_historico enable trigger trg_historico_append_only;
    delete from auth.users where email like '%.teste@exemplo.com';
  exception when others then null;
  end;
end;
$$;


-- Conferência: nada pode ter sobrado
insert into public._teste_rls (teste, esperado, obtido, status)
select '10. banco limpo ao final', '0', (p.n + u.n)::text,
       case when p.n + u.n = 0 then 'PASSOU' else 'FALHOU' end
  from (select count(*) n from public.processos where uid_planilha like 'TESTERLS-%') p,
       (select count(*) n from auth.users where email like '%.teste@exemplo.com')    u;


select id, teste, esperado, obtido, status
  from public._teste_rls
 order by id;

-- Depois de conferir, remova as tabelas auxiliares:
--   drop table public._teste_rls;
--   drop table public._teste_resultado;
