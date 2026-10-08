"""Biblioteca do sincronizador.

Importar este pacote força a saída do terminal para UTF-8. Parece detalhe de
cosmética e não é: o terminal do Windows usa cp1252 por padrão, que não
representa a maior parte do Unicode, e `print` de um caractere de fora dessa
tabela **derruba o script com UnicodeEncodeError**.

Isso aconteceu em produção no primeiro dia. Um e-mail na aba Titulares tinha
vindo com a ligadura tipográfica "ﬂ" (U+FB02) em vez das letras `f` e `l` —
o Word e o PDF fazem essa troca sozinhos ao copiar. O sync quebrou ao
*imprimir* a lista de acessos, antes de chegar na guarda de sanidade, e a
mensagem de erro falava de codec, não de planilha, apontando para o suspeito
errado.

O dado ruim precisa ser corrigido na planilha de qualquer jeito — endereço com
ligadura não recebe e-mail. Mas o script tem que conseguir **mostrar** o
problema em vez de morrer antes disso.

No GitHub Actions nada disso aparece: Linux já é UTF-8. Era uma armadilha só
de quem roda na própria máquina, que é justamente quem está conferindo o plano
antes de aplicar.
"""

from __future__ import annotations

import sys

for _fluxo in (sys.stdout, sys.stderr):
    # `reconfigure` existe em TextIOWrapper (Python 3.7+). Sob redirecionamento
    # para arquivo ou pipe o objeto pode ser outro, daí o getattr.
    _reconfigurar = getattr(_fluxo, "reconfigure", None)
    if _reconfigurar is not None:
        # errors="replace" é a segunda rede: se algum dia a saída for para um
        # destino que não aceite UTF-8, o caractere vira "?" e o script segue.
        # Perder um acento num log é melhor que abortar uma sincronização.
        _reconfigurar(encoding="utf-8", errors="replace")

del _fluxo, _reconfigurar
