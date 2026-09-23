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
    uid_processo: str
    nome: str
    email: str


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
            data_assinatura=valor(i_data) or None,
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

def ler_titulares(fonte) -> list[LinhaTitular]:
    """Lê a aba Titulares. Ausente, devolve lista vazia.

    Esta aba é quem resolve os casais: seis dos quinze processos têm duas
    pessoas, e cada uma recebe o próprio acesso. O campo Cliente da aba de
    fluxo NÃO é partido automaticamente — os separadores são inconsistentes
    ("/", " / ", "/ ", " e ") e uma linha mal partida daria a alguém acesso ao
    processo de outro.
    """
    try:
        linhas = fonte.ler_aba(ABA_TITULARES)
    except Exception:
        return []

    if not linhas:
        return []

    i_cab = None
    for i, linha in enumerate(linhas[:15]):
        chaves = {normalizar_rotulo(c) for c in linha}
        if "email" in chaves and ("uid_processo" in chaves or "uid_royal" in chaves):
            i_cab = i
            break
    if i_cab is None:
        raise PlanilhaError(
            f"Aba {ABA_TITULARES!r} existe mas não tem as colunas esperadas: "
            "uid_processo, nome, email."
        )

    colunas = mapear_colunas(linhas[i_cab])
    i_uid = colunas.get("uid_processo", colunas.get("uid_royal"))
    i_nome = colunas.get("nome")
    i_email = colunas.get("email")

    titulares: list[LinhaTitular] = []
    for linha in linhas[i_cab + 1:]:
        def valor(idx):
            if idx is None or idx >= len(linha):
                return ""
            return (linha[idx] or "").strip()

        uid, email = valor(i_uid), valor(i_email).lower()
        if not uid or not email:
            continue
        titulares.append(LinhaTitular(
            uid_processo=uid,
            nome=valor(i_nome) or email,
            email=email,
        ))

    return titulares
