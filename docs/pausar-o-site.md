# Pausar e religar o site, só pelo GitHub

Sem terminal, sem entrar no Netlify. Um arquivo renomeado pelo navegador.

---

## O que a pausa faz, e o que não faz

**Faz:** todo endereço do site passa a mostrar a página de manutenção. Login,
painel e acompanhamento ficam inalcançáveis — inclusive para quem já estava
logado, porque a própria tela deixa de ser entregue.

**Não faz:** não desliga o banco nem a sincronização. O Supabase continua
respondendo a quem tiver um token válido e souber chamá-lo direto, e o
`sincronizar.py` continua rodando todo dia. Para parar o sync também, veja
[Pausar a sincronização](#pausar-a-sincronização) no fim.

Nenhum dado é apagado. Religar devolve o site exatamente como estava.

---

## Pausar

1. Abra o repositório no GitHub e vá até **`site/_redirects.inativo`**
2. Clique no arquivo, depois no lápis (**Edit this file**)
3. No campo do nome, no alto, apague o `.inativo` — o nome tem que ficar
   exatamente:

   ```
   _redirects
   ```

4. **Commit changes**

O Netlify publica sozinho em um ou dois minutos.

### Confira

Abra <https://royalstatuscliente.netlify.app> numa aba anônima. Tem que
aparecer "Voltamos em breve".

Se ainda aparecer a tela de login, o nome do arquivo está errado. Volte ao
passo 3 e confira caractere por caractere: começa com sublinhado (`_`), tudo
minúsculo, sem `.txt` no fim.

**Aba anônima importa.** Na janela normal o navegador pode mostrar a versão
guardada em cache e te enganar.

---

## Religar

O mesmo caminho, ao contrário:

1. Abra **`site/_redirects`**
2. Lápis (**Edit this file**)
3. Devolva o nome para:

   ```
   _redirects.inativo
   ```

4. **Commit changes**

Confira do mesmo jeito, em aba anônima: a tela de login tem que voltar.

---

## Por que renomear, e não editar a configuração

Errar o nome do arquivo deixa o site **no ar** — o lado seguro de errar, porque
você percebe na conferência e corrige.

Editar o `netlify.toml` para isso seria pior: uma vírgula fora do lugar quebra
o arquivo inteiro, e junto com ele vão os cabeçalhos de segurança e a regra que
limita as chamadas ao Supabase. O site subiria quebrado de um jeito silencioso.

---

## Pausar a sincronização

Se a pausa for longa, ou se o técnico for reestruturar a planilha, vale parar o
sync também. É pelo GitHub, sem mexer em código:

1. No repositório: **Settings → Secrets and variables → Actions**
2. Aba **Variables**
3. `SYNC_HABILITADO` — crie se não existir, com o valor `0`

A execução diária continua acontecendo, mas sai sem gravar nada e termina
verde, com esta linha no log:

```
SYNC DESLIGADO por SYNC_HABILITADO no ambiente.
```

Para religar, troque o valor para `1` (ou apague a variável — sem ela, o padrão
é ligado).

### Cuidado com pausa longa

O GitHub **desativa workflow agendado após 60 dias sem commit no repositório**.
Se o projeto ficar parado meses, o sync morre sozinho e o sintoma é o site
envelhecendo sem erro nenhum. O GitHub avisa o dono por e-mail; qualquer commit
reativa.

---

## Arquivos envolvidos

| | |
| --- | --- |
| `site/_redirects.inativo` | a regra; o nome decide se vale |
| `site/manutencao.html` | a página que o cliente vê |

A página é **autossuficiente**: todo o CSS está dentro dela e não há imagem nem
script externo. Isso não é descuido — com a pausa ligada, `/assets/app.css` e
`/assets/royal-logo.png` também caem na regra e receberiam HTML de volta. Uma
página de manutenção que depende de arquivo externo aparece sem estilo nenhum
justamente quando está em uso.
