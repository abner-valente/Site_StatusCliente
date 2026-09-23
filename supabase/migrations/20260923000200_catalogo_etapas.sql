-- Royal Imóveis — Site de status do cliente
-- Migração 2 de 3: catálogo das etapas.
--
-- 19 linhas: 10 à vista + 9 financiado, conforme a planilha reestruturada em
-- setembro/2026 (abas "Fluxo A Vista" e "Fluxo Financiado").
--
-- As 5 primeiras etapas e as 3 últimas são idênticas nas duas modalidades; a
-- divergência fica só no meio. Os códigos compartilhados são o que permite
-- comparar as duas modalidades numa métrica só.
--
-- rotulo_interno  = texto da planilha SEM o prefixo ordinal
-- rotulo_publico  = o que o comprador lê na tela
--
-- Este arquivo é seguro de reaplicar: o ON CONFLICT atualiza os rótulos sem
-- tocar nos códigos. É assim que se corrige um texto que o cliente lê.
--
-- ATENÇÃO: os rótulos públicos abaixo são proposta inicial e precisam de
-- aprovação de alguém da Royal antes do lançamento.


insert into public.etapas_catalogo (modalidade, ordem, codigo, rotulo_interno, rotulo_publico) values

  -- ----- À vista (10 etapas) -----
  ('avista',  1, 'minuta',
   'Envio de documento para minuta de Instrumento particular',
   'Preparação da minuta do contrato'),

  ('avista',  2, 'onus',
   'Análise e assinatura / pagamento de Ônus pelo Corretor/Royal',
   'Análise e quitação de ônus'),

  ('avista',  3, 'sinal',
   'Transferência do sinal em recursos próprios',
   'Pagamento do sinal'),

  ('avista',  4, 'certidoes',
   'Tirar certidões (E-Cartório e gratuitas)',
   'Emissão de certidões'),

  ('avista',  5, 'itbi',
   'Gerar ITBI após todas as certidões estarem prontas',
   'Emissão do ITBI'),

  ('avista',  6, 'amaurilio',
   'Enviar documentação para o Amaurílio e abrir processo',
   'Documentação em análise no cartório'),

  ('avista',  7, 'agendamento_escritura',
   'Agendamento de escritura',
   'Agendamento da escritura'),

  ('avista',  8, 'entrada_rgi',
   'Enviar escritura para dar entrada no 9° RGI',
   'Escritura enviada para registro'),

  ('avista',  9, 'protocolo',
   'Acompanhar protocolo do Registro do imóvel',
   'Registro em andamento'),

  ('avista', 10, 'pasta',
   'Fazer a pasta com a documentação e enviar para o cliente',
   'Entrega da documentação final'),

  -- ----- Financiado (9 etapas) -----
  ('financiado', 1, 'minuta',
   'Envio de documento para minuta de Instrumento particular',
   'Preparação da minuta do contrato'),

  ('financiado', 2, 'onus',
   'Análise e assinatura / pagamento de Ônus pelo Corretor/Royal',
   'Análise e quitação de ônus'),

  ('financiado', 3, 'sinal',
   'Transferência do sinal em recursos próprios',
   'Pagamento do sinal'),

  ('financiado', 4, 'certidoes',
   'Tirar certidões (E-Cartório e gratuitas)',
   'Emissão de certidões'),

  ('financiado', 5, 'itbi',
   'Gerar ITBI após todas as certidões estarem prontas',
   'Emissão do ITBI'),

  ('financiado', 6, 'contrato_banco',
   'Esperar o contrato do banco chegar e agendar assinatura',
   'Aguardando contrato do banco'),

  ('financiado', 7, 'entrada_rgi',
   'Enviar contrato para dar entrada no 9° RGI',
   'Contrato enviado para registro'),

  ('financiado', 8, 'protocolo',
   'Acompanhar protocolo do Registro do imóvel',
   'Registro em andamento'),

  ('financiado', 9, 'pasta',
   'Fazer a pasta com a documentação e enviar para o cliente',
   'Entrega da documentação final')

on conflict (modalidade, codigo) do update
  set ordem          = excluded.ordem,
      rotulo_interno = excluded.rotulo_interno,
      rotulo_publico = excluded.rotulo_publico;


-- Conferência: a migração falha se o catálogo não ficar exatamente como o
-- esperado. É barato e evita descobrir o problema só na carga inicial.
do $$
declare
  n_avista     int;
  n_financiado int;
begin
  select count(*) into n_avista     from public.etapas_catalogo where modalidade = 'avista';
  select count(*) into n_financiado from public.etapas_catalogo where modalidade = 'financiado';

  if n_avista <> 10 then
    raise exception 'Catálogo à vista tem % etapas, esperado 10.', n_avista;
  end if;

  if n_financiado <> 9 then
    raise exception 'Catálogo financiado tem % etapas, esperado 9.', n_financiado;
  end if;
end;
$$;
