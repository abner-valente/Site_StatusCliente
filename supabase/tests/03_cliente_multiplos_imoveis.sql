-- Royal Imóveis — teste: um cliente com mais de um imóvel
--
-- NÃO é migração. Ver o cabeçalho de 01_integridade.sql.
--
-- Cenário: a mesma pessoa compra dois imóveis e usa o mesmo e-mail nos dois.
-- Ela precisa enxergar os dois processos com um login só, e continuar sem
-- enxergar o de mais ninguém.
--
-- Também cobre o caso do casal que compartilha uma caixa de entrada: dois
-- nomes, um e-mail, um processo.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.


create table if not exists public._teste_multi (
  id       serial primary key,
  teste    text,
  esperado text,
  obtido   text,
  status   text
);

truncate public._teste_multi restart identity;


do $$
declare
  v_proc_1  uuid;   -- primeiro imóvel do cliente
  v_proc_2  uuid;   -- segundo imóvel do MESMO cliente
  v_proc_3  uuid;   -- imóvel de outra pessoa
  v_user    uuid := gen_random_uuid();
  v_outro   uuid := gen_random_uuid();
  v_etapa   int;

  n_meus    int;
  n_alheio  int;
  n_dupl    int;
  v_erro    text := null;
begin
  select id into v_etapa
    from public.etapas_catalogo where modalidade = 'avista' and codigo = 'minuta';

  insert into public.processos (uid_planilha, modalidade, imovel) values
    ('TESTEMULTI-1', 'avista', 'Primeiro imóvel'),
    ('TESTEMULTI-2', 'avista', 'Segundo imóvel'),
    ('TESTEMULTI-3', 'avista', 'Imóvel de outra pessoa');

  select id into v_proc_1 from public.processos where uid_planilha = 'TESTEMULTI-1';
  select id into v_proc_2 from public.processos where uid_planilha = 'TESTEMULTI-2';
  select id into v_proc_3 from public.processos where uid_planilha = 'TESTEMULTI-3';

  insert into public.processo_etapas (processo_id, etapa_id, modalidade, status) values
    (v_proc_1, v_etapa, 'avista', 'concluido'),
    (v_proc_2, v_etapa, 'avista', 'em_andamento'),
    (v_proc_3, v_etapa, 'avista', 'concluido');

  -- =====================================================================
  -- 1. O mesmo e-mail em processos diferentes é aceito
  -- =====================================================================
  begin
    insert into public.titulares (processo_id, nome, email) values
      (v_proc_1, 'Cliente Multi', 'multi.teste@exemplo.com'),
      (v_proc_2, 'Cliente Multi', 'multi.teste@exemplo.com');

    insert into public._teste_multi (teste, esperado, obtido, status) values
      ('1. mesmo e-mail em dois processos é aceito', 'aceito', 'aceito', 'PASSOU');
  exception when others then
    insert into public._teste_multi (teste, esperado, obtido, status) values
      ('1. mesmo e-mail em dois processos é aceito', 'aceito', sqlerrm, 'FALHOU');
  end;

  insert into public.titulares (processo_id, nome, email)
  values (v_proc_3, 'Outra Pessoa', 'outra.teste@exemplo.com');

  -- =====================================================================
  -- 2. O mesmo e-mail DUAS VEZES no mesmo processo é rejeitado
  -- =====================================================================
  -- É a restrição que o script precisa respeitar deduplicando antes do envio.
  -- Sem isso o upsert tenta tocar a mesma linha duas vezes e o Postgres
  -- devolve o erro 21000.
  begin
    insert into public.titulares (processo_id, nome, email)
    values (v_proc_1, 'Cônjuge', 'multi.teste@exemplo.com');

    insert into public._teste_multi (teste, esperado, obtido, status) values
      ('2. e-mail repetido no mesmo processo é rejeitado',
       'rejeitado', 'aceitou', 'FALHOU');
  exception when unique_violation then
    insert into public._teste_multi (teste, esperado, obtido, status) values
      ('2. e-mail repetido no mesmo processo é rejeitado',
       'rejeitado', 'rejeitado', 'PASSOU');
  end;

  -- =====================================================================
  -- 3. Um login, dois processos
  -- =====================================================================
  insert into auth.users (id, email) values
    (v_user,  'multi.teste@exemplo.com'),
    (v_outro, 'outra.teste@exemplo.com');

  select count(*) into n_dupl
    from public.titulares
   where email = 'multi.teste@exemplo.com' and auth_uid = v_user;

  begin
    perform set_config('role', 'authenticated', true);
    perform set_config('request.jwt.claims',
                       json_build_object('sub', v_user, 'role', 'authenticated')::text,
                       true);

    select count(*) into n_meus
      from public.processos where uid_planilha in ('TESTEMULTI-1', 'TESTEMULTI-2');

    select count(*) into n_alheio
      from public.processos where uid_planilha = 'TESTEMULTI-3';

    perform set_config('role', 'none', true);
    perform set_config('request.jwt.claims', '', true);
  exception when others then
    perform set_config('role', 'none', true);
    perform set_config('request.jwt.claims', '', true);
    v_erro := sqlerrm;
  end;

  insert into public._teste_multi (teste, esperado, obtido, status) values
    ('3. gatilho liga o mesmo e-mail aos dois processos', '2',
     coalesce(n_dupl::text, 'nulo'),
     case when n_dupl = 2 then 'PASSOU' else 'FALHOU' end),

    ('4. cliente vê os DOIS imóveis com um login só', '2',
     coalesce(n_meus::text, 'erro'),
     case when n_meus = 2 then 'PASSOU' else 'FALHOU' end),

    ('5. e continua sem ver o imóvel de outra pessoa', '0',
     coalesce(n_alheio::text, 'erro'),
     case when n_alheio = 0 then 'PASSOU' else 'FALHOU' end);

  if v_erro is not null then
    insert into public._teste_multi (teste, esperado, obtido, status)
    values ('ERRO durante a leitura', '-', v_erro, 'FALHOU');
  end if;

  -- =====================================================================
  -- Limpeza
  -- =====================================================================
  alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
  delete from public.processos where uid_planilha like 'TESTEMULTI-%';
  alter table public.processo_etapas_historico enable trigger trg_historico_append_only;

  delete from auth.users where id in (v_user, v_outro);

exception when others then
  perform set_config('role', 'none', true);

  insert into public._teste_multi (teste, esperado, obtido, status)
  values ('ERRO GERAL', '-', sqlerrm, 'FALHOU');

  begin
    alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
    delete from public.processos where uid_planilha like 'TESTEMULTI-%';
    alter table public.processo_etapas_historico enable trigger trg_historico_append_only;
    delete from auth.users where email like '%.teste@exemplo.com';
  exception when others then null;
  end;
end;
$$;


insert into public._teste_multi (teste, esperado, obtido, status)
select '6. banco limpo ao final', '0', (p.n + u.n)::text,
       case when p.n + u.n = 0 then 'PASSOU' else 'FALHOU' end
  from (select count(*) n from public.processos where uid_planilha like 'TESTEMULTI-%') p,
       (select count(*) n from auth.users where email like '%.teste@exemplo.com')       u;


select id, teste, esperado, obtido, status
  from public._teste_multi
 order by id;

-- Depois de conferir:
--   drop table public._teste_multi;
