# Royal Imóveis — site de status do cliente

Cada comprador acompanha o andamento da própria compra de imóvel, com login
por e-mail e sem senha. Os dados saem de uma planilha que o time da Royal
edita e chegam ao site por um banco Postgres.

- **Site:** https://royalstatuscliente.netlify.app
- **Arquitetura e decisões:** [documento](https://claude.ai/code/artifact/d31d4223-dc35-46af-9451-6568097db770)
- **Regras e armadilhas:** [`CLAUDE.md`](CLAUDE.md) — leia antes de mexer
- **Cadastrar cliente (para o time da Royal):** [`docs/cadastrar-cliente-planilha.txt`](docs/cadastrar-cliente-planilha.txt)
- **Montar o e-mail em cliente novo:** [`docs/configurar-email-resend.md`](docs/configurar-email-resend.md)

---

## Instalar em outra máquina

### 1. Clonar e preparar o Python

```bash
git clone https://github.com/abner-valente/Site_StatusCliente.git
cd Site_StatusCliente
python -m venv .venv
```

```bash
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux e macOS
```

```bash
pip install -r requirements.txt
```

### 2. Trazer o que não está no repositório

Estes arquivos ficam de fora de propósito e precisam ser copiados à mão:

| Arquivo | Onde conseguir | Por que está fora |
| --- | --- | --- |
| `.env` | recriar a partir de `.env.example` | tem a `service_role` key |
| `credenciais-google.json` | Google Cloud Console | dá acesso de escrita à planilha |
| `Planilha_..._Imoveis.xlsx` | com o time da Royal | dados de 15 compradores reais |

A planilha `.xlsx` serve apenas à fonte de desenvolvimento
(`FONTE_PLANILHA=xlsx_local`). **Em produção a fonte é o Google Sheets** e nada
precisa estar no disco além das credenciais.

Para o `.env`:

```bash
cp .env.example .env
```

| Variável | Onde pegar |
| --- | --- |
| `SUPABASE_URL` | painel do Supabase, Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | mesma tela, chave **service_role** (não a `anon`) |
| `FONTE_PLANILHA` | `google_sheets` em produção, `xlsx_local` para testar offline |
| `GOOGLE_SHEET_ID` | o trecho da URL da planilha entre `/d/` e `/edit` |
| `GOOGLE_CREDENTIALS_FILE` | caminho do `.json` da service account |

A `service_role` ignora RLS e GRANT. Ela vive só no `.env` e nos secrets do
GitHub Actions — nunca no navegador, nunca no Git.

A service account precisa ter a planilha **compartilhada com ela como editora**
(o e-mail dela está dentro do `.json`, no campo `client_email`). Sem isso a
leitura funciona e o carimbo do uid falha.

### 3. Conferir que funciona

```bash
python sincronizar.py
```

Deve listar 15 processos e dizer que não há mudança. Nada é gravado.

### 4. Rodar o site localmente

```bash
python -m http.server 8765
```

Abra `http://localhost:8765/site/index.html`.

Para o login funcionar local, `http://localhost:8765/site/painel.html` precisa
estar em **Authentication → URL Configuration → Redirect URLs** no Supabase.

---

## Comandos

Resumo e, abaixo, o detalhe de cada um.

| Comando | Quando usar |
| --- | --- |
| `python sincronizar.py` | o do dia a dia: conferir o que mudou na planilha |
| `python sincronizar.py --aplicar` | gravar essa mudança no banco |
| `python provisionar_acessos.py` | descobrir quem está sem conta de login |
| `python gerar_titulares.py` | montar a aba `Titulares` em planilha nova |
| `python carga_inicial.py` | só na primeira carga de um projeto novo |
| `python -m http.server 8765` | abrir o site na própria máquina |

**Nenhum script grava sem `--aplicar`.** Rodar sem a flag é sempre seguro: ele
lê, compara e imprime o plano. É o jeito de conferir antes de decidir.

---

### `sincronizar.py` — o comando do dia a dia

```bash
python sincronizar.py              # simula: imprime o plano, não grava
python sincronizar.py --aplicar    # grava o plano
```

Compara a planilha com o banco e acerta a diferença: muda status, cria
processo novo, cria e revoga titular, e **cria a conta de login** de quem
entrou. É o mesmo comando que o GitHub Actions roda todo dia às 19h.

O que ele imprime:

```
fonte    : Google Sheets (1sD4eS...dYrA)
planilha : 15 processo(s)
banco    : 15 processo(s), 15 ativo(s)

Nenhuma mudança de status.
```

Flags:

| Flag | Para que serve |
| --- | --- |
| `--aplicar` | sai da simulação e grava |
| `--forcar` | ignora a guarda de sanidade, **depois** de conferir o plano |
| `--sem-provisionar` | não cria as contas de login ao final |

Códigos de saída:

| | |
| --- | --- |
| `0` | tudo bem |
| `1` | erro de configuração, de rede ou de planilha |
| `2` | **a guarda de sanidade barrou** — nada foi gravado |
| `3` | gravou o que podia, mas há **linha pendente** na aba `Titulares` |

A diferença entre 2 e 3 decide o que fazer. No `2` o banco está intacto e
alguém precisa autorizar a mudança. No `3` o sync funcionou; alguém ficou sem
acesso por célula malpreenchida, e quem resolve é o técnico da Royal, na
planilha — o recado de cada linha já está lá, na coluna `Obs. Script`.

A guarda barra quando a mudança é grande demais para ser rotina: muito status
mudando de uma vez, processo que sumiu da planilha, uid que o banco não
conhece, ou vários acessos sendo revogados juntos. Quase sempre é planilha
reestruturada ou aba errada. Se a mudança for legítima mesmo, `--forcar`.

**Por que simula por padrão:** o sync revoga acesso e grava histórico, duas
coisas que dão trabalho para desfazer. A simulação é a chance de ver a lista
antes.

**O sync conversa de volta pela coluna `Obs. Script`**, na aba `Titulares`.
Quando acha problema numa linha — e-mail com caractere estranho, imóvel que não
casa com processo nenhum, imóvel repetido em dois — escreve ali o que fazer, em
uma frase, e apaga quando o problema sai. É mão única: ninguém digita nessa
coluna.

O fundo é pintado por gravidade: **âmbar** quando o cliente entra e só a célula
está ruim, **vermelho claro** quando ele não entra, branco quando limpa.

Existe porque o técnico da Royal não lê log do GitHub Actions, mas abre a
planilha todo dia. A coluna é opcional; sem ela o aviso fica só no log, e o
sync avisa que ela falta.

---

### `provisionar_acessos.py` — auditar o acesso

```bash
python provisionar_acessos.py              # lista quem está sem conta
python provisionar_acessos.py --aplicar    # cria as contas que faltam
```

O `sincronizar.py --aplicar` já faz isso ao final. Este script existe para
duas situações: **auditar** sem mexer em mais nada, e consertar o caso de o
sync ter rodado com `--sem-provisionar`.

Serve de primeira parada quando um cliente diz que **o link de acesso não
chega.** Sem conta, a API do Supabase responde `422 otp_disabled` e nenhum
e-mail sai — e a tela do cliente mostra sucesso assim mesmo, de propósito,
para não revelar quem é cliente da Royal.

---

### `gerar_titulares.py` — montar a aba Titulares

```bash
python gerar_titulares.py
```

Lê os processos da planilha e escreve `titulares_para_colar.csv` com a coluna
`email` **vazia**, para o time preencher. Separa casais ("Davi / Jeane" vira
duas linhas) e deixa o texto original ao lado, em `cliente_planilha`, para
quem preenche conferir.

Não grava no banco nem na planilha. Processo que já tem titular fica de fora,
então dá para rodar de novo quando entrarem processos novos.

Útil em planilha nova. No dia a dia, cliente novo entra pela planilha direto —
ver [`docs/cadastrar-cliente-planilha.txt`](docs/cadastrar-cliente-planilha.txt).

---

### `carga_inicial.py` — primeira carga

```bash
python carga_inicial.py              # simula
python carga_inicial.py --aplicar    # grava e gera uids_para_colar.txt
```

Só para o que o nome diz: a primeira carga de uma planilha nova em projeto
novo. **No dia a dia quem cria processo é o `sincronizar.py`** — rodar a carga
inicial num banco que já tem dados é pedir duplicata.

Com a fonte `xlsx_local` ele não carimba o uid na planilha (`openpyxl`
destruiria as listas suspensas de status); os uids saem em
`uids_para_colar.txt` para colagem manual. Com o Google Sheets o carimbo é
automático.

---

### Rodar o site localmente

```bash
python -m http.server 8765
```

`http://localhost:8765/site/index.html`. Serve a pasta como está — não há build.

---

### Sincronização automática

Roda sozinha todo dia às **19:00 de Brasília** pelo GitHub Actions
([`.github/workflows/sincronizar.yml`](.github/workflows/sincronizar.yml)),
sempre com `--aplicar`.

Para rodar fora de hora, sem terminal: **Actions → Sincronizar planilha → Run
workflow**, marcando `aplicar`. Desmarcado, ele só simula.

O workflow precisa de dois secrets em Settings → Secrets and variables →
Actions: `ENV` com o mesmo conteúdo do `.env`, e `GOOGLE_CREDENTIALS_JSON` com
a chave da service account.

**Armadilha:** o GitHub desativa workflow agendado após 60 dias sem commit no
repositório. Este projeto pode ficar meses parado — e aí o sync para sozinho,
sem erro em lugar nenhum; o sintoma é o site envelhecendo. O GitHub avisa o
dono por e-mail. Qualquer commit reativa.

---

### Git

```bash
git status
git add -A
git commit -m "mensagem"
git push
```

Antes de commitar, confira que `.env`, `credenciais*.json`, o `.xlsx` e os
arquivos `*_para_colar.*` não entraram. O `.gitignore` cobre todos, mas
**histórico do Git é permanente** — dado commitado não sai apagando depois.

---

## Banco de dados

Migrações em `supabase/migrations/`, aplicadas em ordem numérica.

A rede da Royal bloqueia as portas 5432 e 6543, então `supabase db push` não
funciona de dentro do escritório. O caminho que funciona é colar cada arquivo
no **SQL Editor** do painel, que trafega por HTTPS. De outra rede, `db push`
deve funcionar normalmente.

Depois de qualquer mudança de schema, rode os arquivos de `supabase/tests/` —
também pelo SQL Editor. Cada um cria e apaga os próprios dados e termina com
um relatório `PASSOU`/`FALHOU`. Eles **não são migrações**; não entram na
ordem numérica.

Tabela nova exige grant explícito nas migrações 400 e 500. Sem o grant, a
política de RLS nem é avaliada e o erro é `permission denied`, que aponta para
o suspeito errado.

---

## Publicação

O Netlify lê o `netlify.toml` e publica **apenas a pasta `site/`**. Migrações,
protótipo e scripts de sync ficam fora do ar — o que importa, porque o sync usa
a `service_role`.

Não preencha build command na interface do Netlify: isso sobrepõe o arquivo.

Trocar de projeto do Supabase exige mudar a URL em **dois** lugares:
`site/config.js` e o `connect-src` da CSP em `netlify.toml`. Esquecer o segundo
publica um site que carrega bonito e falha em toda consulta.

---

## Estrutura

```
site/                      o que vai ao ar no Netlify
  index.html               login por magic link
  painel.html              lista de negociações do cliente
  acompanhamento.html      andamento de um imóvel
  config.js                URL e chave anon (pública, pode versionar)
  assets/                  CSS, módulos de cada página e o logo

sync/                      biblioteca do sincronizador
  fontes.py                de onde a planilha é lida (Google Sheets / xlsx local)
  planilha.py              leitura e normalização
  banco.py                 acesso ao Supabase pela API REST
  acessos.py               criação das contas de login

supabase/
  migrations/              schema, catálogo, RLS e permissões, em ordem
  tests/                   provas de integridade e isolamento (não são migrações)

.github/workflows/         o cron diário da sincronização
docs/                      runbooks: e-mail no Resend, cadastro pelo time

carga_inicial.py           primeira carga da planilha para o banco
sincronizar.py             sincronização recorrente, com as guardas
provisionar_acessos.py     cria as contas de login dos titulares
gerar_titulares.py         monta a aba Titulares para o time preencher

royal-imoveis-acompanhamento.html   protótipo, referência de layout, não publicado
```

---

## O que falta

| | Depende de |
| --- | --- |
| Divulgar o link aos clientes | **e-mails reais dos titulares** (hoje são de teste) |
| Domínio próprio no site | apontar `processosroyal.com.br` para o Netlify (opcional) |

O resto está no ar: banco, site, e-mail por SMTP próprio no Resend e
sincronização automática diária.
