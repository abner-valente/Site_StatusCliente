# Royal Imóveis — site de status do cliente

Site onde cada comprador acompanha o andamento da própria compra de imóvel.
Login por e-mail, sem senha. Os dados vêm de uma planilha que o time da Royal
edita, sincronizada para um banco Postgres.

**No ar:** https://royalstatuscliente.netlify.app
**Supabase:** projeto `royal-status-dev`, ref `hwskiimvcdrncmowxwvy`
**Arquitetura completa:** https://claude.ai/code/artifact/d31d4223-dc35-46af-9451-6568097db770

---

## Duas trilhas que só se encontram no navegador

```
Planilha ──► GitHub Actions (sincronizar.py) ──► Supabase
                                                    │  consulta autenticada,
                                                    │  filtrada por RLS
                                                    ▼
Repositório ──► Netlify (serve site/) ──────► Navegador do cliente
```

O Netlify entrega só HTML, CSS e JS. **Nenhum dado de cliente passa por ele.**
Foi assim que a falha do protótipo original foi corrigida: lá, os dados iam
embutidos no arquivo publicado e apareciam no código-fonte da página.

---

## Regras que não podem ser quebradas

Cada uma existe por um problema que já aconteceu neste projeto.

**1. A coluna `ID` da planilha não é chave.** É posicional. Entre duas versões
do arquivo, com seis dias de diferença, um cliente mudou de ID e outro ID
trocou de dono. A chave é `uid_royal`, carimbada pelo script.

**2. Coluna se localiza por texto de cabeçalho, nunca por posição.** A planilha
já foi reestruturada duas vezes; a numeração das etapas mudou junto. Por isso o
prefixo ordinal (`1° `, `10° `) é descartado antes de comparar.

**3. Histórico é gravado só quando o status MUDA.** Gravando a cada execução,
13 processos gerariam ~15 mil linhas por dia e estourariam os 500 MB do plano
free em poucos meses. Na mudança, o mesmo volume leva décadas.

**4. Nunca apagar processo.** Sumir da planilha pode ser reestruturação, não
cancelamento. Vira `ativo = false` com alerta.

**5. O código do catálogo (`etapas_catalogo.codigo`) nunca muda.** Renomear os
rótulos é seguro; trocar o código quebra a continuidade do histórico e das
métricas.

**6. A `service_role` key nunca vai para o navegador.** Ela ignora RLS e GRANT.
`site/assets/cliente.js` detecta e recusa, mas a regra vale antes disso.

**7. O front não filtra por titular.** Quem filtra é a RLS, no banco. Se o
filtro estivesse no JavaScript, um bug mostraria processo alheio.

---

## Armadilhas já pagas

**GRANT e RLS são camadas separadas.** Este projeto do Supabase não concede
`SELECT`/`INSERT`/`UPDATE`/`DELETE` por padrão a papel nenhum — só
`REFERENCES`, `TRIGGER` e `TRUNCATE`. Sem o grant, a política de RLS nem é
avaliada e o erro é `permission denied`, que aponta para o suspeito errado.
Tabela nova exige grant explícito nas migrações 400 e 500.

**`TRUNCATE` não dispara gatilho de linha.** O append-only do histórico era
`for each row` e passaria reto num truncate. Fechado na migração 600 com um
gatilho `for each statement` mais o revoke do privilégio.

**Conta precisa existir antes do primeiro login.** Cadastro público desligado
mais `shouldCreateUser: false` fecham a porta também para clientes legítimos.
`provisionar_acessos.py` cria as contas a partir de `titulares`. Sem isso a API
responde `422 otp_disabled` e nenhum e-mail sai — e a tela mostra sucesso
assim mesmo, de propósito, para não revelar quem é cliente.

**`openpyxl` descarta validação de dados ao salvar.** Por isso o script não
escreve na planilha local: destruiria as listas suspensas de status, e status
digitado livre quebra a normalização. Ele gera `uids_para_colar.txt` para
colagem manual. No Excel Online (fase 3) o Graph edita a célula sem reescrever
o arquivo e isso deixa de existir.

**A CSP tem a URL do Supabase fixa** em `netlify.toml`, em `connect-src`.
Trocar de projeto exige mudar lá junto com `site/config.js`. Esquecer publica
um site que carrega bonito e falha em toda consulta.

---

## Comandos

```bash
python carga_inicial.py            # simula; --aplicar grava
python sincronizar.py              # simula; --aplicar grava, --forcar ignora a guarda
python provisionar_acessos.py      # simula; --aplicar cria contas
python gerar_titulares.py          # gera a aba Titulares para preencher
```

Todos simulam por padrão. Nenhum grava sem `--aplicar`.

**Migrações** ficam em `supabase/migrations/`, aplicadas em ordem numérica.
A rede da Royal bloqueia as portas 5432 e 6543, então `supabase db push` não
funciona de lá — o caminho é colar no SQL Editor do painel, que usa HTTPS.

**Testes** em `supabase/tests/` não são migrações. Rodar após mudança de schema;
cada um cria e apaga os próprios dados.

---

## Estado

| Fase | |
| --- | --- |
| 0 — banco e carga | pronta |
| 1 — identidade | acesso provisionado, **e-mails ainda são de teste** |
| 2 — site | no ar |
| 3 — sync automático | lógica pronta e testada, **bloqueada no Azure AD** |

Bloqueios reais: registro de app no Azure com `Files.ReadWrite.All` e
consentimento de admin; e-mails reais dos titulares; SMTP próprio, porque o
padrão do Supabase tem limite baixo por hora.

O cron do GitHub Actions está comentado de propósito: ligar antes do Excel
Online criaria uma falha a cada 15 minutos e treinaria todo mundo a ignorar a
notificação — justamente o aviso que precisa funcionar quando o secret do
Azure expirar.

---

## Não está no repositório

- **A planilha `.xlsx`** — tem dados de 15 compradores reais
- **`.env`** — tem a `service_role` key
- `uids_para_colar.txt`, `titulares_para_colar.csv`

O histórico do Git é permanente: um dado commitado não sai apagando depois.

`site/config.js` **está** versionado e isso é correto — ele só tem a chave
`anon`, que é pública por natureza e vai para o navegador de todo visitante.
