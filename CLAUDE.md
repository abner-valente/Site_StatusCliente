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

**8. A planilha manda, inclusive sobre quem tem acesso.** Editar a tabela
`titulares` direto no banco não resolve nada: o próximo sync apaga o que não
estiver na aba `Titulares`. Trocar o e-mail de um cliente é **editar a planilha
e rodar o sync** — nunca o contrário. Mexer só no banco gera uma hora de
confusão, porque funciona até a sincronização seguinte.

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
Sem conta, a API responde `422 otp_disabled` e nenhum e-mail sai — e a tela
mostra sucesso assim mesmo, de propósito, para não revelar quem é cliente.

Como esse passo falhava em silêncio quando esquecido, ele deixou de ser manual:
`sincronizar.py` provisiona ao final de cada execução. `provisionar_acessos.py`
continua existindo para auditar quem está sem acesso e para o caso de o sync
ter rodado com `--sem-provisionar`.

**`openpyxl` descarta validação de dados ao salvar.** Vale só para a fonte
`xlsx_local`, de desenvolvimento: salvar por ali destruiria as listas suspensas
de status, e status digitado livre quebra a normalização. Com essa fonte o
carimbo do uid sai por `uids_para_colar.txt`, para colagem manual.

No Google Sheets isso não existe — a API altera a célula sem reescrever o
arquivo, e o carimbo é automático.

**Data do Sheets é lida sem formatação, de propósito.** Com formatação,
`01/06/2026` vira 1 de junho ou 6 de janeiro conforme o locale da planilha, e
alguém mexer nesse ajuste inverteria todas as datas em silêncio. Sem
formatação vem o número de série, que não depende de idioma.
`planilha.normalizar_data` converte, aceita ISO e dd/mm/aaaa como alternativas,
e **levanta erro** no que não reconhecer — data errada vira "há X dias" errado
na tela do cliente.

**E-mail colado do Word ou de PDF pode trazer ligadura tipográfica.** No
primeiro dia em produção, um endereço na aba `Titulares` veio com `ﬂ`
(U+FB02, um caractere único) em vez das letras `f` e `l`:
`re.ﬂacardoso@gmail.com`. O Gmail não conhece esse endereço — o link de acesso
nunca chegaria, e nada na tela do cliente diria por quê.

Pior, o sync quebrava ao **imprimir** a lista, antes da guarda, porque o
terminal do Windows é cp1252. O erro falava de codec e apontava para o
suspeito errado. `sync/__init__.py` agora força UTF-8 na saída, então o script
mostra o problema em vez de morrer.

Isso não dá erro de validação: é um e-mail sintaticamente válido.

`planilha.normalizar_email` agora trata a entrada: **NFKC antes de minúsculas**
— é o NFKC que desfaz a ligadura e o caractere de largura total; minúsculo não
faz nada por eles, porque `ﬂ` já é minúscula. Invisíveis (zero width, soft
hyphen) são removidos.

O que não é ambíguo ele conserta; o resto **recusa**. Acento é o caso claro:
`josé@gmail.com` e `jose@gmail.com` são caixas de duas pessoas, e tirar o
acento por conta própria manda o link de acesso para a errada.

Quando a normalização muda o endereço, o sync **imprime a linha e o antes/
depois**. Sem isso a planilha ficaria com o valor ruim para sempre, já que ela
é a fonte da verdade e ninguém veria motivo para editar.

Revogar titular apaga a linha de `titulares`, não a conta no Auth. Corrigir um
e-mail deixa uma conta órfã com o endereço antigo — sem titular a RLS não
mostra nada, então é inofensiva, mas aparece na lista de usuários do painel.

**O aviso vai para a planilha, não só para o log.** Quem precisa corrigir a
célula é o técnico da Royal, e ele não lê log do GitHub Actions. A coluna
`Obs. Script` na aba `Titulares` é mão única — o sync escreve e apaga, ninguém
digita. Ele grava só o que mudou, para não gastar cota da API nem encher o
histórico de revisões da planilha todo dia.

A coluna é **opcional**: ausente, o sync avisa no log e segue. De propósito
ele não cria o cabeçalho sozinho — a primeira coluna livre pode ser vizinha de
algo que o time usa, e estrutura da planilha do cliente não é nossa para
mexer. `gerar_titulares.py` já inclui a coluna no CSV de projeto novo.

**E-mail imprestável congela o processo em vez de revogar.** Sem isso, um erro
de digitação deixaria a linha fora de `desejados`, o sync leria como "titular
saiu da aba" e revogaria — então um dedo errado tiraria do ar o acesso de um
cliente que funcionava, e o endereço novo nem seria criado, porque é inválido.
O cliente ficaria sem nada. Congelado, o acesso antigo continua valendo até a
correção. Por isso `ler_titulares` devolve a linha ruim, com `email` vazio, em
vez de descartá-la: é o que permite ao sync saber que o processo tem pendência.

`carga_inicial.py` não tem essa etapa de aviso, então lá a linha ruim é
descartada com aviso no terminal — gravar e-mail vazio criaria titular que
nunca entra.

**A CSP tem a URL do Supabase fixa** em `netlify.toml`, em `connect-src`.
Trocar de projeto exige mudar lá junto com `site/config.js`. Esquecer publica
um site que carrega bonito e falha em toda consulta.

---

## Comandos

```bash
python sincronizar.py              # simula; --aplicar grava; --forcar ignora a guarda
python carga_inicial.py            # primeira carga; gera uids_para_colar.txt
python provisionar_acessos.py      # audita quem está sem acesso
python gerar_titulares.py          # gera a aba Titulares para preencher
```

Todos simulam por padrão. Nenhum grava sem `--aplicar`.

`sincronizar.py --aplicar` já cria as contas de login que faltarem. Desligue
com `--sem-provisionar` se quiser controlar esse passo à parte.

**Cadastrar cliente novo:** numa passada na planilha, adicione a linha na aba
de fluxo (sem uid — o sync carimba) e a linha em `Titulares`. Ali o processo
pode ser identificado pelo **imóvel** em vez do `uid_processo`; o sync resolve
e escreve o uid de volta. Depois, um comando:

```bash
python sincronizar.py            # confere o plano
python sincronizar.py --aplicar  # cria processo, titular e conta de acesso
```

Identificar pelo imóvel existe porque copiar um UUID de 36 caracteres entre
abas era o passo mais propenso a erro do cadastro. Imóvel repetido não é
resolvido por adivinhação: o sync avisa e pede o `uid_processo` naquela linha.

**Trocar o e-mail de um cliente:** edite a coluna `email` na aba `Titulares`,
rode `python sincronizar.py` para conferir o plano — ele lista os acessos a
criar e a revogar —, depois `--aplicar`. Se a troca for em massa, a guarda
barra e exige `--forcar`, que é a fricção certa para revogar acesso de várias
pessoas.

`carga_inicial.py` serve só para o que o nome diz: a primeira carga de uma
planilha nova, em projeto novo. No dia a dia, quem cria processo é o sync.

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
| 1 — identidade | envio de e-mail pronto; **faltam os e-mails reais dos titulares** |
| 2 — site | no ar |
| 3 — sync automático | **no ar**, roda todo dia às 19:00 de Brasília |

O cliente optou pelo **Google Sheets** em 29/09/2026, o que eliminou a
dependência de registro de app no Azure AD com consentimento de admin — era o
bloqueio de prazo mais longo do projeto.

### E-mail: resolvido em 05/10/2026

SMTP próprio pelo **Resend**, domínio **`processosroyal.com.br`** — dedicado,
registrado só para isto, DNS no registro.br. Verificado com DKIM e SPF
passando, confirmado no cabeçalho de uma mensagem real.

Isto substituiu o serviço embutido do Supabase, que entrega **2 mensagens por
hora** — com 15 clientes, três pedidos de link na mesma hora e o terceiro não
recebe, sem erro na tela.

Roteiro completo, inclusive para montar isto em cliente novo, em
[`docs/configurar-email-resend.md`](docs/configurar-email-resend.md).

O `_dmarc` **não existe** na zona. É opcional e o domínio verificou sem ele.
Houve uma versão com `p=reject` enquanto o DKIM ainda não estava publicado —
combinação que recusa toda mensagem sem dar erro. Se um dia for adicionado,
comece em `p=none` e só endureça depois de confirmar entrega real.

**NÃO encoste no DNS de `royalimoveisrj.com` nem `royalimoveisrj.com.br`.**
Os dois estão delegados à inGaia (`ns1..ns4.gaiasite.com.br`) e o e-mail
corporativo da imobiliária passa por `mx.ingaia.com.br`. O painel do
registro.br mostra zona vazia para eles; publicar ali, ou mover a delegação,
derruba o e-mail da Royal. O domínio dedicado existe justamente para isso.

E os e-mails reais dos titulares, que hoje são de teste.

**Workflow agendado é desativado pelo GitHub após 60 dias sem commit no
repositório.** Este projeto pode ficar meses parado, e aí o sync para sozinho —
o sintoma é o site envelhecendo sem nada dar erro. O GitHub avisa o dono por
e-mail ao desativar; qualquer commit reativa.

---

## Não está no repositório

- **A planilha `.xlsx`** — tem dados de 15 compradores reais (fonte de
  desenvolvimento; a de produção é o Google Sheets)
- **`.env`** — tem a `service_role` key e o JSON da service account do Google
- **`credenciais*.json`** — a chave da service account
- `uids_para_colar.txt`, `titulares_para_colar.csv`

O histórico do Git é permanente: um dado commitado não sai apagando depois.

`site/config.js` **está** versionado e isso é correto — ele só tem a chave
`anon`, que é pública por natureza e vai para o navegador de todo visitante.
