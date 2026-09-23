-- Royal Imóveis — limpeza de histórico duplicado da carga inicial
--
-- NÃO é migração. É um utilitário de manutenção, para rodar uma vez.
--
-- Por que existe
-- --------------
-- A primeira versão da carga inicial inseria o histórico de partida a cada
-- execução, em vez de só para processos recém-criados. Quem rodou
-- `carga_inicial.py --aplicar` mais de uma vez tem linhas repetidas com
-- `origem = 'carga_inicial'`.
--
-- O script já foi corrigido: agora só grava o ponto de partida dos processos
-- que ele acabou de criar. Este arquivo limpa o que ficou para trás.
--
-- O que ele faz
-- -------------
-- Mantém a linha MAIS ANTIGA de cada (processo, etapa) com origem
-- 'carga_inicial' e apaga as demais. Não toca em linha alguma com origem
-- 'sync' ou 'correcao' — histórico real nunca é apagado por este script.
--
-- Precisa desligar o gatilho append-only, que é o procedimento documentado
-- para manutenção excepcional. Ele é religado ao final, inclusive em caso de
-- erro.
--
-- Como rodar: colar inteiro no SQL Editor e executar uma vez.


-- Antes
select 'antes' as momento,
       count(*)                                          as linhas_carga_inicial,
       count(distinct (processo_id, etapa_id))           as pares_processo_etapa
  from public.processo_etapas_historico
 where origem = 'carga_inicial';


do $$
declare
  removidas int;
begin
  alter table public.processo_etapas_historico
    disable trigger trg_historico_append_only;

  with ranqueadas as (
    select id,
           row_number() over (
             partition by processo_id, etapa_id
             order by em, id
           ) as posicao
      from public.processo_etapas_historico
     where origem = 'carga_inicial'
  )
  delete from public.processo_etapas_historico h
   using ranqueadas r
   where h.id = r.id
     and r.posicao > 1;

  get diagnostics removidas = row_count;

  alter table public.processo_etapas_historico
    enable trigger trg_historico_append_only;

  raise notice 'Removidas % linha(s) duplicada(s).', removidas;

exception when others then
  -- O gatilho precisa voltar mesmo se algo falhar no meio.
  begin
    alter table public.processo_etapas_historico
      enable trigger trg_historico_append_only;
  exception when others then null;
  end;
  raise;
end;
$$;


-- Depois: as duas colunas precisam ficar iguais, e o gatilho precisa estar
-- habilitado de novo ('O' = origin, ou seja, ligado).
select 'depois' as momento,
       (select count(*) from public.processo_etapas_historico
         where origem = 'carga_inicial')                          as linhas_carga_inicial,
       (select count(distinct (processo_id, etapa_id))
          from public.processo_etapas_historico
         where origem = 'carga_inicial')                          as pares_processo_etapa,
       (select tgenabled from pg_trigger
         where tgname = 'trg_historico_append_only')              as gatilho;
