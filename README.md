# Royal Imóveis — site de status do cliente

Cada comprador acompanha o andamento da própria compra de imóvel, com login
por e-mail e sem senha. Os dados saem de uma planilha que o time da Royal
edita e chegam ao site por um banco Postgres.

- **Site:** https://royalstatuscliente.netlify.app
- **Arquitetura e decisões:** [documento](https://claude.ai/code/artifact/d31d4223-dc35-46af-9451-6568097db770)
- **Regras e armadilhas:** [`CLAUDE.md`](CLAUDE.md) — leia antes de mexer

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

Dois arquivos ficam de fora de propósito e precisam ser copiados à mão:

| Arquivo | Onde conseguir | Por que está fora |
| --- | --- | --- |
| `Planilha_Royal_Processo_Venda_Imoveis.xlsx` | com o time da Royal | dados de 15 compradores reais |
| `.env` | recriar a partir de `.env.example` | contém a `service_role` key |

Para o `.env`:

```bash
cp .env.example .env
```

Preencha com os valores de **Settings → API** no painel do Supabase:

- `SUPABASE_URL` — Project URL
- `SUPABASE_SERVICE_ROLE_KEY` — a chave **service_role**, não a `anon`

A `service_role` ignora RLS e GRANT. Ela vive só no `.env` e nos secrets do
GitHub Actions — nunca no navegador, nunca no Git.

### 3. Conferir que funciona

```bash
python sincronizar.py
```

Deve listar 15 processos e dizer que não há mudança. Se aparecer erro de
configuração, o `.env` está incompleto; se aparecer erro de planilha, o `.xlsx`
não está na pasta ou tem outro nome (confira `CAMINHO_PLANILHA` no `.env`).

### 4. Rodar o site localmente

```bash
python -m http.server 8765
```

Abra `http://localhost:8765/site/index.html`.

Para o login funcionar local, `http://localhost:8765/site/painel.html` precisa
estar em **Authentication → URL Configuration → Redirect URLs** no Supabase.

---

## Estrutura

```
site/                      o que vai ao ar no Netlify
  index.html               login por magic link
  painel.html              lista de negociações do cliente
  acompanhamento.html      andamento de um imóvel
  config.js                URL e chave anon (pública, pode versionar)
  assets/                  CSS e os módulos de cada página

sync/                      biblioteca do sincronizador
  fontes.py                de onde a planilha é lida (xlsx local / Excel Online)
  planilha.py              leitura e normalização
  banco.py                 acesso ao Supabase pela API REST

supabase/
  migrations/              schema, catálogo, RLS e permissões, em ordem
  tests/                   provas de integridade e isolamento (não são migrações)

carga_inicial.py           primeira carga da planilha para o banco
sincronizar.py             sincronização recorrente, com as guardas
provisionar_acessos.py     cria as contas de login dos titulares
gerar_titulares.py         monta a aba Titulares para o time preencher

royal-imoveis-acompanhamento.html   protótipo, referência de layout, não publicado
```

---

## Comandos

Todos simulam por padrão e só gravam com `--aplicar`.

| Comando | O que faz |
| --- | --- |
| `python sincronizar.py` | compara planilha e banco, grava só o que mudou |
| `python carga_inicial.py` | primeira carga; gera `uids_para_colar.txt` |
| `python provisionar_acessos.py` | cria contas de login a partir de `titulares` |
| `python gerar_titulares.py` | gera `titulares_para_colar.csv` |

Bandeiras úteis: `--forcar` no `sincronizar.py` ignora a guarda de sanidade,
depois de conferir o plano.

---

## Banco de dados

Migrações em `supabase/migrations/`, aplicadas em ordem numérica.

A rede da Royal bloqueia as portas 5432 e 6543, então `supabase db push` não
funciona de dentro do escritório. O caminho que funciona é colar cada arquivo
no **SQL Editor** do painel, que trafega por HTTPS. De outra rede, `db push`
deve funcionar normalmente.

Depois de qualquer mudança de schema, rode os arquivos de `supabase/tests/`.
Cada um cria e apaga os próprios dados e termina com um relatório
`PASSOU`/`FALHOU`.

---

## Publicação

O Netlify lê o `netlify.toml` e publica **apenas a pasta `site/`**. Migrações,
protótipo e scripts de sync ficam fora do ar — o que importa, porque o sync usa
a `service_role`.

Não preencha build command na interface do Netlify: isso sobrepõe o arquivo.

---

## O que falta

| | Depende de |
| --- | --- |
| Sincronização automática | registro de app no Azure AD com `Files.ReadWrite.All` |
| Divulgar o link | e-mails reais dos titulares (hoje são de teste) |
| Clientes reais | SMTP próprio; o padrão do Supabase limita envios por hora |
