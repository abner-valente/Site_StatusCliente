#!/usr/bin/env python
"""Carga inicial: leva a planilha para o banco pela primeira vez.

    python carga_inicial.py             # simula, não grava nada
    python carga_inicial.py --aplicar   # grava no banco

Simula por padrão de propósito: vale olhar o plano antes da primeira execução
real.

Por que o script NÃO escreve na planilha local
----------------------------------------------
O openpyxl não preserva validação de dados ao salvar — ele avisa isso ao abrir
o arquivo. Carimbar o uid_royal por ali destruiria as listas suspensas de
status que vêm da aba `Listas`. O time passaria a digitar status livre e a
normalização do sync quebraria.

Então, com fonte local, o script grava no banco e gera `uids_para_colar.txt`
para você colar a coluna no Excel, que preserva tudo.

Na fase 3 isso deixa de existir: o Graph API edita a célula sem reescrever o
arquivo, e o carimbo volta a ser automático.

Ordem de escrita, que NÃO deve ser invertida
--------------------------------------------
O uid precisa chegar à planilha. Enquanto ele não estiver lá, uma nova execução
não reconhece as linhas e criaria processos duplicados. Por isso o script
insiste no aviso ao final: colar a coluna faz parte da carga, não é opcional.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from dotenv import load_dotenv

from sync import banco, fontes, planilha

ARQUIVO_UIDS = "uids_para_colar.txt"


def principal() -> int:
    ap = argparse.ArgumentParser(description="Carga inicial da planilha para o Supabase.")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava no banco; sem esta flag apenas simula")
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

    # Fonte local não aceita escrita segura; ver docstring do módulo.
    fonte_local = isinstance(fonte, fontes.FonteXlsxLocal)

    existentes = banco.processos_por_uid(sb)
    if existentes:
        print(f"Aviso: o banco já tem {len(existentes)} processo(s). "
              f"Linhas com uid conhecido serão atualizadas, não duplicadas.\n")

    total_novos = 0
    total_etapas = 0
    blocos_uid: list[tuple[str, str, int, list[str], int]] = []

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
            print(f"  coluna {planilha.COLUNA_UID} ausente; lugar dela: {col_uid}{linha_cab}")

        uids_desta_aba: list[str] = []
        novos_nesta_aba = 0

        for p in linhas:
            novo = p.uid is None
            if novo:
                p.uid = str(uuid.uuid4())
                novos_nesta_aba += 1
            uids_desta_aba.append(p.uid)

            concluidas = sum(1 for s in p.etapas.values() if s == "concluido")
            marca = "novo" if novo else "existente"
            print(f"  [{marca:9}] {p.cliente_bruto:22} {p.imovel:34} "
                  f"{concluidas}/{len(p.etapas)} concluídas")

            if not args.aplicar:
                total_novos += 1 if novo else 0
                total_etapas += len(p.etapas)
                continue

            if not fonte_local and novo:
                fonte.escrever_celula(aba, p.numero_linha, col_uid, p.uid)

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
                # Ponto de partida do histórico, gravado UMA vez só, para
                # processos que esta execução acabou de criar.
                #
                # Histórico é append-only: rodar a carga de novo sobre um
                # processo existente duplicaria as linhas de partida, e não
                # há como desfazer sem desligar o gatilho. Daqui em diante
                # quem grava é o sync, e só quando o status MUDA.
                if novo:
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

        blocos_uid.append((aba, col_uid, linha_cab, uids_desta_aba, novos_nesta_aba))
        print()

    # --- titulares -------------------------------------------------------
    print(f"--- {planilha.ABA_TITULARES} ---")
    titulares = planilha.ler_titulares(fonte)
    if not titulares:
        print("  aba ausente ou vazia — nenhum acesso de cliente será criado.")
        print("  Sem ela ninguém consegue logar: é o item bloqueante da fase 1.")
    else:
        print(f"  {len(titulares)} titular(es) na planilha")
        if args.aplicar:
            uid_para_id = {
                linha["uid_planilha"]: linha["id"]
                for linha in banco.processos_por_uid(sb).values()
            }
            # Deduplica por (processo, e-mail) ANTES de mandar ao banco.
            #
            # O mesmo e-mail em processos diferentes é legítimo e continua
            # valendo: uma pessoa pode comprar mais de um imóvel. A restrição
            # do banco é unique (processo_id, email), por processo.
            #
            # O que não pode é o mesmo e-mail duas vezes no MESMO processo —
            # caso de um casal que compartilha uma caixa de entrada. Sem
            # deduplicar, o upsert tenta tocar a mesma linha duas vezes na
            # mesma instrução e o Postgres recusa com o código 21000.
            por_chave: dict[tuple[str, str], dict] = {}
            orfaos, fundidos = [], []

            for t in titulares:
                pid = uid_para_id.get(t.uid_processo)
                if pid is None:
                    orfaos.append(t)
                    continue

                chave = (pid, t.email)
                anterior = por_chave.get(chave)
                if anterior is None:
                    por_chave[chave] = {
                        "processo_id": pid, "nome": t.nome, "email": t.email,
                    }
                    continue

                # Mesmo acesso, duas pessoas: mantém os dois nomes no registro.
                if t.nome not in anterior["nome"].split(" / "):
                    anterior["nome"] = f"{anterior['nome']} / {t.nome}"
                fundidos.append((t.email, anterior["nome"]))

            registros = list(por_chave.values())

            banco.gravar_titulares(sb, registros)
            ligados = banco.vincular_titulares_pendentes(sb)

            print(f"  {len(registros)} gravado(s), {ligados} ligado(s) a contas existentes")

            for email, nome in fundidos:
                print(f"  fundido: {email} aparece mais de uma vez no mesmo "
                      f"processo — titular gravado como {nome!r}")

            emails = [r["email"] for r in registros]
            repetidos = {e for e in emails if emails.count(e) > 1}
            for e in sorted(repetidos):
                n = emails.count(e)
                print(f"  {e} é titular de {n} processos — vai ver os {n} ao logar")

            for t in orfaos:
                print(f"  AVISO: uid_processo {t.uid_processo!r} de {t.email} "
                      f"não existe no banco — titular ignorado")
    print()

    # --- arquivo de uids -------------------------------------------------
    # Só quando há linha nova sem carimbo. Um aviso que aparece em toda
    # execução vira ruído, e aí ninguém o lê na vez em que ele importa.
    pendentes = [b for b in blocos_uid if b[4] > 0]
    if args.aplicar and fonte_local and pendentes:
        _escrever_arquivo_uids(blocos_uid)

    print("=== Resumo ===")
    print(f"processos novos : {total_novos}")
    print(f"etapas gravadas : {total_etapas}")

    if not args.aplicar:
        print("\nNada foi gravado. Para aplicar:  python carga_inicial.py --aplicar")
    elif fonte_local and pendentes:
        novos = sum(b[4] for b in pendentes)
        print(f"\n>>> FALTA UM PASSO MANUAL <<<")
        print(f"{novos} processo(s) receberam uid novo, e a planilha ainda não o tem.")
        print(f"Enquanto a coluna não for preenchida, uma nova execução não")
        print(f"reconhece estas linhas e criaria processos duplicados.")
        print(f"\nAbra {ARQUIVO_UIDS} e cole a coluna inteira nas abas indicadas.")
    elif fonte_local:
        print("\nPlanilha e banco em sincronia: todas as linhas já têm uid.")

    return 0


def _escrever_arquivo_uids(blocos: list[tuple[str, str, int, list[str], int]]) -> None:
    """Gera o arquivo com as colunas de uid para colar no Excel.

    Colar preserva validação de dados, formatação condicional e fórmulas —
    coisas que o openpyxl descartaria ao salvar o arquivo.
    """
    linhas_saida: list[str] = [
        "COMO USAR",
        "=========",
        "Para cada bloco abaixo: copie as linhas indicadas (incluindo o",
        "cabeçalho uid_royal) e cole no Excel na célula indicada.",
        "",
        "Depois de colar, proteja a coluna contra edição manual. Se um uid",
        "sumir ou for alterado, o sync cria um processo duplicado e o cliente",
        "perde o histórico.",
        "",
    ]

    for aba, coluna, linha_cab, uids, _novos in blocos:
        linhas_saida += [
            "=" * 62,
            f"ABA: {aba}",
            f"COLAR EM: {coluna}{linha_cab}",
            "=" * 62,
            planilha.COLUNA_UID,
            *uids,
            "",
        ]

    with open(ARQUIVO_UIDS, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_saida))

    print(f"Gerado: {ARQUIVO_UIDS}")


if __name__ == "__main__":
    sys.exit(principal())
