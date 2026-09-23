-- Royal Imóveis — Site de status do cliente
-- Migração 3 de 3: isolamento por cliente (RLS) e vínculo com o login.
--
-- O público do site é o cliente final, e só ele. A regra "cada um vê só o seu"
-- mora aqui, no banco — não no código do site. Um erro no front não consegue
-- contorná-la, porque a consulta já chega filtrada.
--
-- O script de sincronização usa a service_role, que ignora RLS por definição.
-- Nunca expor a service_role key no navegador.


-- ---------------------------------------------------------------------------
-- Função de apoio
-- ---------------------------------------------------------------------------
-- Existe para evitar recursão infinita: uma política em `titulares` que
-- consultasse a própria `titulares` faria o Postgres abortar com
-- "infinite recursion detected in policy for relation titulares".
--
-- SECURITY DEFINER faz a função rodar ignorando RLS, então a consulta interna
-- não dispara política nenhuma. Ela só devolve os processos de quem chamou,
-- portanto é segura de expor.

create or replace function public.processos_do_titular()
returns setof uuid
language sql
security definer
set search_path = public
stable
as $$
  select processo_id
    from public.titulares
   where auth_uid = (select auth.uid());
$$;

comment on function public.processos_do_titular() is
  'Processos do usuário autenticado. Base de todas as políticas de RLS.';


-- ---------------------------------------------------------------------------
-- Ligar titular à conta de login
-- ---------------------------------------------------------------------------
-- O e-mail da aba "Titulares" é o que amarra a pessoa ao processo. O vínculo
-- pode acontecer em duas ordens diferentes, e as duas precisam funcionar:
--
--   1. titular já cadastrado, usuário faz o primeiro login  -> gatilho abaixo
--   2. usuário já existe, e-mail entra na planilha depois   -> função de backfill
--
-- O sync deve chamar public.vincular_titulares_pendentes() ao final de cada
-- execução para cobrir o caso 2.

create or replace function public.vincular_titular_novo_usuario()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.titulares
     set auth_uid = new.id
   where email = lower(new.email)
     and auth_uid is null;
  return new;
end;
$$;

-- Observação de manutenção: criar gatilho em auth.users exige privilégio de
-- owner. Pelo Supabase CLI a migração roda como `postgres` e funciona. Se for
-- aplicar pelo SQL Editor com um papel restrito, este bloco pode falhar —
-- nesse caso rode-o separadamente como owner.
drop trigger if exists trg_vincular_titular on auth.users;
create trigger trg_vincular_titular
  after insert on auth.users
  for each row execute function public.vincular_titular_novo_usuario();


create or replace function public.vincular_titulares_pendentes()
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  n int;
begin
  with ligados as (
    update public.titulares t
       set auth_uid = u.id
      from auth.users u
     where t.auth_uid is null
       and t.email is not null
       and t.email = lower(u.email)
    returning 1
  )
  select count(*) into n from ligados;

  return n;
end;
$$;

comment on function public.vincular_titulares_pendentes() is
  'Liga titulares sem auth_uid a contas já existentes. Chamar ao fim de cada sync.';

-- Backfill só faz sentido pelo processo de sync, nunca pelo navegador.
revoke execute on function public.vincular_titulares_pendentes() from anon, authenticated;


-- ---------------------------------------------------------------------------
-- Ligar RLS
-- ---------------------------------------------------------------------------

alter table public.processos                 enable row level security;
alter table public.titulares                 enable row level security;
alter table public.etapas_catalogo           enable row level security;
alter table public.processo_etapas           enable row level security;
alter table public.processo_etapas_historico enable row level security;

-- Visitante não autenticado não lê nada. Com RLS ligada e nenhuma política
-- para `anon` isso já valeria, mas o revoke deixa a intenção explícita.
revoke all on public.processos                 from anon;
revoke all on public.titulares                 from anon;
revoke all on public.etapas_catalogo           from anon;
revoke all on public.processo_etapas           from anon;
revoke all on public.processo_etapas_historico from anon;


-- ---------------------------------------------------------------------------
-- Políticas — apenas leitura, apenas para quem está autenticado
-- ---------------------------------------------------------------------------
-- Não existe política de INSERT, UPDATE ou DELETE de propósito: o cliente só lê.
-- Toda escrita vem do sync, pela service_role.

create policy "titular lê o próprio processo"
  on public.processos for select to authenticated
  using (id in (select * from public.processos_do_titular()));

-- Processo inativo continua visível: ele pode ter sumido da planilha por
-- reestruturação, e tirar a página do cliente do ar sem aviso é pior do que
-- mostrar um estado antigo. Quem decide o que exibir é a interface.

create policy "titular lê os titulares do próprio processo"
  on public.titulares for select to authenticated
  using (processo_id in (select * from public.processos_do_titular()));

create policy "catálogo de etapas é legível por quem está logado"
  on public.etapas_catalogo for select to authenticated
  using (true);

create policy "titular lê as etapas do próprio processo"
  on public.processo_etapas for select to authenticated
  using (processo_id in (select * from public.processos_do_titular()));

create policy "titular lê o histórico do próprio processo"
  on public.processo_etapas_historico for select to authenticated
  using (processo_id in (select * from public.processos_do_titular()));


-- ---------------------------------------------------------------------------
-- Teste obrigatório antes do lançamento
-- ---------------------------------------------------------------------------
-- Configuração errada de RLS é a falha mais comum desta arquitetura, e ela não
-- aparece na interface — só na API. Antes de liberar para clientes:
--
--   1. Logar como o titular do processo A.
--   2. Consultar a API pedindo explicitamente o id do processo B.
--   3. O resultado precisa ser zero linhas, não erro de permissão.
--
-- Fazer o mesmo para processo_etapas e para o histórico.
--
-- Lembrete: desativar o cadastro público no Supabase Auth (Authentication ->
-- Providers -> Email -> "Allow new users to sign up" desligado). Com ele ligado,
-- qualquer e-mail cria conta; a RLS não deixa ver nada, mas a pessoa entra no
-- sistema e consegue sondar quais e-mails existem.
