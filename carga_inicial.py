#!/usr/bin/env python
"""Carga inicial: leva a planilha para o banco pela primeira vez.

    python carga_inicial.py             # simula, não grava nada
    python carga_inicial.py --aplicar   # grava de verdade

Simula por padrão de propósito. A primeira execução real carimba a coluna
uid_royal na planilha e cria os processos no banco — vale olhar o plano antes.

Ordem de escrita, que NÃO deve ser invertida
--------------------------------------------
1. carimba o uid na planilha
2. grava no banco

Se o passo 2 falhar, a planilha já tem o uid e a próxima execução reaproveita.
Na ordem inversa, uma falha no carimbo faria a execução seguinte gerar uids
novos e criar processos duplicados.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from dotenv import load_dotenv

from sync import banco, fontes, planilha


def principal() -> int:
    ap = argparse.ArgumentParser(description="Carga inicial da planilha para o Supabase.")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava de verdade; sem esta flag apenas simula")
    args = ap.parse_args()

    load_dotenv()

    modo = "APLICANDO" if args.aplicar else "SIMULAÇÃO (nada será gravado)"
    print(f"=== Carga inicial — {modo} ===\n")

    try:
        fonte = fontes.criar_fonte()
        sb = banco.criar_cliente()
        catalogo = banco.ler_catalogo(sb)
        ids_etapa = banco.id_das_etapas(catalogo)
    except (fontes.FonteError, banco.BancoError) as e:
        print(f"ERRO DE CONFIGURAÇÃO\n{e}", file=sys.stderr)
        return 1

    existentes = banco.processos_por_uid(sb)
    if existentes:
        print(f"Aviso: o banco já tem {len(existentes)} processo(s). "
              f"Linhas com uid conhecido serão atualizadas, não duplicadas.\n")

    total_novos = 0
    total_etapas = 0

    for aba, modalidade in planilha.ABAS_FLUXO.items():
        print(f"--- {aba} ({modalidade}) ---")

        try:
            linhas = planilha.ler_fluxo(fonte, aba, modalidade, catalogo[modalidade])
        except planilha.PlanilhaError as e:
            print(f"ERRO NA PLANILHA\n{e}", file=sys.stderr)
            return 1

        idx_uid, uid_existe = planilha.indice_coluna_uid(fonte, aba)
        col_uid = planilha.letra_coluna(idx_uid)
        linha_cab = planilha.linha_cabecalho_numero(fonte, aba)

        if not uid_existe:
            print(f"  coluna {planilha.COLUNA_UID} ausente; será criada em {col_uid}{linha_cab}")
            if args.aplicar:
                fonte.escrever_celula(aba, linha_cab, col_uid, planilha.COLUNA_UID)

        for p in linhas:
            novo = p.uid is None
            if novo:
                p.uid = str(uuid.uuid4())

            concluidas = sum(1 for s in p.etapas.values() if s == "concluido")
            marca = "novo" if novo else "existente"
            print(f"  [{marca:9}] {p.cliente_bruto:22} {p.imovel:34} "
                  f"{concluidas}/{len(p.etapas)} concluídas")

            if not args.aplicar:
                total_novos += 1 if novo else 0
                total_etapas += len(p.etapas)
                continue

            # 1. carimbo na planilha, antes do banco
            if novo:
                fonte.escrever_celula(aba, p.numero_linha, col_uid, p.uid)

            # 2. banco
            proc = banco.gravar_processo(sb, {
                "uid_planilha": p.uid,
                "modalidade": p.modalidade,
                "imovel": p.imovel,
                "corretor": p.corretor or None,
                "data_assinatura": p.data_assinatura,
                "ativo": True,
            })

            etapas_reg, hist_reg = [], []
            for codigo, status in p.etapas.items():
                etapa_id = ids_etapa[(p.modalidade, codigo)]
                etapas_reg.append({
                    "processo_id": proc["id"],
                    "etapa_id": etapa_id,
                    "modalidade": p.modalidade,
                    "status": status,
                })
                # Na carga inicial o histórico registra só o ponto de partida.
                # A partir daqui, o sync grava apenas quando o status MUDA.
                hist_reg.append({
                    "processo_id": proc["id"],
                    "etapa_id": etapa_id,
                    "status_de": None,
                    "status_para": status,
                    "origem": "carga_inicial",
                })

            banco.gravar_etapas(sb, etapas_reg)
            banco.gravar_historico(sb, hist_reg)

            total_novos += 1 if novo else 0
            total_etapas += len(etapas_reg)

        print()

    # --- titulares -------------------------------------------------------
    titulares = planilha.ler_titulares(fonte)
    if not titulares:
        print(f"--- {planilha.ABA_TITULARES} ---")
        print("  aba ausente ou vazia — nenhum acesso de cliente será criado.")
        print("  Sem ela ninguém consegue logar: é o item bloqueante da fase 1.\n")
    else:
        print(f"--- {planilha.ABA_TITULARES} ---")
        print(f"  {len(titulares)} titular(es) na planilha")
        if args.aplicar:
            uid_para_id = {
                linha["uid_planilha"]: linha["id"]
                for linha in banco.processos_por_uid(sb).values()
            }
            registros, orfaos = [], []
            for t in titulares:
                pid = uid_para_id.get(t.uid_processo)
                if pid is None:
                    orfaos.append(t)
                    continue
                registros.append({"processo_id": pid, "nome": t.nome, "email": t.email})

            banco.gravar_titulares(sb, registros)
            ligados = banco.vincular_titulares_pendentes(sb)
            print(f"  {len(registros)} gravado(s), {ligados} ligado(s) a contas existentes")
            for t in orfaos:
                print(f"  AVISO: uid_processo {t.uid_processo!r} de {t.email} "
                      f"não existe no banco — titular ignorado")
        print()

    print("=== Resumo ===")
    print(f"processos novos : {total_novos}")
    print(f"etapas gravadas : {total_etapas}")
    if not args.aplicar:
        print("\nNada foi gravado. Para aplicar:  python carga_inicial.py --aplicar")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
