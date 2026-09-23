-- Royal Imóveis — Site de status do cliente
-- Migração 1 de 3: tabelas, índices e gatilhos de integridade.
--
-- Ordem de aplicação: 100_schema -> 200_catalogo_etapas -> 300_rls
--
-- Convenção: os dados de processo são DERIVADOS da planilha e podem ser
-- reconstruídos rodando o sync de novo. O que não é reconstruível é a tabela
-- titulares (vínculo com a conta de login) e o histórico de mudanças.


-- ---------------------------------------------------------------------------
-- Funções utilitárias
-- ---------------------------------------------------------------------------

create or replace function public.tocar_atualizado_em()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

comment on function public.tocar_atualizado_em() is
  'Mantém a coluna atualizado_em em dia. Usada por gatilho BEFORE UPDATE.';


-- ---------------------------------------------------------------------------
-- processos
-- ---------------------------------------------------------------------------

create table public.processos (
  id              uuid        primary key default gen_random_uuid(),

  -- Carimbo de identidade escrito pelo script na coluna uid_royal da planilha.
  -- NÃO usar a coluna "ID" da planilha como chave: ela é posicional e já mudou
  -- de dono entre duas versões do arquivo (Fábio Ramos foi de ID 6 para 5, e o
  -- ID 4 passou de Patricia para Luciano em seis dias).
  uid_planilha    text        not null unique,

  modalidade      text        not null check (modalidade in ('avista','financiado')),
  imovel          text        not null,
  corretor        text,

  -- Marco zero das métricas de tempo. Veio da coluna "Data da Assinatura",
  -- adicionada na reestruturação de setembro/2026.
  data_assinatura date,

  -- Soft delete. Vira false quando o processo some da planilha. NUNCA apagar:
  -- sumir pode ser reestruturação, não cancelamento.
  ativo           boolean     not null default true,
  visto_em        timestamptz not null default now(),

  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),

  -- Alvo da chave estrangeira composta em processo_etapas (ver adiante).
  constraint processos_id_modalidade_key unique (id, modalidade)
);

create index processos_ativo_idx on public.processos (ativo) where ativo;

create trigger trg_processos_atualizado_em
  before update on public.processos
  for each row execute function public.tocar_atualizado_em();

comment on column public.processos.uid_planilha is
  'UUID gravado de volta na coluna uid_royal da planilha. Proteger a coluna contra edição manual.';


-- ---------------------------------------------------------------------------
-- titulares
-- ---------------------------------------------------------------------------
-- Relação muitos-para-muitos entre pessoa e processo. Seis dos quinze processos
-- têm duas pessoas (Davi/Jeane, Gisele/José, Mateus/Vivian, Fagner/Catia,
-- Carlos e Silvania, Felipe/Rebeca). Cada uma recebe o próprio magic link e vê
-- o mesmo acompanhamento.
--
-- Alimentada pela aba "Titulares" da planilha, NÃO por parsing do campo Cliente:
-- os separadores são inconsistentes ("/", " / ", "/ ", " e ") e uma linha mal
-- partida criaria um titular com acesso a processo alheio.

create table public.titulares (
  id          uuid        primary key default gen_random_uuid(),
  processo_id uuid        not null references public.processos(id) on delete cascade,
  nome        text        not null,

  -- É o login. Sempre em minúsculas: a comparação com auth.users.email depende
  -- disso, e o constraint abaixo impede que o script grave de outro jeito.
  email       text,
  auth_uid    uuid        references auth.users(id) on delete set null,

  criado_em   timestamptz not null default now(),

  constraint titulares_email_minusculo check (email is null or email = lower(email)),
  constraint titulares_processo_email_key unique (processo_id, email)
);

-- auth_uid é consultado por toda política de RLS: sem índice, cada leitura do
-- site faz varredura completa da tabela.
create index titulares_auth_uid_idx on public.titulares (auth_uid) where auth_uid is not null;
create index titulares_processo_idx on public.titulares (processo_id);
create index titulares_email_idx    on public.titulares (email)    where email is not null;


-- ---------------------------------------------------------------------------
-- etapas_catalogo
-- ---------------------------------------------------------------------------
-- 19 linhas fixas: 10 à vista + 9 financiado. Populado pela migração 200.

create table public.etapas_catalogo (
  id             serial primary key,
  modalidade     text   not null check (modalidade in ('avista','financiado')),
  ordem          int    not null check (ordem > 0),

  -- Slug estável, compartilhado entre modalidades quando a etapa é a mesma.
  -- É o que permite comparar as duas modalidades numa métrica só.
  --
  -- NUNCA trocar o código de uma etapa existente: quebra a continuidade do
  -- histórico. Renomear os rótulos é seguro; renomear o código não é.
  codigo         text   not null,

  -- Texto da planilha SEM o prefixo ordinal ("1° ", "2° ", ...).
  -- O prefixo fica de fora de propósito: a numeração já mudou uma vez (o fluxo
  -- financiado pulava do 8° para o 10° e virou 1..9 na reestruturação), então
  -- casar o cabeçalho por texto sem ordinal é mais robusto.
  rotulo_interno text   not null,

  -- O que o cliente lê. Existe para não expor nome de pessoa e jargão interno
  -- ("Amaurílio", "9° RGI") na tela do comprador.
  rotulo_publico text   not null,

  -- DEFERRABLE de propósito: reaplicar a migração 200 com as etapas em outra
  -- ordem violaria esta restrição no meio do INSERT. Adiada para o fim da
  -- transação, o statement inteiro roda antes da verificação.
  constraint etapas_modalidade_ordem_key  unique (modalidade, ordem)
                                          deferrable initially deferred,
  constraint etapas_modalidade_codigo_key unique (modalidade, codigo),
  constraint etapas_id_modalidade_key     unique (id, modalidade)
);


-- ---------------------------------------------------------------------------
-- processo_etapas (estado atual)
-- ---------------------------------------------------------------------------

create table public.processo_etapas (
  processo_id   uuid        not null,
  etapa_id      int         not null,

  -- Coluna redundante de propósito: junto com as duas chaves estrangeiras
  -- compostas abaixo, o banco passa a impedir que um processo financiado
  -- receba uma etapa do fluxo à vista. Sem isso, um bug no script corromperia
  -- os dados em silêncio.
  modalidade    text        not null check (modalidade in ('avista','financiado')),

  status        text        not null
                check (status in ('nao_iniciado','em_andamento','pendente',
                                  'concluido','atrasado','cancelado')),

  -- Quando entrou NESTE status. Base do indicador "parado há X dias".
  desde         timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),

  primary key (processo_id, etapa_id),

  constraint processo_etapas_processo_fk
    foreign key (processo_id, modalidade)
    references public.processos (id, modalidade) on delete cascade,

  constraint processo_etapas_etapa_fk
    foreign key (etapa_id, modalidade)
    references public.etapas_catalogo (id, modalidade)
);

create index processo_etapas_processo_idx on public.processo_etapas (processo_id);

create trigger trg_processo_etapas_atualizado_em
  before update on public.processo_etapas
  for each row execute function public.tocar_atualizado_em();


-- ---------------------------------------------------------------------------
-- processo_etapas_historico (append-only)
-- ---------------------------------------------------------------------------
-- O script só grava aqui QUANDO O STATUS MUDA. Gravar a cada sincronização
-- geraria cerca de 15 mil linhas por dia com 13 processos ativos, e estouraria
-- os 500 MB do plano free em poucos meses.

create table public.processo_etapas_historico (
  id          bigint generated always as identity primary key,
  processo_id uuid        not null references public.processos(id) on delete cascade,
  etapa_id    int         not null references public.etapas_catalogo(id),
  status_de   text,
  status_para text        not null
              check (status_para in ('nao_iniciado','em_andamento','pendente',
                                     'concluido','atrasado','cancelado')),
  em          timestamptz not null default now(),

  -- Permite excluir a carga inicial e correções manuais das métricas de tempo.
  origem      text        not null
              check (origem in ('sync','carga_inicial','correcao'))
);

create index processo_etapas_historico_idx
  on public.processo_etapas_historico (processo_id, etapa_id, em desc);


-- Append-only de verdade: o gatilho vale inclusive para a service_role, que
-- ignora RLS. Para uma limpeza excepcional:
--   alter table public.processo_etapas_historico
--     disable trigger trg_historico_append_only;
create or replace function public.bloquear_alteracao_historico()
returns trigger
language plpgsql
as $$
begin
  raise exception 'processo_etapas_historico é append-only: UPDATE e DELETE bloqueados. Para manutenção excepcional, desabilite o gatilho trg_historico_append_only.';
end;
$$;

create trigger trg_historico_append_only
  before update or delete on public.processo_etapas_historico
  for each row execute function public.bloquear_alteracao_historico();
