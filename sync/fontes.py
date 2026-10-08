"""Camada de entrada: de onde a planilha é lida.

Todo o resto do sistema não sabe qual fonte está em uso. Trocar de fonte é
mudar a variável FONTE_PLANILHA no .env — nenhum outro arquivo muda.

Implementações:
    FonteGoogleSheets  gspread + service account   — produção
    FonteXlsxLocal     openpyxl, arquivo no disco  — desenvolvimento

O Excel Online via Microsoft Graph chegou a ser desenhado e foi descartado: o
cliente optou pelo Google Sheets, o que eliminou a dependência de registro de
app no Azure AD com consentimento de admin do tenant — que era o item de prazo
mais longo do projeto e dependia da TI de terceiro.
"""

from __future__ import annotations

import os
from typing import Protocol


class FonteError(RuntimeError):
    """Problema ao ler ou escrever na planilha."""


# Fundo das células de aviso, por nível de gravidade.
#
# Mora aqui, e não em planilha.py, porque é apresentação: o sync decide se a
# linha tem "atencao" ou "erro" e esta camada escolhe o RGB. Trocar a paleta
# não encosta na regra.
#
# Âmbar e vermelho claros de propósito: o técnico lê o TEXTO dentro da célula,
# e fundo saturado com letra preta fica ilegível. Clarear o fundo mantém o
# contraste do texto e ainda assim salta numa coluna de células brancas.
CORES_AVISO: dict[str, dict[str, float]] = {
    # #FFF3CD
    "atencao": {"red": 1.0, "green": 0.953, "blue": 0.804},
    # #F8D7DA
    "erro": {"red": 0.973, "green": 0.843, "blue": 0.855},
}

# Célula sem aviso. Branco explícito em vez de "sem preenchimento": a API de
# formatação não tem como dizer "volte ao padrão" numa chamada de lote.
COR_LIMPA: dict[str, float] = {"red": 1.0, "green": 1.0, "blue": 1.0}


class FonteDePlanilha(Protocol):
    """Contrato mínimo que o sync exige de qualquer fonte."""

    def ler_aba(self, nome: str) -> list[list[str]]:
        """Devolve a aba inteira como linhas de texto, incluindo o cabeçalho.

        Células vazias viram string vazia, nunca None.
        """
        ...

    def escrever_celula(self, aba: str, linha: int, coluna: str, valor: str) -> None:
        """Grava uma célula. `linha` é 1-based, `coluna` é letra ("Q").

        Usado para carimbar o uid_royal em linhas novas. Não é sincronização
        de duas vias — é identidade, e nenhum humano digita ali.
        """
        ...

    def escrever_celulas(
        self, aba: str, celulas: list[tuple[int, str, str]]
    ) -> None:
        """Grava várias células de uma vez. Cada item é (linha, coluna, valor).

        Existe por causa da cota: a API do Sheets permite 60 escritas por
        minuto por usuário, e a coluna de observação toca uma célula por
        titular. Com 26 titulares, uma chamada por célula gastaria metade da
        cota numa execução que não mudou quase nada.
        """
        ...

    def colorir_celulas(
        self, aba: str, celulas: list[tuple[int, str, str | None]]
    ) -> None:
        """Pinta o fundo das células. Cada item é (linha, coluna, nível).

        `nível` é uma chave de CORES_AVISO, ou None para limpar. Quem chama
        fala em gravidade, não em cor: a paleta é decisão desta camada.

        Fonte sem suporte a formatação pode não fazer nada. O texto do aviso
        já está na célula; a cor é reforço, não o recado.
        """
        ...

    # Escrever aqui é seguro? Só quem responde True recebe carimbo automático
    # de uid. O openpyxl descarta validação de dados ao salvar, então a fonte
    # local não pode escrever sem estragar as listas suspensas da planilha.
    escrita_segura: bool

    def descrever(self) -> str:
        """Frase curta identificando a origem, para aparecer no relatório.

        Sem isso, uma execução lendo do arquivo local e outra lendo do Sheets
        produzem saídas idênticas — e quem está conferindo uma migração de
        fonte não tem como saber se ela realmente aconteceu.
        """
        ...


# ---------------------------------------------------------------------------
# Produção — Google Sheets
# ---------------------------------------------------------------------------

class FonteGoogleSheets:
    """Lê e escreve a planilha hospedada no Google Sheets.

    Autentica por service account: uma conta de máquina, sem pessoa por trás.
    A planilha precisa ser compartilhada com o e-mail dessa conta, como se
    fosse mais um colaborador.

    Escopo `spreadsheets` (leitura e escrita). Somente leitura NÃO basta: o
    sync carimba o uid_royal de volta, e é isso que impede processo duplicado.

    Diferente do openpyxl, escrever por aqui altera a célula sem reescrever o
    arquivo — validação de dados, formatação condicional e fórmulas ficam
    intactas. Por isso o carimbo é automático nesta fonte.
    """

    ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets"]

    # A API altera a célula sem reescrever o arquivo: validação de dados,
    # formatação condicional e fórmulas ficam intactas.
    escrita_segura = True

    def __init__(self, credenciais_json: str, planilha_id: str):
        self._credenciais_json = credenciais_json
        self.planilha_id = planilha_id
        self._planilha = None

    def _abrir(self):
        if self._planilha is not None:
            return self._planilha

        import json

        import gspread
        from google.oauth2.service_account import Credentials

        try:
            info = json.loads(self._credenciais_json)
        except json.JSONDecodeError as e:
            raise FonteError(
                "GOOGLE_CREDENTIALS_JSON não é um JSON válido. Cole o conteúdo "
                "inteiro do arquivo de chave da service account, entre aspas "
                f"simples, numa linha só. Detalhe: {e}"
            ) from e

        try:
            cred = Credentials.from_service_account_info(info, scopes=self.ESCOPOS)
            cliente = gspread.authorize(cred)
            self._planilha = cliente.open_by_key(self.planilha_id)
        except Exception as e:
            raise FonteError(
                f"Não consegui abrir a planilha {self.planilha_id!r}.\n"
                f"Confira se ela foi compartilhada com o e-mail da service "
                f"account ({info.get('client_email', '?')}) como Editor.\n"
                f"Detalhe: {e}"
            ) from e

        return self._planilha

    def ler_aba(self, nome: str) -> list[list[str]]:
        import gspread

        planilha = self._abrir()
        try:
            aba = planilha.worksheet(nome)
        except gspread.WorksheetNotFound as e:
            disponiveis = ", ".join(w.title for w in planilha.worksheets())
            raise FonteError(
                f"Aba {nome!r} não existe na planilha. Abas disponíveis: {disponiveis}"
            ) from e

        # UNFORMATTED_VALUE de propósito: com formatação, uma data volta como
        # aparece na tela, e "01/06/2026" vira dia 1 de junho ou 6 de janeiro
        # conforme o locale da planilha. Alguém trocar esse ajuste inverteria
        # todas as datas em silêncio.
        #
        # Sem formatação, data vem como número de série do Sheets, que não
        # depende de idioma. Quem converte é planilha.normalizar_data.
        bruto = aba.get_all_values(value_render_option="UNFORMATTED_VALUE")
        return [["" if c is None else str(c).strip() for c in linha] for linha in bruto]

    def escrever_celula(self, aba: str, linha: int, coluna: str, valor: str) -> None:
        planilha = self._abrir()
        planilha.worksheet(aba).update_acell(f"{coluna}{linha}", valor)

    def escrever_celulas(
        self, aba: str, celulas: list[tuple[int, str, str]]
    ) -> None:
        if not celulas:
            return
        planilha = self._abrir()
        # value_input_option RAW: o texto vai para a célula como está. Sem
        # isso o Sheets interpreta o conteúdo, e uma observação começando com
        # "=" ou "-" viraria fórmula ou número negativo.
        planilha.worksheet(aba).batch_update(
            [{"range": f"{col}{lin}", "values": [[valor]]}
             for lin, col, valor in celulas],
            value_input_option="RAW",
        )

    def colorir_celulas(
        self, aba: str, celulas: list[tuple[int, str, str | None]]
    ) -> None:
        if not celulas:
            return
        planilha = self._abrir()
        planilha.worksheet(aba).batch_format([
            {
                "range": f"{col}{lin}",
                "format": {
                    "backgroundColor": CORES_AVISO.get(nivel or "", COR_LIMPA),
                    # Quebra de linha: o aviso é uma frase, e sem isto o texto
                    # vaza por cima das colunas vizinhas ou é cortado no meio.
                    "wrapStrategy": "WRAP",
                },
            }
            for lin, col, nivel in celulas
        ])

    def descrever(self) -> str:
        return f"Google Sheets ({self.planilha_id[:6]}...{self.planilha_id[-4:]})"


# ---------------------------------------------------------------------------
# Desenvolvimento — arquivo local
# ---------------------------------------------------------------------------

class FonteXlsxLocal:
    """Lê o .xlsx do disco.

    Serve para desenvolvimento e para rodar sem rede. NÃO serve para produção:
    exige alguém rodando o script na própria máquina, e o arquivo fica travado
    enquanto estiver aberto no Excel.

    A escrita existe mas o `carga_inicial.py` evita usá-la: o openpyxl descarta
    validação de dados ao salvar, o que apagaria as listas suspensas de status
    vindas da aba Listas. Com esta fonte, o carimbo do uid sai por
    uids_para_colar.txt, para colagem manual.
    """

    # Salvar pelo openpyxl descartaria as listas suspensas de status vindas da
    # aba Listas, e status digitado livre quebra a normalização do sync.
    escrita_segura = False

    def __init__(self, caminho: str):
        self.caminho = caminho

    def ler_aba(self, nome: str) -> list[list[str]]:
        import openpyxl

        wb = openpyxl.load_workbook(self.caminho, data_only=True, read_only=True)
        if nome not in wb.sheetnames:
            disponiveis = ", ".join(wb.sheetnames)
            wb.close()
            raise FonteError(
                f"Aba {nome!r} não existe na planilha. Abas disponíveis: {disponiveis}"
            )

        ws = wb[nome]
        linhas = [[_texto(c) for c in linha] for linha in ws.iter_rows(values_only=True)]
        wb.close()
        return linhas

    def escrever_celula(self, aba: str, linha: int, coluna: str, valor: str) -> None:
        self.escrever_celulas(aba, [(linha, coluna, valor)])

    def escrever_celulas(
        self, aba: str, celulas: list[tuple[int, str, str]]
    ) -> None:
        if not celulas:
            return

        import openpyxl

        # Um load/save para o lote inteiro. Além da lentidão, cada save é uma
        # chance de perder a validação de dados — ver o aviso da classe.
        wb = openpyxl.load_workbook(self.caminho)
        for linha, coluna, valor in celulas:
            wb[aba][f"{coluna}{linha}"] = valor
        wb.save(self.caminho)
        wb.close()

    def colorir_celulas(
        self, aba: str, celulas: list[tuple[int, str, str | None]]
    ) -> None:
        """Não faz nada nesta fonte, de propósito.

        Pintar exigiria mais um load/save do openpyxl, e cada save descarta a
        validação de dados da planilha — ver o aviso da classe. Como esta
        fonte é só de desenvolvimento e nem recebe aviso automático (o sync
        exige `escrita_segura`), o custo não se justifica. O texto do aviso
        continua indo para o terminal.
        """
        return

    def descrever(self) -> str:
        return f"arquivo local ({self.caminho})"


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

def _texto(valor) -> str:
    """Normaliza uma célula do openpyxl para texto. Datas viram ISO."""
    import datetime as _dt

    if valor is None:
        return ""
    if isinstance(valor, _dt.datetime):
        return valor.date().isoformat()
    if isinstance(valor, _dt.date):
        return valor.isoformat()
    return str(valor).strip()


def criar_fonte() -> FonteDePlanilha:
    """Monta a fonte indicada por FONTE_PLANILHA no .env."""
    tipo = os.environ.get("FONTE_PLANILHA", "google_sheets").strip()

    if tipo == "google_sheets":
        planilha_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if not planilha_id:
            raise FonteError(
                "GOOGLE_SHEET_ID não definido. É o trecho da URL da planilha "
                "entre /d/ e /edit."
            )

        credenciais = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
        if not credenciais:
            caminho = os.environ.get("GOOGLE_CREDENTIALS_FILE", "").strip()
            if caminho:
                if not os.path.exists(caminho):
                    raise FonteError(f"Arquivo de credenciais não encontrado: {caminho!r}")
                with open(caminho, encoding="utf-8") as f:
                    credenciais = f.read()

        if not credenciais:
            raise FonteError(
                "Faltam as credenciais do Google. Defina GOOGLE_CREDENTIALS_JSON "
                "com o conteúdo da chave da service account, ou "
                "GOOGLE_CREDENTIALS_FILE com o caminho do arquivo.\n"
                "No GitHub Actions use GOOGLE_CREDENTIALS_JSON: lá não existe "
                "arquivo para apontar."
            )

        return FonteGoogleSheets(credenciais, planilha_id)

    if tipo == "xlsx_local":
        caminho = os.environ.get("CAMINHO_PLANILHA", "").strip()
        if not caminho:
            raise FonteError("CAMINHO_PLANILHA não definido no .env")
        if not os.path.exists(caminho):
            raise FonteError(f"Planilha não encontrada em {caminho!r}")
        return FonteXlsxLocal(caminho)

    raise FonteError(
        f"FONTE_PLANILHA={tipo!r} não reconhecida. Use google_sheets ou xlsx_local."
    )
