"""Leitura e normalização das abas de fluxo.

Regra que orienta este módulo: **coluna se localiza por texto de cabeçalho,
nunca por posição**. A planilha já foi reestruturada duas vezes — na última, a
coluna "Data da Assinatura" entrou na posição B e empurrou tudo, e a numeração
das etapas do fluxo financiado mudou de 1..8,10..12 para 1..9. Código que
dependesse de índice teria quebrado nas duas vezes.

Pelo mesmo motivo o prefixo ordinal ("1° ", "10° ") é descartado antes de
comparar: a numeração muda, o texto da etapa não.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Abas de fluxo e a modalidade que cada uma representa.
ABAS_FLUXO: dict[str, str] = {
    "Fluxo A Vista": "avista",
    "Fluxo Financiado": "financiado",
}

# Aba que o time da Royal preenche com quem pode acessar cada processo.
ABA_TITULARES = "Titulares"

# Cabeçalho da coluna de identidade que o sync carimba.
COLUNA_UID = "uid_royal"

# Coluna da aba Titulares onde o sync escreve recado para o técnico da Royal.
# Mão única: o sync escreve, ninguém digita ali. Opcional — sem ela o sync
# só avisa no log, que o técnico não lê.
COLUNA_OBS = "Obs. Script"

# Gravidade do aviso. O sync classifica; quem pinta é a camada da fonte, que
# escolhe a cor. Esta separação existe para a regra não saber de RGB.
#
#   atencao  o cliente ENTRA; só a célula está ruim
#   erro     o cliente NÃO entra até alguém corrigir
NIVEL_ATENCAO = "atencao"
NIVEL_ERRO = "erro"

# Status aceitos, já normalizados. Bate com o CHECK das tabelas no banco.
STATUS_VALIDOS = {
    "nao_iniciado", "em_andamento", "pendente",
    "concluido", "atrasado", "cancelado",
}


class PlanilhaError(RuntimeError):
    """Planilha fora do formato esperado. O sync para em vez de gravar lixo."""


@dataclass
class LinhaProcesso:
    aba: str
    numero_linha: int              # 1-based, para carimbar o uid de volta
    modalidade: str
    uid: str | None
    cliente_bruto: str             # texto cru do campo Cliente, sem partir
    imovel: str
    corretor: str
    data_assinatura: str | None    # ISO ou None
    etapas: dict[str, str] = field(default_factory=dict)  # codigo -> status


@dataclass
class LinhaTitular:
    numero_linha: int          # 1-based, para carimbar o uid de volta
    uid_processo: str | None   # vazio quando a pessoa identificou pelo imóvel
    imovel: str                # alternativa ao uid, mais fácil de digitar
    nome: str
    email: str
    # O texto exatamente como está na célula. Guardado porque quando a
    # normalização muda o endereço, a planilha segue com o valor ruim — e a
    # planilha é a fonte da verdade (regra 8). O sync usa isto para avisar
    # qual célula corrigir à mão.
    email_bruto: str = ""
    # Frase curta para a coluna "Obs. Script", escrita para o técnico da
    # Royal. None = célula do e-mail está boa.
    problema: str | None = None
    # Gravidade do problema: NIVEL_ATENCAO, NIVEL_ERRO ou None.
    nivel: str | None = None
    # Texto que já está na coluna de observação, para o sync escrever só o
    # que mudou em vez de reescrever a coluna toda a cada execução.
    obs_atual: str = ""


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def normalizar_rotulo(texto: str) -> str:
    """Chave de comparação de cabeçalho.

    Tira o prefixo ordinal, acentos, caixa e espaço repetido. O que sobra é
    estável entre reestruturações da planilha.

        "6° Tirar certidões (E-Cartório e gratuitas)"
        -> "tirar certidoes (e-cartorio e gratuitas)"
    """
    t = re.sub(r"^\s*\d+\s*°?\s*", "", texto or "")
    t = sem_acento(t).lower()
    return re.sub(r"\s+", " ", t).strip()


def normalizar_status(bruto: str) -> str:
    """Converte o status da planilha para o slug do banco.

    Valor desconhecido levanta erro de propósito: é a guarda que impede o sync
    de gravar um status que o banco rejeitaria, ou pior, de inventar um padrão.
    """
    t = sem_acento((bruto or "").strip()).lower()
    t = re.sub(r"\s+", "_", t)

    if not t:
        return "nao_iniciado"       # célula vazia = etapa ainda não começou
    if t not in STATUS_VALIDOS:
        raise PlanilhaError(
            f"Status desconhecido na planilha: {bruto!r}. "
            f"Esperado um de: {', '.join(sorted(STATUS_VALIDOS))}"
        )
    return t


# Caracteres sem desenho que sobrevivem ao strip e ao NFKC. Chegam por cópia
# de página web ou de documento formatado, e deixam o endereço visualmente
# idêntico ao correto — o pior tipo de defeito, porque ninguém acha olhando.
INVISIVEIS = {
    0x00AD: None,   # soft hyphen
    0x200B: None,   # zero width space
    0x200C: None,   # zero width non-joiner
    0x200D: None,   # zero width joiner
    0x200E: None,   # left-to-right mark
    0x200F: None,   # right-to-left mark
    0x2060: None,   # word joiner
    0xFEFF: None,   # byte order mark
}

FORMATO_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class EmailAnalisado:
    """Resultado da limpeza de um endereço vindo da planilha.

    `problema` é escrito para o técnico da Royal ler na própria planilha, não
    para programador: frase curta, sem jargão, dizendo o que fazer.
    """

    bruto: str
    limpo: str                  # "" quando não dá para usar
    problema: str | None        # None = célula está boa
    corrigido: bool             # dá para usar, mas o texto da célula está ruim
    nivel: str | None = None    # NIVEL_ATENCAO, NIVEL_ERRO ou None

    @property
    def utilizavel(self) -> bool:
        return bool(self.limpo)


def analisar_email(bruto: str) -> EmailAnalisado:
    """Limpa o endereço e **descreve** o que achou, sem levantar erro.

    Minúsculas são o menor dos problemas: e-mail não diferencia caixa, e tanto
    o Supabase quanto a tela de login já convertem. O que de fato morde é o
    caractere que *parece* certo e não é.

    No primeiro dia em produção um endereço veio com `ﬂ` (U+FB02), a ligadura
    tipográfica que o Word e o PDF colocam sozinhos no lugar de `f` + `l`.
    Minúsculo não conserta: a ligadura já é minúscula. Quem conserta é o NFKC,
    que decompõe `ﬂ` em `fl`, `＠` de largura total em `@`, e companhia.

    A ordem importa: NFKC antes da caixa.

    O que o NFKC não resolve, esta função **recusa** em vez de adivinhar.
    Acento é o caso claro: `josé@gmail.com` e `jose@gmail.com` são caixas de
    duas pessoas, e tirar o acento por conta própria mandaria o link de acesso
    do cliente para a errada.

    Não levanta erro de propósito. Parar aqui mataria o sync inteiro por causa
    de uma célula: ninguém atualizaria e — pior — a observação na planilha
    nunca seria escrita, justamente a que avisaria o técnico. Quem decide o
    que fazer é `sincronizar.py`.
    """
    bruto = bruto or ""
    t = bruto.strip()
    if not t:
        return EmailAnalisado(bruto, "", None, False)

    t = unicodedata.normalize("NFKC", t)
    t = t.translate(INVISIVEIS)
    t = t.strip().lower()

    # Mensagens curtas de propósito: ficam numa célula de planilha, que o
    # técnico lê de passagem. Frase longa é rolada para fora da vista e não
    # é lida — aviso que ninguém lê não serve para nada.
    def ruim(msg: str) -> EmailAnalisado:
        return EmailAnalisado(bruto, "", f"SEM ACESSO: {msg}", False, NIVEL_ERRO)

    if not t:
        return ruim("célula só tem caracteres invisíveis. Digite o e-mail à mão.")

    if any(c.isspace() for c in t):
        return ruim("e-mail com espaço no meio. Apague a célula e corrija.")

    fora = sorted({c for c in t if ord(c) > 127})
    if fora:
        amostra = " ".join(c for c in fora)
        return ruim(
            f"e-mail com caractere inválido ({amostra}). Apague a célula e "
            "digite à mão, sem colar."
        )

    if not FORMATO_EMAIL.fullmatch(t):
        return ruim("e-mail sem @ ou sem domínio. Confira e digite de novo.")

    if t != bruto.strip().lower():
        # Deu para usar, mas a célula tem caractere que só parece certo. Não
        # avisar deixaria o texto ruim na planilha para sempre, e ele voltaria
        # no próximo cadastro feito do mesmo jeito (copiando de documento).
        return EmailAnalisado(
            bruto, t,
            f"ATENÇÃO: e-mail com caractere especial. O sistema usará {t}. "
            "Apague a célula e corrija se necessário.",
            True, NIVEL_ATENCAO,
        )

    return EmailAnalisado(bruto, t, None, False, None)


def normalizar_email(bruto: str, onde: str = "") -> str:
    """Igual a `analisar_email`, mas **para** no primeiro problema.

    Serve a quem prefere falhar na hora; o sync usa `analisar_email`, que
    descreve o problema sem interromper a execução.
    """
    r = analisar_email(bruto)
    if r.utilizavel:
        return r.limpo
    if r.problema is None:
        return ""

    local = f" ({onde})" if onde else ""
    # O texto de `problema` é escrito para o técnico; aqui vira mensagem de
    # erro, então ganha a localização e o valor cru entre aspas.
    detalhe = r.problema.removeprefix("SEM ACESSO: ")
    raise PlanilhaError(f"E-mail{local} {bruto!r}: {detalhe}")


def normalizar_data(bruto: str) -> str | None:
    """Converte a data da planilha para ISO (AAAA-MM-DD).

    Aceita três formas, porque as fontes entregam coisas diferentes:

      - ISO, vindo do .xlsx pelo openpyxl
      - número de série do Google Sheets, dias desde 30/12/1899
      - dd/mm/aaaa, caso alguém leia com formatação

    O formato dd/mm/aaaa assume DIA PRIMEIRO, que é o padrão pt-BR da planilha.
    É a única das três que seria ambígua; as outras duas não dependem de
    idioma, e é por isso que a fonte do Sheets pede valor não formatado.

    Valor irreconhecível levanta erro em vez de virar None em silêncio: data
    errada no acompanhamento vira "há X dias" errado na tela do cliente.
    """
    import datetime as _dt

    t = (bruto or "").strip()
    if not t:
        return None

    # ISO
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return t

    # número de série do Sheets (e do Excel): dias desde 30/12/1899
    m = re.fullmatch(r"(\d+)(?:\.\d+)?", t)
    if m:
        serie = int(m.group(1))
        # 1 a 100000 cobre de 1900 a 2173. Fora disso não é data.
        if 1 <= serie <= 100000:
            return (_dt.date(1899, 12, 30) + _dt.timedelta(days=serie)).isoformat()

    # dd/mm/aaaa ou dd/mm/aa
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", t)
    if m:
        dia, mes, ano = (int(g) for g in m.groups())
        if ano < 100:
            ano += 2000
        try:
            return _dt.date(ano, mes, dia).isoformat()
        except ValueError as e:
            raise PlanilhaError(f"Data inválida na planilha: {bruto!r} ({e})") from e

    raise PlanilhaError(
        f"Não reconheci a data {bruto!r}. Esperado AAAA-MM-DD, dd/mm/aaaa "
        "ou número de série do Sheets."
    )


def letra_coluna(indice_zero: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    n = indice_zero + 1
    while n > 0:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


# ---------------------------------------------------------------------------
# Localização do cabeçalho
# ---------------------------------------------------------------------------

def achar_linha_cabecalho(linhas: list[list[str]]) -> int:
    """Índice (0-based) da linha de cabeçalho.

    A planilha tem título e subtítulo antes da tabela, e a posição já mudou
    entre versões — então procuramos em vez de fixar.
    """
    for i, linha in enumerate(linhas[:15]):
        chaves = {normalizar_rotulo(c) for c in linha}
        if "cliente" in chaves and "corretor" in chaves:
            return i
    raise PlanilhaError(
        "Não achei a linha de cabeçalho: nenhuma das 15 primeiras linhas tem "
        "as colunas 'Cliente' e 'Corretor' juntas."
    )


def mapear_colunas(cabecalho: list[str]) -> dict[str, int]:
    """Rótulo normalizado -> índice da coluna."""
    mapa: dict[str, int] = {}
    for i, celula in enumerate(cabecalho):
        chave = normalizar_rotulo(celula)
        if chave and chave not in mapa:
            mapa[chave] = i
    return mapa


# ---------------------------------------------------------------------------
# Leitura das abas de fluxo
# ---------------------------------------------------------------------------

def ler_fluxo(
    fonte,
    aba: str,
    modalidade: str,
    catalogo: list[dict],
) -> list[LinhaProcesso]:
    """Lê uma aba de fluxo e devolve os processos preenchidos.

    `catalogo` são as linhas de etapas_catalogo da modalidade, cada uma com
    ao menos `codigo` e `rotulo_interno`. É o banco que manda no mapeamento:
    se a planilha ganhar uma etapa que o catálogo não conhece, o sync para.
    """
    linhas = fonte.ler_aba(aba)
    if not linhas:
        raise PlanilhaError(f"Aba {aba!r} está vazia.")

    i_cab = achar_linha_cabecalho(linhas)
    cabecalho = linhas[i_cab]
    colunas = mapear_colunas(cabecalho)

    def coluna(*nomes: str) -> int | None:
        for nome in nomes:
            idx = colunas.get(normalizar_rotulo(nome))
            if idx is not None:
                return idx
        return None

    i_cliente = coluna("Cliente")
    i_imovel = coluna("Imóvel / Empreendimento", "Imovel / Empreendimento", "Imóvel")
    i_corretor = coluna("Corretor")
    i_data = coluna("Data da Assinatura")
    i_uid = coluna(COLUNA_UID)

    if i_cliente is None or i_imovel is None:
        raise PlanilhaError(
            f"Aba {aba!r}: faltam as colunas 'Cliente' e/ou 'Imóvel / Empreendimento'."
        )

    # Cada etapa do catálogo precisa achar sua coluna. Etapa sem coluna é sinal
    # de que a planilha mudou e o catálogo ficou para trás — parar é melhor do
    # que gravar metade.
    etapa_por_coluna: dict[int, str] = {}
    faltando: list[str] = []
    for etapa in catalogo:
        idx = colunas.get(normalizar_rotulo(etapa["rotulo_interno"]))
        if idx is None:
            faltando.append(etapa["rotulo_interno"])
        else:
            etapa_por_coluna[idx] = etapa["codigo"]

    if faltando:
        raise PlanilhaError(
            f"Aba {aba!r}: estas etapas do catálogo não têm coluna correspondente "
            f"na planilha:\n  - " + "\n  - ".join(faltando) +
            "\n\nOu a planilha mudou e o catálogo precisa ser atualizado "
            "(supabase/migrations/20260923000200_catalogo_etapas.sql), "
            "ou o texto do cabeçalho foi editado."
        )

    processos: list[LinhaProcesso] = []
    for deslocamento, linha in enumerate(linhas[i_cab + 1:], start=1):
        numero_linha = i_cab + 1 + deslocamento  # 1-based na planilha

        def valor(idx: int | None) -> str:
            if idx is None or idx >= len(linha):
                return ""
            return (linha[idx] or "").strip()

        cliente = valor(i_cliente)
        if not cliente:
            continue                    # linha em branco pré-formatada

        etapas: dict[str, str] = {}
        for idx, codigo in etapa_por_coluna.items():
            try:
                etapas[codigo] = normalizar_status(valor(idx))
            except PlanilhaError as e:
                raise PlanilhaError(
                    f"Aba {aba!r}, linha {numero_linha}, cliente {cliente!r}: {e}"
                ) from e

        processos.append(LinhaProcesso(
            aba=aba,
            numero_linha=numero_linha,
            modalidade=modalidade,
            uid=valor(i_uid) or None,
            cliente_bruto=cliente,
            imovel=valor(i_imovel),
            corretor=valor(i_corretor),
            data_assinatura=normalizar_data(valor(i_data)),
        ))
        processos[-1].etapas = etapas

    return processos


def indice_coluna_uid(fonte, aba: str) -> tuple[int, bool]:
    """Onde o uid_royal está, ou onde deveria ficar.

    Devolve (índice 0-based, já_existe). Quando não existe, aponta a primeira
    coluna livre depois do último cabeçalho preenchido.
    """
    linhas = fonte.ler_aba(aba)
    i_cab = achar_linha_cabecalho(linhas)
    cabecalho = linhas[i_cab]

    colunas = mapear_colunas(cabecalho)
    idx = colunas.get(normalizar_rotulo(COLUNA_UID))
    if idx is not None:
        return idx, True

    ultimo_preenchido = -1
    for i, celula in enumerate(cabecalho):
        if (celula or "").strip():
            ultimo_preenchido = i
    return ultimo_preenchido + 1, False


def linha_cabecalho_numero(fonte, aba: str) -> int:
    """Número 1-based da linha de cabeçalho, para gravar o título da coluna."""
    return achar_linha_cabecalho(fonte.ler_aba(aba)) + 1


# ---------------------------------------------------------------------------
# Aba de titulares
# ---------------------------------------------------------------------------

def _cabecalho_titulares(linhas: list[list[str]]) -> int:
    """Índice (0-based) do cabeçalho da aba Titulares."""
    for i, linha in enumerate(linhas[:15]):
        chaves = {normalizar_rotulo(c) for c in linha}
        if "email" in chaves and ("uid_processo" in chaves or "imovel" in chaves
                                  or "imovel / empreendimento" in chaves):
            return i
    raise PlanilhaError(
        f"Aba {ABA_TITULARES!r} existe mas não tem as colunas esperadas. "
        "São necessárias: email, nome, e uid_processo OU imóvel."
    )


def info_coluna_uid_titulares(fonte) -> tuple[str, int]:
    """Letra da coluna uid_processo na aba Titulares e a linha do cabeçalho.

    O sync usa para escrever o uid de volta depois de resolver pelo imóvel —
    assim a pessoa nunca precisa copiar um UUID de 36 caracteres na mão, que
    era o passo mais frágil do cadastro de cliente novo.
    """
    linhas = fonte.ler_aba(ABA_TITULARES)
    i_cab = _cabecalho_titulares(linhas)
    colunas = mapear_colunas(linhas[i_cab])
    idx = colunas.get("uid_processo")
    if idx is None:
        # coluna ausente: indica a primeira livre depois do último cabeçalho
        ultimo = max((i for i, c in enumerate(linhas[i_cab]) if (c or "").strip()),
                     default=-1)
        idx = ultimo + 1
    return letra_coluna(idx), i_cab + 1


def info_coluna_obs(fonte) -> str | None:
    """Letra da coluna de observação na aba Titulares, ou None se não existir.

    Diferente de `info_coluna_uid_titulares`, esta **não** aponta a primeira
    coluna livre quando a coluna falta. Criar cabeçalho sozinho na planilha do
    cliente é mexer em estrutura que não é nossa, e a primeira livre pode ser
    vizinha de algo que o time usa. Ausente, o sync avisa no log e segue.
    """
    linhas = fonte.ler_aba(ABA_TITULARES)
    if not linhas:
        return None
    i_cab = _cabecalho_titulares(linhas)
    idx = mapear_colunas(linhas[i_cab]).get(normalizar_rotulo(COLUNA_OBS))
    return None if idx is None else letra_coluna(idx)


def ler_titulares(fonte) -> list[LinhaTitular]:
    """Lê a aba Titulares. Ausente, devolve lista vazia.

    Esta aba é quem resolve os casais: seis dos quinze processos têm duas
    pessoas, e cada uma recebe o próprio acesso. O campo Cliente da aba de
    fluxo NÃO é partido automaticamente — os separadores são inconsistentes
    ("/", " / ", "/ ", " e ") e uma linha mal partida daria a alguém acesso ao
    processo de outro.

    O processo pode ser identificado de duas formas:

      uid_processo  exato, e é o que fica na planilha depois
      imóvel        para digitar na mão; o sync resolve e carimba o uid

    A segunda existe porque copiar um UUID entre abas era o passo mais
    propenso a erro do cadastro de cliente novo.
    """
    try:
        linhas = fonte.ler_aba(ABA_TITULARES)
    except Exception:
        return []

    if not linhas:
        return []

    i_cab = _cabecalho_titulares(linhas)
    colunas = mapear_colunas(linhas[i_cab])
    i_uid = colunas.get("uid_processo")
    i_nome = colunas.get("nome")
    i_email = colunas.get("email")
    i_imovel = colunas.get("imovel / empreendimento", colunas.get("imovel"))
    i_obs = colunas.get(normalizar_rotulo(COLUNA_OBS))

    titulares: list[LinhaTitular] = []
    for deslocamento, linha in enumerate(linhas[i_cab + 1:], start=1):
        def valor(idx):
            if idx is None or idx >= len(linha):
                return ""
            return (linha[idx] or "").strip()

        numero_linha = i_cab + 1 + deslocamento

        email_bruto = valor(i_email)
        if not email_bruto:
            continue

        # Linha com e-mail ruim continua sendo devolvida, com `email` vazio.
        # É o que permite ao sync escrever a observação na planilha e, mais
        # importante, saber que aquele processo tem pendência — sem isso ele
        # trataria a linha como "titular que saiu da aba" e revogaria o
        # acesso que ainda funciona.
        analise = analisar_email(email_bruto)
        email = analise.limpo

        uid, imovel = valor(i_uid), valor(i_imovel)
        if not uid and not imovel:
            raise PlanilhaError(
                f"Aba {ABA_TITULARES!r}, linha {numero_linha}: "
                f"{email_bruto} não tem uid_processo nem imóvel. Preencha um "
                "dos dois para o sync saber a qual processo o acesso pertence."
            )

        titulares.append(LinhaTitular(
            numero_linha=numero_linha,
            uid_processo=uid or None,
            imovel=imovel,
            nome=valor(i_nome) or email or email_bruto,
            email=email,
            email_bruto=email_bruto,
            problema=analise.problema,
            nivel=analise.nivel,
            obs_atual=valor(i_obs),
        ))

    return titulares
