"""Acesso ao Supabase pela API REST (HTTPS).

Por que REST e não conexão Postgres direta: a rede da Royal bloqueia saída nas
portas 5432 e 6543. A API REST trafega na 443, funciona do escritório e é o
mesmo caminho que o GitHub Actions vai usar na fase 3 — testar agora é testar
o que vai para produção.

Este módulo usa a service_role key, que ignora RLS e GRANT. Ela nunca pode
chegar ao navegador.
"""

from __future__ import annotations

import os
from typing import Any


class BancoError(RuntimeError):
    """Falha de comunicação ou de contrato com o Supabase."""


def criar_cliente():
    """Monta o cliente do Supabase a partir do .env."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "").strip()
    chave = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not chave:
        raise BancoError(
            "SUPABASE_URL e/ou SUPABASE_SERVICE_ROLE_KEY não definidos.\n"
            "Copie .env.example para .env e preencha com os valores de\n"
            "Settings -> API no painel do Supabase."
        )
    if "SEU_PROJECT_REF" in url:
        raise BancoError("SUPABASE_URL ainda está com o valor de exemplo do .env.example.")

    return create_client(url, chave)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def ler_catalogo(sb) -> dict[str, list[dict]]:
    """Etapas por modalidade, em ordem.

    O banco é a fonte do mapeamento planilha -> etapa. O script não tem lista
    de etapas embutida de propósito: duas fontes de verdade divergiriam.
    """
    r = sb.table("etapas_catalogo").select(
        "id, modalidade, ordem, codigo, rotulo_interno, rotulo_publico"
    ).order("modalidade").order("ordem").execute()

    if not r.data:
        raise BancoError(
            "etapas_catalogo está vazio. Aplique a migração "
            "20260923000200_catalogo_etapas.sql antes de rodar a carga."
        )

    catalogo: dict[str, list[dict]] = {}
    for linha in r.data:
        catalogo.setdefault(linha["modalidade"], []).append(linha)

    esperado = {"avista": 10, "financiado": 9}
    for modalidade, qtd in esperado.items():
        achado = len(catalogo.get(modalidade, []))
        if achado != qtd:
            raise BancoError(
                f"Catálogo de {modalidade} tem {achado} etapas, esperado {qtd}."
            )

    return catalogo


def id_das_etapas(catalogo: dict[str, list[dict]]) -> dict[tuple[str, str], int]:
    """(modalidade, codigo) -> id da etapa."""
    return {
        (etapa["modalidade"], etapa["codigo"]): etapa["id"]
        for etapas in catalogo.values()
        for etapa in etapas
    }


# ---------------------------------------------------------------------------
# Processos
# ---------------------------------------------------------------------------

def processos_por_uid(sb) -> dict[str, dict]:
    """Tudo que já está no banco, indexado pelo carimbo da planilha."""
    r = sb.table("processos").select(
        "id, uid_planilha, modalidade, imovel, corretor, data_assinatura, ativo"
    ).execute()
    return {linha["uid_planilha"]: linha for linha in (r.data or [])}


def gravar_processo(sb, dados: dict[str, Any]) -> dict:
    """Cria ou atualiza um processo pelo uid_planilha."""
    r = sb.table("processos").upsert(
        dados, on_conflict="uid_planilha"
    ).execute()
    if not r.data:
        raise BancoError(f"Upsert de processo não retornou dados: {dados.get('uid_planilha')}")
    return r.data[0]


def gravar_etapas(sb, registros: list[dict]) -> None:
    """Estado atual das etapas. Chave composta (processo_id, etapa_id)."""
    if not registros:
        return
    sb.table("processo_etapas").upsert(
        registros, on_conflict="processo_id,etapa_id"
    ).execute()


def gravar_historico(sb, registros: list[dict]) -> None:
    """Histórico é append-only: só insert, nunca upsert.

    O banco recusa UPDATE e DELETE nesta tabela por gatilho, inclusive para a
    service_role. Se este código um dia tentar atualizar, vai falhar alto — que
    é o comportamento desejado.
    """
    if not registros:
        return
    sb.table("processo_etapas_historico").insert(registros).execute()


# ---------------------------------------------------------------------------
# Titulares
# ---------------------------------------------------------------------------

def gravar_titulares(sb, registros: list[dict]) -> None:
    if not registros:
        return
    sb.table("titulares").upsert(
        registros, on_conflict="processo_id,email"
    ).execute()


def vincular_titulares_pendentes(sb) -> int:
    """Liga titulares a contas que já existiam antes do e-mail entrar na planilha.

    Cobre o caso que o gatilho em auth.users não pega: usuário criado primeiro,
    e-mail cadastrado depois. Deve rodar ao fim de cada sync.
    """
    r = sb.rpc("vincular_titulares_pendentes").execute()
    return r.data if isinstance(r.data, int) else 0
