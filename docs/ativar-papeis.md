# Ativar corretor e vendedor

Roteiro de implantação dos papéis. Cada passo é reversível, e nada quebra
enquanto a planilha não estiver pronta.

**Decisão do cliente em 04/11/2026:** corretor e vendedor veem a mesma tela do
comprador, inteira. O recorte é de acesso ao processo, não de conteúdo.

---

## A ordem importa

```
1. migração        →  2. código       →  3. planilha      →  4. sync
   (SQL Editor)       (já commitado)     (o técnico)         (você)
```

**Migração primeiro.** O código já pede a coluna `papel` ao banco; rodar o
sync antes de aplicar a migração falha na hora, dizendo que a coluna não
existe.

**Planilha por último, e sem pressa.** A coluna `papel` é opcional: enquanto
ela não existir, toda linha é lida como `cliente` e o sync roda exatamente
como antes. Processo sem linha de vendedor simplesmente não tem acesso de
vendedor, e a rodada do dia seguinte pega o que o técnico preencheu.

---

## 1. Aplicar a migração

Painel do Supabase → **SQL Editor** → colar inteiro e executar:

```
supabase/migrations/20260923000700_papel_do_titular.sql
```

`supabase db push` não funciona da rede da Royal — as portas 5432 e 6543 estão
bloqueadas. O SQL Editor passa por HTTPS.

O arquivo termina conferindo o próprio trabalho. Se a coluna, a chave, a
política ou o `grant` não estiverem no lugar, ele **levanta erro** em vez de
deixar passar. Ao final mostra a contagem de titulares por papel — devem estar
todos como `cliente`.

## 2. Rodar o teste

Mesmo SQL Editor:

```
supabase/tests/05_rls_papeis.sql
```

Dez linhas, todas `PASSOU`. Ele cria dois processos de teste, quatro contas,
confere quem vê o quê e apaga tudo. O item 10 prova que não sobrou nada.

Os testes não são migrações e não entram na ordem numérica.

**Rode também o `02_rls_isolamento.sql`.** A migração 700 trocou a política de
quem-vê-quem; o 02 é o teste que prova que o processo A não enxerga o processo
B, e precisa continuar passando.

## 3. Criar a coluna `papel` na planilha

Na aba `Titulares`, **insira uma coluna à esquerda de `Obs. Script`** e
escreva no cabeçalho:

```
papel
```

A posição importa porque colar é posicional, e o arquivo do passo 4 foi gerado
nessa ordem:

```
uid_processo | nome | email | imovel | cliente_planilha | papel | Obs. Script
```

`Obs. Script` fica sendo a última de propósito: é a coluna de mão única, onde
só o sync escreve.

As 32 linhas que já existem ficam com `papel` vazio, e vazio conta como
comprador. Nenhuma precisa ser editada.

## 4. Colar as linhas novas

Abra `papeis_para_colar.csv` e cole as 38 linhas abaixo da última linha
existente da aba.

| papel | linhas | o que vem preenchido |
| --- | --- | --- |
| `vendedor` | 16 | e-mail pronto, `nome` em branco |
| `corretor` | 22 | `nome` pronto, **e-mail em branco** |

O `uid_processo` já vem resolvido em todas. Isso não é detalhe: a lista que o
gerente passou trazia os imóveis abreviados (`Jacarepa Residentes`,
`Garden Up 1 108`) e **nenhum dos dez casava** com o nome da planilha. Colados
como estavam, nenhum vendedor entraria.

`nome` em branco não é problema: o sistema usa o e-mail como nome quando a
célula está vazia.

Linha com e-mail em branco é **ignorada** pelo sync. As 22 de corretor não
criam acesso nenhum até alguém preencher o endereço — são uma lista de tarefa
no lugar certo.

## 5. Preencher os e-mails dos corretores

São 10 pessoas em 22 linhas, então o mesmo endereço se repete.

**Teste com um corretor antes dos dez.** Eles usam caixa corporativa
(`@royalimoveisrj.com.br`), hospedada na inGaia, e filtro corporativo é mais
rígido que Gmail. Link de acesso que cai em quarentena é indistinguível de
login quebrado: o corretor diz "não funciona" e não há erro em lugar nenhum
para investigar. Com um de cada vez, isso aparece numa pessoa, não em dez.

Enviar para lá não encosta no DNS da Royal — nós mandamos *de*
`processosroyal.com.br`, com DKIM e SPF passando. Receber é problema do
servidor deles.

Uma linha pede atenção: um processo tem `Thiago/Nilton` na coluna `Corretor`
da aba de fluxo. Se forem duas pessoas, viram **duas linhas** de corretor,
uma para cada e-mail.

## 6. Sincronizar

```bash
python sincronizar.py
```

Simula e mostra o plano. Confira a lista `ACESSOS A CRIAR` — agora ela mostra
o papel de cada um.

```bash
python sincronizar.py --aplicar
```

Grava e cria as contas de login que faltarem. Não precisa rodar
`provisionar_acessos.py` à parte.

A guarda de mudança em massa **não conta inserção** — ela olha revogação e
mudança de status. As 38 linhas novas não serão barradas.

---

## O que fica faltando

**12 processos sem vendedor.** A lista do gerente cobriu 10 dos 22. Os que
faltam:

```
Bourgogne Bl 2 511            Laercio
Bourgogne Bl 2 710            Davi e Jeane
Freedom Bl 6 303              Angela
Maxxii Sala 415               Luciano
Caribe I Bl 2 102             Fábio Ramos
Florianopolis 1450 Bl 2 403   Renata
Free Residencial Bl 2 308     Gisele e José
Boa Nova Bl 2 107             Daniel
Full Comfort Apto 201         Mateus e Vivian
Village Livorno Apto 403      Fagner e Catia
Escuna Bl 3 102               Tais
Life 360 Bl 2 704             Denilson e Sandra
```

Conforme forem levantados, são linhas novas na aba `Titulares` com
`papel = vendedor`. Nenhum código a mais.

---

## Desfazer

**Antes do passo 6**, nada foi para o banco: apagar as linhas coladas na
planilha basta.

**Depois**, para remover o acesso de corretor e vendedor sem desfazer a
migração: apague as linhas de papel `corretor` e `vendedor` da aba
`Titulares`, rode o sync e confira a lista `ACESSOS A REVOGAR`. Revogação em
massa bate na guarda e exige `--forcar`, que é a fricção certa para tirar o
acesso de muita gente de uma vez.

Revogar apaga a linha de `titulares`, não a conta no Auth. Conta órfã é
inofensiva — sem titular a RLS não mostra nada —, mas aparece na lista de
usuários do painel.

Para voltar o schema ao estado anterior, a migração é reversível na mão:
restaurar a chave `(processo_id, email)`, recriar a política
`"titular lê os titulares do próprio processo"` e derrubar a coluna `papel`.
Nessa ordem, e lembrando de devolver o `on_conflict` de
`banco.gravar_titulares` para `processo_id,email` — a tupla é escrita à mão e
não acompanha o banco sozinha.
