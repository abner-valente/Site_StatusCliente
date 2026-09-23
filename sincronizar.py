#!/usr/bin/env python
"""Sincronização recorrente: planilha -> banco.

    python sincronizar.py             # simula, não grava nada
    python sincronizar.py --aplicar   # grava
    python sincronizar.py --aplicar --forcar   # ignora a guarda de sanidade

Simula por padrão mesmo em produção: o agendamento no GitHub Actions passa
--aplicar explicitamente. Assim uma execução manual distraída não escreve.

As quatro defesas
-----------------
1. IDENTIDADE ESTÁVEL. O casamento é pelo uid_royal, não pela posição da linha.
   Entre duas versões da planilha, com seis dias de diferença, um cliente mudou
   de ID e outro ID trocou de dono.

2. CHAVE PARA DESLIGAR. SYNC_HABILITADO diferente de "1" impede a execução.
   Reestruturação de planilha é evento planejado: desliga antes, reconcilia
   depois, religa.

3. GUARDA DE SANIDADE. Mudança em massa, processo sumido, cabeçalho diferente
   ou status desconhecido param a execução em vez de gravar. Uma reestruturação
   anterior produziu cinco eventos que pareciam fatos de negócio e não eram;
   esta guarda os teria barrado.

4. NUNCA APAGAR. Processo ausente da planilha vira ativo=false com alerta.

E a regra que sustenta tudo
---------------------------
Histórico só é gravado QUANDO O STATUS MUDA. Gravando a cada execução, 13
processos ativos gerariam cerca de 15 mil linhas por dia e estourariam os
500 MB do plano free em poucos meses. Gravando só na mudança, o mesmo volume
leva décadas.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from sync import banco, fontes, planilha


class SyncAbortado(RuntimeError):
    """A guarda de sanidade barrou a execução. Nada foi gravado."""


def principal() -> int:
    ap = argparse.ArgumentParser(description="Sincroniza a planilha com o banco.")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava; sem esta flag apenas simula")
    ap.add_argument("--forcar", action="store_true",
                    help="ignora a guarda de sanidade (use após conferir o plano)")
    args = ap.parse_args()

    load_dotenv()

    modo = "APLICANDO" if args.aplicar else "SIMULAÇÃO (nada será gravado)"
    print(f"=== Sincronização — {modo} ===")
    print(f"    {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

    # ---- defesa 2: chave para desligar --------------------------------
    if os.environ.get("SYNC_HABILITADO", "1").strip() != "1":
        print("SYNC DESLIGADO por SYNC_HABILITADO no ambiente.")
        print("É o modo de reestruturação da planilha. Religue quando terminar.")
        return 0

    try:
        fonte = fontes.criar_fonte()
        sb = banco.criar_cliente()
        catalogo = banco.ler_catalogo(sb)
        ids_etapa = banco.id_das_etapas(catalogo)
    except (fontes.FonteError, banco.BancoError) as e:
        print(f"ERRO DE CONFIGURAÇÃO\n{e}", file=sys.stderr)
        return 1

    # ---- leitura ------------------------------------------------------
    # Erro de cabeçalho ou status desconhecido levanta PlanilhaError e para
    # aqui, antes de qualquer escrita. É parte da defesa 3.
    linhas_planilha: list[planilha.LinhaProcesso] = []
    try:
        for aba, modalidade in planilha.ABAS_FLUXO.items():
            linhas_planilha += planilha.ler_fluxo(fonte, aba, modalidade, catalogo[modalidade])
    except planilha.PlanilhaError as e:
        print(f"PLANILHA FORA DO FORMATO — nada foi gravado\n{e}", file=sys.stderr)
        return 1

    no_banco = banco.processos_por_uid(sb)
    etapas_banco = banco.etapas_atuais(sb)

    # ---- plano --------------------------------------------------------
    sem_uid, desconhecidos = [], []
    mudancas_status: list[dict] = []
    processos_tocados: set[str] = set()
    dados_alterados: list[tuple[str, dict]] = []
    vistos_uid: set[str] = set()

    for p in linhas_planilha:
        if not p.uid:
            sem_uid.append(p)
            continue

        vistos_uid.add(p.uid)
        proc = no_banco.get(p.uid)
        if proc is None:
            desconhecidos.append(p)
            continue

        campos = {}
        if (proc.get("imovel") or "") != p.imovel:
            campos["imovel"] = p.imovel
        if (proc.get("corretor") or "") != (p.corretor or ""):
            campos["corretor"] = p.corretor or None
        if (proc.get("data_assinatura") or None) != (p.data_assinatura or None):
            campos["data_assinatura"] = p.data_assinatura
        if not proc.get("ativo"):
            campos["ativo"] = True          # reapareceu na planilha
        if campos:
            dados_alterados.append((proc["id"], campos))

        for codigo, novo in p.etapas.items():
            etapa_id = ids_etapa[(p.modalidade, codigo)]
            atual = etapas_banco.get((proc["id"], etapa_id))
            antigo = atual["status"] if atual else None
            if antigo != novo:
                mudancas_status.append({
                    "processo_id": proc["id"],
                    "etapa_id": etapa_id,
                    "modalidade": p.modalidade,
                    "codigo": codigo,
                    "de": antigo,
                    "para": novo,
                    "imovel": p.imovel,
                })
                processos_tocados.add(proc["id"])

    sumidos = [proc for uid, proc in no_banco.items()
               if uid not in vistos_uid and proc.get("ativo")]

    # ---- relatório do plano -------------------------------------------
    ativos = sum(1 for p in no_banco.values() if p.get("ativo"))
    print(f"planilha : {len(linhas_planilha)} processo(s)")
    print(f"banco    : {len(no_banco)} processo(s), {ativos} ativo(s)\n")

    if mudancas_status:
        print(f"MUDANÇAS DE STATUS ({len(mudancas_status)}):")
        for m in mudancas_status:
            print(f"  {m['imovel'][:34]:34} {m['codigo']:22} "
                  f"{str(m['de']):14} -> {m['para']}")
        print()
    else:
        print("Nenhuma mudança de status.\n")

    for pid, campos in dados_alterados:
        print(f"  dados alterados em {pid[:8]}: {', '.join(campos)}")
    for p in sem_uid:
        print(f"  SEM UID: {p.aba} linha {p.numero_linha} ({p.cliente_bruto})")
    for p in desconhecidos:
        print(f"  UID DESCONHECIDO: {p.uid} ({p.cliente_bruto})")
    for proc in sumidos:
        print(f"  SUMIU DA PLANILHA: {proc['imovel']} (uid {proc['uid_planilha']})")

    # ---- defesa 3: guarda de sanidade ---------------------------------
    try:
        _guarda(ativos, processos_tocados, sumidos, sem_uid, desconhecidos, args.forcar)
    except SyncAbortado as e:
        print(f"\n>>> SINCRONIZAÇÃO ABORTADA <<<\n{e}", file=sys.stderr)
        print("\nNada foi gravado. Confira o plano acima. Se a mudança for "
              "legítima, rode de novo com --forcar.", file=sys.stderr)
        return 2

    if not args.aplicar:
        print("\nNada foi gravado. Para aplicar:  python sincronizar.py --aplicar")
        return 0

    # ---- escrita ------------------------------------------------------
    for pid, campos in dados_alterados:
        sb.table("processos").update(campos).eq("id", pid).execute()

    agora = datetime.now(timezone.utc).isoformat()
    etapas_reg, hist_reg = [], []
    for m in mudancas_status:
        etapas_reg.append({
            "processo_id": m["processo_id"],
            "etapa_id": m["etapa_id"],
            "modalidade": m["modalidade"],
            "status": m["para"],
            "desde": agora,
        })
        hist_reg.append({
            "processo_id": m["processo_id"],
            "etapa_id": m["etapa_id"],
            "status_de": m["de"],
            "status_para": m["para"],
            "origem": "sync",
        })

    banco.gravar_etapas(sb, etapas_reg)
    banco.gravar_historico(sb, hist_reg)

    for proc in sumidos:
        banco.desativar_processo(sb, proc["id"])

    banco.marcar_visto(sb, [no_banco[u]["id"] for u in vistos_uid if u in no_banco])

    # ---- titulares ----------------------------------------------------
    titulares = planilha.ler_titulares(fonte)
    if titulares:
        uid_para_id = {u: p["id"] for u, p in no_banco.items()}
        por_chave: dict[tuple[str, str], dict] = {}
        for t in titulares:
            pid = uid_para_id.get(t.uid_processo)
            if pid is None:
                continue
            chave = (pid, t.email)
            anterior = por_chave.get(chave)
            if anterior is None:
                por_chave[chave] = {"processo_id": pid, "nome": t.nome, "email": t.email}
            elif t.nome not in anterior["nome"].split(" / "):
                anterior["nome"] = f"{anterior['nome']} / {t.nome}"
        banco.gravar_titulares(sb, list(por_chave.values()))

    ligados = banco.vincular_titulares_pendentes(sb)

    print(f"\n=== Aplicado ===")
    print(f"etapas atualizadas   : {len(etapas_reg)}")
    print(f"linhas de histórico  : {len(hist_reg)}")
    print(f"processos desativados: {len(sumidos)}")
    print(f"titulares ligados    : {ligados}")
    return 0


def _guarda(ativos, tocados, sumidos, sem_uid, desconhecidos, forcar):
    """Defesa 3. Levanta SyncAbortado quando a mudança tem cara de acidente."""
    motivos = []

    if desconhecidos:
        motivos.append(
            f"{len(desconhecidos)} linha(s) com uid que o banco não conhece. "
            "Alguém digitou ou colou na coluna uid_royal.")

    if sumidos:
        motivos.append(
            f"{len(sumidos)} processo(s) sumiram da planilha. Pode ser "
            "reestruturação, não cancelamento — por isso o sync não desativa "
            "sozinho.")

    if sem_uid:
        motivos.append(
            f"{len(sem_uid)} linha(s) sem uid. Rode carga_inicial.py e cole a "
            "coluna antes de sincronizar, senão viram processos duplicados.")

    limite = float(os.environ.get("LIMITE_MUDANCA_EM_MASSA", "0.30"))
    if ativos and len(tocados) / ativos > limite:
        pct = len(tocados) / ativos * 100
        motivos.append(
            f"{len(tocados)} de {ativos} processos mudaram de status "
            f"({pct:.0f}%), acima do limite de {limite*100:.0f}%.")

    if not motivos:
        return

    texto = "\n".join(f"  - {m}" for m in motivos)
    if forcar:
        print(f"\nGuarda de sanidade acionada, ignorada por --forcar:\n{texto}\n")
        return
    raise SyncAbortado(texto)


if __name__ == "__main__":
    sys.exit(principal())
