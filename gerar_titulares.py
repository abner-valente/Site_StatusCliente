#!/usr/bin/env python
"""Gera a aba Titulares para colar na planilha.

    python gerar_titulares.py

Lê os processos da planilha (já carimbados com uid_royal), separa os nomes dos
casais e escreve `titulares_para_colar.csv` com a coluna `email` vazia, para o
time da Royal preencher.

Processos que já têm titular no banco ficam de fora, então dá para rodar de
novo quando entrarem processos novos.

Por que aqui a separação de nomes é aceitável
---------------------------------------------
O sync NUNCA separa "Davi / Jeane" sozinho: um erro daria a alguém acesso ao
processo de outra pessoa, sem ninguém olhar. Aqui é diferente — a saída é uma
sugestão que uma pessoa revisa antes de virar acesso. O custo de errar é uma
correção na planilha, não um vazamento.

Por isso a coluna `cliente_planilha` vem junto: quem preenche os e-mails vê o
texto original ao lado do nome separado e corrige o que estiver errado.
"""

from __future__ import annotations

import csv
import re
import sys

from dotenv import load_dotenv

from sync import banco, fontes, planilha

ARQUIVO_SAIDA = "titulares_para_colar.csv"

# Separadores observados no campo Cliente: "/", " / ", "/ " e " e ".
SEPARADORES = re.compile(r"\s*/\s*|\s+e\s+", re.IGNORECASE)


def separar_nomes(bruto: str) -> list[str]:
    partes = [p.strip() for p in SEPARADORES.split(bruto or "")]
    return [p for p in partes if p] or [bruto.strip()]


def principal() -> int:
    load_dotenv()

    try:
        fonte = fontes.criar_fonte()
        sb = banco.criar_cliente()
        catalogo = banco.ler_catalogo(sb)
    except (fontes.FonteError, banco.BancoError) as e:
        print(f"ERRO DE CONFIGURAÇÃO\n{e}", file=sys.stderr)
        return 1

    processos = banco.processos_por_uid(sb)
    ja_tem = banco.titulares_por_processo(sb)

    linhas_csv: list[dict] = []
    sem_uid: list[str] = []
    separados: list[tuple[str, list[str]]] = []
    pulados = 0

    for aba, modalidade in planilha.ABAS_FLUXO.items():
        try:
            linhas = planilha.ler_fluxo(fonte, aba, modalidade, catalogo[modalidade])
        except planilha.PlanilhaError as e:
            print(f"ERRO NA PLANILHA\n{e}", file=sys.stderr)
            return 1

        for p in linhas:
            if not p.uid:
                sem_uid.append(f"{aba} linha {p.numero_linha}: {p.cliente_bruto}")
                continue

            proc = processos.get(p.uid)
            if proc is None:
                sem_uid.append(
                    f"{aba} linha {p.numero_linha}: {p.cliente_bruto} "
                    f"(uid {p.uid} não existe no banco)"
                )
                continue

            if ja_tem.get(proc["id"]):
                pulados += 1
                continue

            nomes = separar_nomes(p.cliente_bruto)
            if len(nomes) > 1:
                separados.append((p.cliente_bruto, nomes))

            for nome in nomes:
                linhas_csv.append({
                    "uid_processo": p.uid,
                    "nome": nome,
                    "email": "",
                    "imovel": p.imovel,
                    "cliente_planilha": p.cliente_bruto,
                })

    if sem_uid:
        print("ATENÇÃO — linhas sem uid válido, ficaram de fora:")
        for item in sem_uid:
            print(f"  {item}")
        print("  Rode carga_inicial.py e cole a coluna uid_royal antes.\n")

    if pulados:
        print(f"{pulados} processo(s) já têm titular no banco e foram ignorados.\n")

    if not linhas_csv:
        print("Nada a gerar.")
        return 0

    # utf-8-sig: o Excel em português só reconhece os acentos com BOM.
    # delimitador ';': é o separador de lista padrão do Excel pt-BR.
    with open(ARQUIVO_SAIDA, "w", encoding="utf-8-sig", newline="") as f:
        campos = ["uid_processo", "nome", "email", "imovel", "cliente_planilha"]
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas_csv)

    print(f"Gerado: {ARQUIVO_SAIDA}")
    print(f"  {len(linhas_csv)} linha(s) de titular, "
          f"{len({l['uid_processo'] for l in linhas_csv})} processo(s)\n")

    if separados:
        print("CONFERIR — nomes separados automaticamente:")
        for bruto, nomes in separados:
            print(f"  {bruto!r} -> {', '.join(repr(n) for n in nomes)}")
        print()

    print("Próximos passos:")
    print(f"  1. abra {ARQUIVO_SAIDA} no Excel")
    print("  2. confira os nomes separados e preencha a coluna email")
    print("  3. copie tudo e cole numa aba nova chamada 'Titulares', na célula A1")
    print("  4. rode carga_inicial.py --aplicar para levar ao banco")
    print()
    print("O sync lê as colunas uid_processo, nome e email pelo nome do")
    print("cabeçalho. As colunas imovel e cliente_planilha existem só para")
    print("ajudar quem preenche, e são ignoradas.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
