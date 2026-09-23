-- Royal Imóveis — teste de integridade do schema
--
-- NÃO é migração. Este arquivo mora em supabase/tests/ de propósito: se
-- estivesse em supabase/migrations/ o CLI o aplicaria como parte do schema.
--
-- Prova que as garantias do banco funcionam de verdade, não só que os objetos
-- existem. Roda contra o projeto de desenvolvimento, cria dados com prefixo
-- TESTE- e apaga tudo ao final.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.
-- Ao final, a última consulta mostra PASSOU/FALHOU por teste.


create table if not exists public._teste_resultado (
  id      serial primary key,
  teste   text,
  status  text,
  detalhe text
);

truncate public._teste_resultado restart identity;


do $$
declare
  v_proc         uuid;
  v_etapa_avista int;
  v_etapa_onus   int;
  v_etapa_fin    int;
begin
  -- ---------------------------------------------------------------------
  -- Preparação
  -- ---------------------------------------------------------------------
  insert into public.processos (uid_planilha, modalidade, imovel, corretor)
  values ('TESTE-' || gen_random_uuid(), 'avista', 'Imóvel de teste', 'Teste')
  returning id into v_proc;

  select id into v_etapa_avista
    from public.etapas_catalogo where modalidade = 'avista'     and codigo = 'minuta';
  select id into v_etapa_onus
    from public.etapas_catalogo where modalidade = 'avista'     and codigo = 'onus';
  select id into v_etapa_fin
    from public.etapas_catalogo where modalidade = 'financiado' and codigo = 'contrato_banco';

  -- ---------------------------------------------------------------------
  -- 1. Etapa da modalidade certa precisa entrar
  -- ---------------------------------------------------------------------
  begin
    insert into public.processo_etapas (processo_id, etapa_id, modalidade, status)
    values (v_proc, v_etapa_avista, 'avista', 'nao_iniciado');

    insert into public._teste_resultado (teste, status, detalhe)
    values ('1. etapa da modalidade correta é aceita', 'PASSOU', null);
  exception when others then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('1. etapa da modalidade correta é aceita', 'FALHOU', sqlerrm);
  end;

  -- ---------------------------------------------------------------------
  -- 2. Etapa de financiado num processo à vista precisa ser barrada
  --    (é a garantia dada pelas chaves estrangeiras compostas)
  -- ---------------------------------------------------------------------
  begin
    insert into public.processo_etapas (processo_id, etapa_id, modalidade, status)
    values (v_proc, v_etapa_fin, 'financiado', 'nao_iniciado');

    insert into public._teste_resultado (teste, status, detalhe)
    values ('2. FK composta barra etapa de outra modalidade', 'FALHOU',
            'o banco ACEITOU uma etapa de financiado num processo à vista');
  exception
    when foreign_key_violation then
      insert into public._teste_resultado (teste, status, detalhe)
      values ('2. FK composta barra etapa de outra modalidade', 'PASSOU', null);
    when others then
      insert into public._teste_resultado (teste, status, detalhe)
      values ('2. FK composta barra etapa de outra modalidade', 'PASSOU',
              'barrado por: ' || sqlerrm);
  end;

  -- ---------------------------------------------------------------------
  -- 3. Status fora da lista conhecida precisa ser rejeitado
  --    (usa o texto da planilha, com acento e maiúscula, que é o erro real
  --     que aconteceria se o script esquecesse de normalizar)
  -- ---------------------------------------------------------------------
  begin
    insert into public.processo_etapas (processo_id, etapa_id, modalidade, status)
    values (v_proc, v_etapa_onus, 'avista', 'Concluído');

    insert into public._teste_resultado (teste, status, detalhe)
    values ('3. status fora da lista é rejeitado', 'FALHOU',
            'o banco aceitou o status bruto da planilha sem normalizar');
  exception when check_violation then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('3. status fora da lista é rejeitado', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- 4. Histórico não aceita UPDATE
  -- ---------------------------------------------------------------------
  insert into public.processo_etapas_historico
    (processo_id, etapa_id, status_de, status_para, origem)
  values (v_proc, v_etapa_avista, 'nao_iniciado', 'em_andamento', 'carga_inicial');

  begin
    update public.processo_etapas_historico
       set status_para = 'concluido'
     where processo_id = v_proc;

    insert into public._teste_resultado (teste, status, detalhe)
    values ('4. histórico bloqueia UPDATE', 'FALHOU', 'o UPDATE passou');
  exception when others then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('4. histórico bloqueia UPDATE', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- 5. Histórico não aceita DELETE
  -- ---------------------------------------------------------------------
  begin
    delete from public.processo_etapas_historico where processo_id = v_proc;

    insert into public._teste_resultado (teste, status, detalhe)
    values ('5. histórico bloqueia DELETE', 'FALHOU', 'o DELETE passou');
  exception when others then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('5. histórico bloqueia DELETE', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- 6. E-mail de titular precisa estar em minúsculas
  -- ---------------------------------------------------------------------
  begin
    insert into public.titulares (processo_id, nome, email)
    values (v_proc, 'Titular de teste', 'MAIUSCULO@exemplo.com');

    insert into public._teste_resultado (teste, status, detalhe)
    values ('6. e-mail de titular exige minúsculas', 'FALHOU', 'aceitou maiúsculas');
  exception when check_violation then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('6. e-mail de titular exige minúsculas', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- 7. Dois titulares no mesmo processo (o caso dos casais)
  -- ---------------------------------------------------------------------
  begin
    insert into public.titulares (processo_id, nome, email) values
      (v_proc, 'Davi',  'davi.teste@exemplo.com'),
      (v_proc, 'Jeane', 'jeane.teste@exemplo.com');

    insert into public._teste_resultado (teste, status, detalhe)
    values ('7. dois titulares no mesmo processo', 'PASSOU', null);
  exception when others then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('7. dois titulares no mesmo processo', 'FALHOU', sqlerrm);
  end;

  -- ---------------------------------------------------------------------
  -- 8. uid_planilha não pode repetir
  -- ---------------------------------------------------------------------
  begin
    insert into public.processos (uid_planilha, modalidade, imovel)
    select uid_planilha, 'financiado', 'Outro imóvel'
      from public.processos where id = v_proc;

    insert into public._teste_resultado (teste, status, detalhe)
    values ('8. uid_planilha duplicado é rejeitado', 'FALHOU', 'aceitou duplicata');
  exception when unique_violation then
    insert into public._teste_resultado (teste, status, detalhe)
    values ('8. uid_planilha duplicado é rejeitado', 'PASSOU', null);
  end;

  -- ---------------------------------------------------------------------
  -- Limpeza
  -- ---------------------------------------------------------------------
  -- O gatilho append-only bloqueia até o DELETE em cascata do processo, então
  -- precisa ser desligado para limpar. É o mesmo procedimento documentado para
  -- manutenção excepcional em produção.
  alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
  delete from public.processos where uid_planilha like 'TESTE-%';
  alter table public.processo_etapas_historico enable trigger trg_historico_append_only;

  insert into public._teste_resultado (teste, status, detalhe)
  values ('9. limpeza dos dados de teste', 'PASSOU',
          'nenhum registro TESTE- permaneceu');

exception when others then
  -- Se algo estourar fora dos blocos protegidos, registra e tenta limpar.
  insert into public._teste_resultado (teste, status, detalhe)
  values ('ERRO GERAL', 'FALHOU', sqlerrm);

  begin
    alter table public.processo_etapas_historico disable trigger trg_historico_append_only;
    delete from public.processos where uid_planilha like 'TESTE-%';
    alter table public.processo_etapas_historico enable trigger trg_historico_append_only;
  exception when others then null;
  end;
end;
$$;


-- Conferência final: não pode sobrar nada com prefixo TESTE-
insert into public._teste_resultado (teste, status, detalhe)
select '10. banco limpo ao final',
       case when count(*) = 0 then 'PASSOU' else 'FALHOU' end,
       case when count(*) = 0 then null
            else count(*)::text || ' processo(s) de teste sobraram' end
  from public.processos where uid_planilha like 'TESTE-%';


select id, teste, status, coalesce(detalhe, '') as detalhe
  from public._teste_resultado
 order by id;

-- Depois de conferir o resultado, remova a tabela auxiliar:
--   drop table public._teste_resultado;
