# Configurar o envio de e-mail (Resend)

Guia para quando houver sinal verde do cliente. Sem isto, **o site não atende
nenhum cliente real** — não é questão de volume, ver abaixo.

---

## Por que isto é necessário

O serviço de e-mail embutido do Supabase é de desenvolvimento:

| | Padrão do Supabase | Com SMTP próprio |
| --- | --- | --- |
| Limite de envio | **2 mensagens por hora** | 30/hora, ajustável |
| Entregabilidade | remetente compartilhado, reputação fora do seu controle | domínio próprio |

Com 15 clientes, duas mensagens por hora não se sustenta: se três pessoas
pedirem o link na mesma hora, a terceira não recebe. E **o sintoma é mudo** —
a tela de login mostra a mesma mensagem de sucesso com ou sem erro, de
propósito, para não revelar a terceiros quem é cliente da Royal.

A documentação do Supabase afirma também que o serviço padrão recusa entregar
para endereços fora da equipe do projeto. **Em 29/09/2026 isso não se
confirmou neste projeto**: um endereço externo, sem vínculo com a organização,
recebeu o link normalmente. Pode ser restrição em implantação gradual ou
aplicada a projetos de outra data — não dá para contar com nenhum dos dois
comportamentos.

O que é constante e suficiente para justificar a troca: o limite por hora e a
reputação do remetente compartilhado, que é o que faz magic link cair em spam.

---

## Pré-requisitos

- Domínio da Royal com acesso ao DNS
- Conta no Resend **criada com um e-mail que a Royal controla**

Sobre a segunda: se a conta for criada com o e-mail da agência que desenvolve,
a operação do cliente fica dependente de infraestrutura de terceiro. No dia em
que o contrato encerrar, o acesso dos compradores para de funcionar junto.
Crie com um endereço da Royal e mantenha acesso de operação.

---

## 1. Adicionar o domínio no Resend

**Domains → Add Domain.**

### Escolher entre raiz e subdomínio

O endereço do remetente tem que ser **no domínio exato que foi verificado**.
Verificar `acesso.royalimoveis.com.br` obriga a mandar de
`algo@acesso.royalimoveis.com.br`, o que fica redundante na caixa de entrada.

| Verificar | Remetente fica | |
| --- | --- | --- |
| `royalimoveis.com.br` | `acesso@royalimoveis.com.br` | mais limpo para o comprador |
| `mail.royalimoveis.com.br` | `acesso@mail.royalimoveis.com.br` | aceitável |
| `acesso.royalimoveis.com.br` | `acesso@acesso.royalimoveis.com.br` | redundante |

O Resend recomenda subdomínio para isolar reputação: se o e-mail transacional
tiver problema de entrega, não contamina o e-mail comercial da imobiliária.

Com o volume deste projeto — 15 clientes pedindo link esporadicamente — esse
risco é baixo, e a clareza para o comprador pesa mais. **Recomendação: raiz.**
Se o cliente for cauteloso com o e-mail corporativo, `mail.` resolve com pouca
perda de legibilidade.

Decida antes de publicar o DNS: mudar depois exige refazer a verificação.

O Resend devolve três registros para publicar no DNS:

| Tipo | Nome | Valor |
| --- | --- | --- |
| MX | `send` | `feedback-smtp.<região>.amazonses.com`, prioridade 10 |
| TXT | `send` | `v=spf1 include:amazonses.com ~all` |
| TXT | `resend._domainkey` | a chave DKIM que o painel mostrar |

**Pegadinha:** o nome vai **sem o domínio**. É `send`, não
`send.royalimoveis.com.br`. Quase todo painel de DNS completa sozinho, e quem
cola o nome inteiro cria `send.royalimoveis.com.br.royalimoveis.com.br`, que
não verifica nunca.

---

## 2. Publicar no DNS e aguardar

Os registros que o Resend mostra **variam conforme a região** escolhida. Na
região de São Paulo ele pede dois CNAME apontando para `forge.rmta.net`; em
outras, MX e TXT apontando para `amazonses.com`. **Copie o que o painel
mostrar**, não uma lista decorada.

Ao copiar o DKIM, use o botão de copiar do Resend. O valor aparece truncado na
tela (`p=MIGfMA [...] QIDAQAB`), e chave cortada é a causa mais comum de
verificação que nunca completa.

No campo de nome, use só o prefixo — `resend._domainkey`, `send`, `rsend`. O
painel de DNS completa o domínio sozinho, e quem cola o nome inteiro cria
`send.dominio.com.dominio.com`.

### O que perguntar ao cliente

Duas perguntas destravam a etapa:

1. **Onde o DNS do domínio é gerenciado?** Registrador, Cloudflare, painel da
   hospedagem, ou a agência que fez o site.
2. **Já existe um registro `_dmarc`?** Só pode haver um por domínio. Se existir,
   **não crie outro** — ver a seção sobre DMARC adiante. Ele é opcional e o
   domínio verifica sem ele.

Antecipe a preocupação de quem administra DNS de empresa: **isto não afeta o
e-mail atual**. Os registros ficam em nomes exclusivos do Resend
(`resend._domainkey`, `send`, `rsend`) e não colidem com Google Workspace,
Microsoft 365 ou qualquer outro provedor.

### Route 53, se for o caso

O Route 53 aceita no máximo 255 caracteres por trecho de TXT, e a chave DKIM
costuma passar disso. Quebre em dois trechos entre aspas, na mesma linha — o
Route 53 junta automaticamente:

```
"p=MIGfMA0GCSqG...primeiros 255 caracteres" "restante da chave"
```

Colar tudo de uma vez dá erro ou salva truncado.

### Sobre o DMARC

Os três registros têm papéis diferentes, e é fácil confundi-los:

| | Pergunta que responde |
| --- | --- |
| **SPF** | quais servidores podem mandar em nome deste domínio? |
| **DKIM** | esta mensagem foi assinada por um deles, e chegou intacta? |
| **DMARC** | e se as respostas acima forem "não"? O que faço com a mensagem? |

SPF e DKIM são as verificações; DMARC é a **política** sobre o que fazer quando
elas falham. O que importa é o valor de `p=`:

| Política | O destinatário faz |
| --- | --- |
| `p=none` | nada — entrega normal, só registra |
| `p=quarantine` | joga no spam |
| `p=reject` | recusa, a mensagem nem chega |

O Resend sugere `v=DMARC1; p=none;`, que é **modo observação**: não muda nada
na entrega, só declara publicamente que o domínio tem política — sinal de
domínio bem cuidado para Gmail e Outlook.

Começar em `none` é a prática recomendada. Ir direto para `reject` com alguma
coisa mal configurada faria e-mail legítimo da imobiliária ser recusado sem
aviso.

**Só pode haver um `_dmarc` por domínio.** O destinatário procura um registro
nesse nome; achando dois, a especificação manda ignorar os dois. O resultado é
pior que não ter nenhum — você acha que tem política e não tem.

Então: se já existir, **pule**. Se não existir, adicione o `p=none`. Custo
zero, risco zero.

O underscore em `_dmarc` e `_domainkey` é convenção: sinaliza que o nome não é
endereço de servidor, e sim configuração para máquina ler. Por isso eles
parecem estranhos ao lado de `www` e `mail`.

### Prazo

A verificação leva **até 72 horas**, normalmente bem menos. O painel do Resend
mostra o status — só siga quando estiver verificado.

---

## 3. Criar a chave de API

**API Keys → Create API Key**, com permissão de envio e **restrita ao domínio**
da Royal.

A restrição importa: se a chave vazar ou precisar ser revogada, nada mais na
conta é afetado.

A chave aparece **uma única vez**. Copie na hora e guarde onde a equipe
encontre depois.

---

## 4. Configurar no Supabase

**Project Settings → Authentication → SMTP Settings**, ligar *Enable Custom
SMTP*:

| Campo | Valor |
| --- | --- |
| Host | `smtp.resend.com` |
| Port | `587` |
| Username | `resend` — literalmente esta palavra |
| Password | a API key (`re_...`) |
| Sender email | um endereço **do domínio verificado** |
| Sender name | `Royal Imóveis` |

O `Sender email` precisa ser do domínio verificado. Se for de outro, o Resend
recusa, e o sintoma é o de sempre: nenhum link chega e nada dá erro.

**Não precisa ser uma caixa de e-mail que existe.** É apenas o campo "De:" da
mensagem; ninguém entrega nada nesse endereço. O que o Resend exige é o
domínio, não a caixa.

Mas tem consequência: se o comprador **responder** ao e-mail do link, a
resposta vai para esse endereço. Caixa inexistente devolve erro, e o cliente
acha que foi ignorado.

| Endereço | Respostas |
| --- | --- |
| Caixa real que alguém lê | chegam a alguém — melhor |
| `nao-responda@...` | somem, mas o nome já avisa |
| Caixa inexistente com nome comum | somem **e** o cliente não sabe |

Use uma das duas primeiras. A terceira é a única ruim.

O `Sender name` é o que o comprador vê na caixa de entrada. Deve ser o nome da
imobiliária, não o de quem desenvolveu.

---

## 5. Subir o limite de envios

**Authentication → Rate Limits.**

Depois de trocar o SMTP, o Supabase impõe 30 mensagens por hora para proteger a
reputação de um serviço recém-configurado. Ajuste para o volume esperado.

Este é o passo mais esquecido do roteiro: troca-se o SMTP para resolver a cota
e o gargalo continua onde estava.

---

## 6. Conferir que funcionou

Entre no site com o e-mail de um titular e **abra o cabeçalho da mensagem**
recebida. O remetente precisa ser o do domínio da Royal.

Se ainda vier pelo remetente antigo, o Supabase não aplicou a configuração —
confira se *Enable Custom SMTP* ficou realmente ligado e salvo.

Teste também com um endereço **fora** da equipe do Supabase. É exatamente o
caso que o serviço padrão recusava, e é o que prova que a troca resolveu.

---

## Registrar depois de pronto

Anote em algum lugar que a equipe encontre:

- com qual e-mail a conta do Resend foi criada
- qual subdomínio foi verificado
- onde a API key está guardada
- quem administra a conta

Daqui a oito meses, quando alguém precisar rotacionar a chave, essa informação
não pode existir só na cabeça de uma pessoa.
