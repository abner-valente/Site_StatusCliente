-- Royal Imóveis — teste dos papéis: cliente, corretor, vendedor
--
-- NÃO é migração. Ver o cabeçalho de 01_integridade.sql.
--
-- Prova duas coisas que a migração 700 introduziu, e que a interface não
-- mostraria se estivessem erradas:
--
--   1. ACESSO é agnóstico a papel. Comprador, corretor e vendedor do mesmo
--      processo veem o mesmo processo e as mesmas etapas. É o que faz corretor
--      e vendedor funcionarem sem tela nova — `processos_do_titular()` nunca
--      soube de papel, e tem de continuar sem saber.
--
--   2. QUEM-VÊ-QUEM é restrito ao papel. O comprador não lê o e-mail do
--      vendedor nem o contrário: são partes que negociam entre si. Mas o casal
--      comprador continua se vendo, que é o caso para o qual a política
--      original nasceu.
--
-- A segunda é a que mais importa. Antes da 700 a política mostrava TODOS os
-- titulares do processo a qualquer um deles; com três papéis na mesma tabela
-- isso passaria endereço de gente que não pediu para ser apresentada.
--
-- PRÉ-REQUISITO: migrações 400 e 700 aplicadas. Sem a 400 o teste falha com
-- "permission denied for table processos", porque GRANT e RLS são camadas
-- independentes. Sem a 700 falha na coluna `papel`.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.


create table if not exists public._teste_papeis (
  id       serial primary key,
  teste    text,
  esperado text,
  obtido   text,
  status   text
);

truncate public._teste_papeis restart identity;


do $$
declare
  v_proc_a  uuid;
  v_proc_b  uuid;
  v_etapa   int;

  v_compra1 uuid := gen_random_uuid();
  v_compra2 uuid := gen_random_uuid();
  v_corret  uuid := gen_random_uuid();
  v_vended  uuid := gen_random_uuid();

  -- Nulos de propósito: leitura que falhe sai como FALHOU em vez de dar um
  -- número enganoso.
  n_proc_corret   int;
  n_proc_vended   int;
  n_proc_compra1  int;
  n_etapas_vended int;
  n_tit_compra1   int;
  n_tit_vended    int;
  n_tit_corret    int;
  n_duplo         int;

  v_erro    text := null;
begin
  select id into v_etapa
    from public.etapas_catalogo where modalidade = 'avista' and codigo = 'minuta';

  -- =====================================================================
  -- Preparação: dois processos
  -- =====================================================================
  insert into public.processos (uid_planilha, modalidade, imovel, corretor)
  values ('TESTEPAPEL-A', 'avista', 'Imóvel A', 'Corretor teste')
  returning id into v_proc_a;

  insert into public.processos (uid_planilha, modalidade, imovel, corretor)
  values ('TESTEPAPEL-B', 'avista', 'Imóvel B', 'Corretor teste')
  returning id into v_proc_b;

  insert into public.processo_etapas (processo_id, etapa_id, modalidade, status) values
    (v_proc_a, v_etapa, 'avista', 'concluido'),
    (v_proc_b, v_etapa, 'avista', 'concluido');

  -- Processo A: casal comprador, um corretor, um vendedor.
  insert into public.titulares (processo_id, nome, email, papel) values
    (v_proc_a, 'Comprador 1', 'compra1.papel.teste@exemplo.com', 'cliente'),
    (v_proc_a, 'Comprador 2', 'compra2.papel.teste@exemplo.com', 'cliente'),
    (v_proc_a, 'Corretor',    'corret.papel.teste@exemplo.com',  'corretor'),
    (v_proc_a, 'Vendedor',    'vended.papel.teste@exemplo.com',  'vendedor');

  -- Processo B: o MESMO corretor. É assim que ele vê a carteira dele inteira.
  insert into public.titulares (processo_id, nome, email, papel) values
    (v_proc_b, 'Corretor', 'corret.papel.teste@exemplo.com', 'corretor');

  insert into auth.users (id, email) values
    (v_compra1, 'compra1.papel.teste@exemplo.com'),
    (v_compra2, 'compra2.papel.teste@exemplo.com'),
    (v_corret,  'corret.papel.teste@exemplo.com'),
    (v_vended,  'vended.papel.teste@exemplo.com');

  -- =====================================================================
  -- Dois papéis, mesmo e-mail, mesmo processo
  -- =====================================================================
  -- O corretor que compra pela própria Royal. A chave antiga
  -- (processo_id, email) recusava esta segunda linha; a nova tem de aceitar.
  insert into public.titulares (processo_id, nome, email, papel) values
    (v_proc_b, 'Duplo', 'duplo.papel.teste@exemplo.com', 'cliente'),
    (v_proc_b, 'Duplo', 'duplo.papel.teste@exemplo.com', 'corretor');

  select count(*) into n_duplo
    from public.titulares
   where processo_id = v_proc_b and email = 'duplo.papel.teste@exemplo.com';

  -- =====================================================================
  -- Identidade do CORRETOR
  -- =====================================================================
  -- Bloco próprio: erro de leitura aqui não desfaz o que já foi gravado.
  begin
    perform set_config('role', 'authenticated', true);
    perform set_config('request.jwt.claims',
                       json_build_object('sub', v_corret, 'role', 'authenticated')::text,
                       true);

    -- Vê os dois processos da carteira.
    select count(*) into n_proc_corret
      from public.processos where uid_planilha like 'TESTEPAPEL-%';

    -- Dos titulares, vê só os de papel corretor: ele mesmo, nos dois
    -- processos. Não vê o casal comprador nem o vendedor.
    select count(*) into n_tit_corret
      from public.titulares where processo_id in (v_proc_a, v_proc_b);

    -- =====================================================================
    -- Identidade do VENDEDOR
    -- =====================================================================
    perform set_config('request.jwt.claims',
                       json_build_object('sub', v_vended, 'role', 'authenticated')::text,
                       true);

    select count(*) into n_proc_vended
      from public.processos where uid_planilha like 'TESTEPAPEL-%';

    -- Decisão do cliente em 04/11/2026: vendedor vê a tela inteira.
    select count(*) into n_etapas_vended
      from public.processo_etapas where processo_id in (v_proc_a, v_proc_b);

    select count(*) into n_tit_vended
      from public.titulares where processo_id in (v_proc_a, v_proc_b);

    -- =====================================================================
    -- Identidade do COMPRADOR 1
    -- =====================================================================
    perform set_config('request.jwt.claims',
                       json_build_object('sub', v_compra1, 'role', 'authenticated')::text,
                       true);

    select count(*) into n_proc_compra1
      from public.processos where uid_planilha like 'TESTEPAPEL-%';

    select count(*) into n_tit_compra1
      from public.titulares where processo_id in (v_proc_a, v_proc_b);

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
  insert into public._teste_papeis (teste, esperado, obtido, status) values
    ('1. corretor vê os 2 processos da carteira', '2',
     coalesce(n_proc_corret::text, 'erro'),
     case when n_proc_corret = 2 then 'PASSOU' else 'FALHOU' end),

    ('2. vendedor vê só o processo dele', '1',
     coalesce(n_proc_vended::text, 'erro'),
     case when n_proc_vended = 1 then 'PASSOU' else 'FALHOU' end),

    ('3. comprador vê só o processo dele', '1',
     coalesce(n_proc_compra1::text, 'erro'),
     case when n_proc_compra1 = 1 then 'PASSOU' else 'FALHOU' end),

    ('4. vendedor lê as etapas do processo', '1',
     coalesce(n_etapas_vended::text, 'erro'),
     case when n_etapas_vended = 1 then 'PASSOU' else 'FALHOU' end),

    ('5. comprador vê o casal, não corretor nem vendedor', '2',
     coalesce(n_tit_compra1::text, 'erro'),
     case when n_tit_compra1 = 2 then 'PASSOU' else 'FALHOU' end),

    ('6. vendedor vê só a si mesmo', '1',
     coalesce(n_tit_vended::text, 'erro'),
     case when n_tit_vended = 1 then 'PASSOU' else 'FALHOU' end),

    ('7. corretor vê só a si mesmo, nos 2 processos', '2',
     coalesce(n_tit_corret::text, 'erro'),
     case when n_tit_corret = 2 then 'PASSOU' else 'FALHOU' end),

    ('8. mesmo e-mail com 2 papéis é aceito', '2',
     coalesce(n_duplo::text, 'erro'),
     case when n_duplo = 2 then 'PASSOU' else 'FALHOU' end),

    ('9. nenhum erro durante as leituras', 'sem erro',
     coalesce(v_erro, 'sem erro'),
     case when v_erro is null then 'PASSOU' else 'FALHOU' end);

  -- =====================================================================
  -- Limpeza
  -- =====================================================================
  delete from public.processos where uid_planilha like 'TESTEPAPEL-%';
  delete from auth.users where email like '%.papel.teste@exemplo.com';

exception when others then
  perform set_config('role', 'none', true);
  perform set_config('request.jwt.claims', '', true);

  insert into public._teste_papeis (teste, esperado, obtido, status)
  values ('ERRO NA PREPARAÇÃO', 'sem erro', sqlerrm, 'FALHOU');

  begin
    alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
    delete from public.processos where uid_planilha like 'TESTEPAPEL-%';
    alter table public.processo_etapas_historico enable trigger trg_historico_append_only;
    delete from auth.users where email like '%.papel.teste@exemplo.com';
  exception when others then null;
  end;
end;
$$;


-- Conferência: nada pode ter sobrado
insert into public._teste_papeis (teste, esperado, obtido, status)
select '10. banco limpo ao final', '0', (p.n + u.n)::text,
       case when p.n + u.n = 0 then 'PASSOU' else 'FALHOU' end
  from (select count(*) n from public.processos where uid_planilha like 'TESTEPAPEL-%') p,
       (select count(*) n from auth.users where email like '%.papel.teste@exemplo.com') u;


select id, teste, esperado, obtido, status
  from public._teste_papeis
 order by id;

-- Depois de conferir, remova a tabela auxiliar:
--   drop table public._teste_papeis;
