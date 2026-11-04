-- ---------------------------------------------------------------------------
-- 700 — papel do titular: cliente, corretor, vendedor
-- ---------------------------------------------------------------------------
-- Antes desta migração, `titulares` significava "comprador". Na prática ela
-- sempre foi uma tabela genérica de "quem pode ver este processo" — e
-- `processos_do_titular()` nunca soube de papel nenhum. Por isso corretor e
-- vendedor entram como LINHAS, não como tabelas novas: a RLS, que é o único
-- lugar onde um bug mostra dado de outra pessoa, fica intocada.
--
-- Quatro das cinco políticas não mudam uma vírgula. Só a de quem-vê-quem.
--
-- Decisão do cliente em 04/11/2026: corretor e vendedor veem a MESMA tela do
-- comprador, inteira. O recorte é de acesso ao processo, não de conteúdo.
-- ---------------------------------------------------------------------------


-- ---------------------------------------------------------------------------
-- A coluna
-- ---------------------------------------------------------------------------
-- `default 'cliente'` é o que faz as linhas que já existem continuarem
-- valendo sem ninguém tocar nelas. Vale também para a planilha: enquanto a
-- coluna `papel` não existir na aba Titulares, o sync lê tudo como cliente e
-- roda igual a antes.

alter table public.titulares
  add column if not exists papel text not null default 'cliente';

alter table public.titulares drop constraint if exists titulares_papel_valido;
alter table public.titulares add  constraint titulares_papel_valido
  check (papel in ('cliente', 'corretor', 'vendedor'));

comment on column public.titulares.papel is
  'cliente, corretor ou vendedor. Quem manda é a aba Titulares da planilha.';


-- ---------------------------------------------------------------------------
-- A chave
-- ---------------------------------------------------------------------------
-- `(processo_id, email)` quebraria no corretor que compra pela própria Royal:
-- ele é corretor e cliente do mesmo processo, duas linhas, mesmo e-mail.
-- Com o papel na chave as duas convivem, e a duplicata de verdade — mesma
-- pessoa, mesmo papel, mesmo processo — continua barrada.

alter table public.titulares
  drop constraint if exists titulares_processo_email_key;

alter table public.titulares
  drop constraint if exists titulares_processo_email_papel_key;

alter table public.titulares add constraint titulares_processo_email_papel_key
  unique (processo_id, email, papel);


-- ---------------------------------------------------------------------------
-- Quem vê quem
-- ---------------------------------------------------------------------------
-- Mesma armadilha da migração 300: uma política em `titulares` que consulte
-- `titulares` aborta com "infinite recursion detected in policy for relation
-- titulares". SECURITY DEFINER roda ignorando RLS, então a consulta interna
-- não dispara política nenhuma.
--
-- Só devolve as linhas de quem chamou, portanto é segura de expor.

create or replace function public.meus_papeis()
returns table (processo_id uuid, papel text)
language sql
security definer
set search_path = public
stable
as $$
  select processo_id, papel
    from public.titulares
   where auth_uid = (select auth.uid());
$$;

comment on function public.meus_papeis() is
  'Pares (processo, papel) do usuário autenticado. Base da política de quem-vê-quem.';

-- GRANT e RLS são camadas separadas neste projeto: sem o grant a política nem
-- é avaliada e o erro é `permission denied`, que aponta para o suspeito
-- errado. Mesmo tratamento dado a processos_do_titular() na migração 400.
grant execute on function public.meus_papeis() to authenticated;

-- A política antiga mostrava TODOS os titulares do processo a qualquer um
-- deles. Com três papéis na mesma tabela, isso passaria o e-mail do comprador
-- ao vendedor e vice-versa — gente que negocia entre si e não precisa trocar
-- endereço por aqui.
--
-- A nova mostra só quem divide o MESMO papel no mesmo processo. Casal
-- comprador continua se vendo, que é o caso para o qual a política nasceu.
--
-- O cliente não perde nada: o nome do corretor já está em `processos.corretor`,
-- que ele lê pela política "titular lê o próprio processo".

drop policy if exists "titular lê os titulares do próprio processo" on public.titulares;
drop policy if exists "titular lê titulares do mesmo papel" on public.titulares;

create policy "titular lê titulares do mesmo papel"
  on public.titulares for select to authenticated
  using ((processo_id, papel) in (select * from public.meus_papeis()));


-- ---------------------------------------------------------------------------
-- Conferência
-- ---------------------------------------------------------------------------
-- Falha ao aplicar é melhor do que descobrir depois que a política não existe
-- e a tabela está aberta — ou fechada — sem ninguém saber.

do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'titulares'
       and column_name = 'papel'
  ) then
    raise exception 'coluna titulares.papel não foi criada';
  end if;

  if not exists (
    select 1 from pg_constraint
     where conname = 'titulares_processo_email_papel_key'
  ) then
    raise exception 'chave única (processo, email, papel) não foi criada';
  end if;

  if not exists (
    select 1 from pg_policies
     where schemaname = 'public' and tablename = 'titulares'
       and policyname = 'titular lê titulares do mesmo papel'
  ) then
    raise exception 'política de quem-vê-quem não foi criada';
  end if;

  if not has_function_privilege('authenticated', 'public.meus_papeis()', 'execute') then
    raise exception 'authenticated não pode executar meus_papeis() — a política não será avaliada';
  end if;

  raise notice 'Migração 700 aplicada: papel, chave e política conferidos.';
end $$;


-- Quantos titulares por papel, para olhar depois do primeiro sync.
select papel, count(*) as titulares, count(auth_uid) as com_conta
  from public.titulares
 group by papel
 order by papel;
