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
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

from sync import acessos, banco, fontes, planilha


class SyncAbortado(RuntimeError):
    """A guarda de sanidade barrou a execução. Nada foi gravado."""


def principal() -> int:
    ap = argparse.ArgumentParser(description="Sincroniza a planilha com o banco.")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava; sem esta flag apenas simula")
    ap.add_argument("--forcar", action="store_true",
                    help="ignora a guarda de sanidade (use após conferir o plano)")
    ap.add_argument("--sem-provisionar", action="store_true",
                    help="não cria contas de login ao final")
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

    print(f"fonte    : {fonte.descrever()}")
    no_banco = banco.processos_por_uid(sb)
    etapas_banco = banco.etapas_atuais(sb)

    # ---- plano --------------------------------------------------------
    sem_uid, desconhecidos = [], []
    mudancas_status: list[dict] = []
    processos_tocados: set[str] = set()
    dados_alterados: list[tuple[str, dict]] = []
    vistos_uid: set[str] = set()

    novos: list = []
    for p in linhas_planilha:
        if not p.uid:
            # Linha nova: o sync cria o processo e carimba o uid de volta.
            #
            # Só quando a fonte aceita escrita segura. Sem o carimbo, a
            # execução seguinte não reconheceria a linha e criaria o processo
            # de novo — duplicar é pior do que parar e avisar.
            if fonte.escrita_segura and p.imovel:
                p.uid = str(uuid.uuid4())
                novos.append(p)
                vistos_uid.add(p.uid)
                continue
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

    if novos:
        print(f"PROCESSOS NOVOS ({len(novos)}):")
        for p in novos:
            print(f"  {p.cliente_bruto:22} {p.imovel}")
        print()

    for pid, campos in dados_alterados:
        print(f"  dados alterados em {pid[:8]}: {', '.join(campos)}")
    for p in sem_uid:
        print(f"  SEM UID: {p.aba} linha {p.numero_linha} ({p.cliente_bruto})")
    for p in desconhecidos:
        print(f"  UID DESCONHECIDO: {p.uid} ({p.cliente_bruto})")
    for proc in sumidos:
        print(f"  SUMIU DA PLANILHA: {proc['imovel']} (uid {proc['uid_planilha']})")

    # ---- plano de titulares -------------------------------------------
    # Calculado ANTES da guarda: remover titular é revogar acesso, e uma
    # revogação em massa precisa passar pelo mesmo freio que uma mudança de
    # status em massa.
    titulares_planilha = planilha.ler_titulares(fonte)
    uid_para_id = {u: pr["id"] for u, pr in no_banco.items()}

    # A normalização do e-mail é silenciosa por natureza, e silêncio aqui é
    # ruim: a planilha é a fonte da verdade (regra 8), então o valor ruim fica
    # lá para sempre e volta a aparecer no próximo cadastro feito do mesmo
    # jeito. Avisar qual célula editar é o que fecha o ciclo.
    corrigidos = [t for t in titulares_planilha
                  if t.problema and t.email and t.email_bruto.strip() != t.email]
    if corrigidos:
        print(f"\nE-MAILS AJUSTADOS NA LEITURA ({len(corrigidos)}):")
        for t in corrigidos:
            print(f"  linha {t.numero_linha}: {t.email_bruto!r} -> {t.email!r}")
        print("  O sync usa o valor da direita. Corrija a planilha para o")
        print("  aviso parar de aparecer.")

    # Imóvel -> uid, para quem preencheu a aba Titulares sem o uid. Copiar um
    # UUID de 36 caracteres entre abas na mão era o passo mais propenso a erro
    # do cadastro; aqui a pessoa escreve o imóvel e o sync resolve.
    #
    # Imóvel repetido não é resolvido por adivinhação: entra em `ambiguos` e a
    # linha é ignorada com aviso.
    # A chave ignora acento, caixa e espaço repetido: quem redigita o imóvel na
    # outra aba erra justamente nisso, e recusar por causa de um acento seria
    # rigor sem propósito.
    def _chave_imovel(texto: str) -> str:
        return planilha.normalizar_rotulo(texto)

    por_imovel: dict[str, list[str]] = {}
    for p in linhas_planilha:
        if p.uid and p.imovel:
            por_imovel.setdefault(_chave_imovel(p.imovel), []).append(p.uid)

    titulares_a_carimbar: list[tuple[int, str]] = []
    ambiguos, sem_processo = [], []

    desejados: dict[tuple[str, str], dict] = {}
    email_ruim: list = []

    # Processos com alguma linha pendente na aba Titulares. O acesso que já
    # existe neles fica congelado até o técnico resolver — ver o porquê junto
    # ao cálculo de `a_remover`.
    protegidos: set[str] = set()

    for t in titulares_planilha:
        uid = t.uid_processo
        if not uid:
            candidatos = por_imovel.get(_chave_imovel(t.imovel), [])
            if len(candidatos) == 1:
                uid = candidatos[0]
                titulares_a_carimbar.append((t.numero_linha, uid))
            elif len(candidatos) > 1:
                ambiguos.append(t)
                if len(set(candidatos)) == 1:
                    protegidos.add(candidatos[0])
                continue
            else:
                sem_processo.append(t)
                continue

        # E-mail que não dá para usar não vira acesso, mas também não pode
        # fazer o processo perder o que já tem: a linha existe, o titular
        # existe, só o texto da célula está ruim.
        if not t.email:
            email_ruim.append(t)
            protegidos.add(uid)
            continue

        # Indexado por UID, não pelo id do banco: processo criado nesta mesma
        # execução ainda não tem id, e o titular dele seria descartado — que é
        # justamente o caso do cadastro de cliente novo numa passada só.
        chave = (uid, t.email)
        anterior = desejados.get(chave)
        if anterior is None:
            desejados[chave] = {"uid": uid, "nome": t.nome, "email": t.email}
        elif t.nome not in anterior["nome"].split(" / "):
            anterior["nome"] = f"{anterior['nome']} / {t.nome}"

    # Só mexe em titular de processo que APARECE na planilha. Processo ausente
    # já é tratado como "sumiu" e não deve perder os acessos por tabela.
    id_para_uid = {pr["id"]: u for u, pr in no_banco.items()}
    no_banco_titulares = banco.titulares_por_processo(sb)
    a_remover = []
    for uid in vistos_uid:
        pid = uid_para_id.get(uid)
        if pid is None:
            continue                      # processo novo: ainda não tem titular

        # Processo com linha pendente não perde acesso. Um e-mail digitado
        # errado deixaria a linha fora de `desejados`, o sync leria isso como
        # "titular saiu da aba" e revogaria — então um erro de digitação
        # tiraria do ar o acesso de um cliente que estava funcionando, e o
        # endereço novo nem seria criado, porque está inválido. O cliente
        # ficaria sem nada.
        #
        # Congelar é o lado certo para errar: o acesso antigo continua
        # valendo, e a observação na planilha pede a correção.
        if uid in protegidos:
            continue

        for t in no_banco_titulares.get(pid, []):
            if (uid, (t.get("email") or "").lower()) not in desejados:
                a_remover.append(t)

    # Quem ainda não tem acesso. Reportar só as revogações seria assimétrico:
    # quem confere o plano precisa ver as duas pontas antes de aplicar.
    ja_existentes = {
        (id_para_uid.get(pid), (t.get("email") or "").lower())
        for pid, lista in no_banco_titulares.items() for t in lista
    }
    a_criar = [d for chave, d in desejados.items() if chave not in ja_existentes]

    total_titulares = sum(len(v) for v in no_banco_titulares.values())

    if a_criar:
        print()
        print(f"ACESSOS A CRIAR ({len(a_criar)}):")
        for d in a_criar:
            print(f"  {d['email']:34} {d['nome']}")

    if a_remover:
        print()
        print(f"ACESSOS A REVOGAR ({len(a_remover)}):")
        for t in a_remover:
            print(f"  {t['email']:34} {t['nome']}")

    for t in ambiguos:
        print(f"  IMÓVEL AMBÍGUO em Titulares linha {t.numero_linha} "
              f"({t.email_bruto}): {t.imovel!r} aparece em mais de um "
              f"processo. Preencha o uid_processo nessa linha.")
    for t in sem_processo:
        print(f"  SEM PROCESSO em Titulares linha {t.numero_linha} "
              f"({t.email_bruto}): não achei processo com o imóvel "
              f"{t.imovel!r}.")
    for t in email_ruim:
        print(f"  E-MAIL INVÁLIDO em Titulares linha {t.numero_linha}: "
              f"{t.email_bruto!r} — sem acesso para esta pessoa. O acesso que "
              f"já existia no processo foi mantido.")

    # ---- recado na planilha -------------------------------------------
    # Log do Actions é lido por quem programa, e quem precisa corrigir a
    # célula é o técnico da Royal. A coluna "Obs. Script" é o canal que chega
    # nele: ele abre a planilha todo dia de qualquer forma.
    obs_desejada: dict[int, str] = {t.numero_linha: "" for t in titulares_planilha}
    for t in titulares_planilha:
        if t.problema:
            obs_desejada[t.numero_linha] = t.problema
    for t in ambiguos:
        obs_desejada[t.numero_linha] = (
            f"SEM ACESSO: o imóvel {t.imovel!r} aparece em mais de um "
            "processo, então não dá para saber de qual é este titular. "
            "Preencha a coluna uid_processo nesta linha."
        )
    for t in sem_processo:
        obs_desejada[t.numero_linha] = (
            f"SEM ACESSO: não existe processo com o imóvel {t.imovel!r}. "
            "Confira se o nome está igual ao da aba de fluxo — copie e cole "
            "de lá, não redigite."
        )

    # Só o que mudou. Reescrever a coluna toda todo dia gastaria cota da API
    # e encheria o histórico de revisões da planilha de alteração sem efeito.
    obs_a_escrever = [
        (t.numero_linha, obs_desejada[t.numero_linha])
        for t in titulares_planilha
        if obs_desejada[t.numero_linha] != t.obs_atual
    ]

    pendencias = len(email_ruim) + len(ambiguos) + len(sem_processo)

    # ---- defesa 3: guarda de sanidade ---------------------------------
    try:
        _guarda(ativos, processos_tocados, sumidos, sem_uid, desconhecidos,
                a_remover, total_titulares, args.forcar)
    except SyncAbortado as e:
        print(f"\n>>> SINCRONIZAÇÃO ABORTADA <<<\n{e}", file=sys.stderr)
        print("\nNada foi gravado. Confira o plano acima. Se a mudança for "
              "legítima, rode de novo com --forcar.", file=sys.stderr)
        return 2

    if not args.aplicar:
        print("\nNada foi gravado. Para aplicar:  python sincronizar.py --aplicar")
        if obs_a_escrever:
            print(f"Com --aplicar, {len(obs_a_escrever)} célula(s) da coluna "
                  f"{planilha.COLUNA_OBS!r} seriam atualizadas.")
        return 3 if pendencias else 0

    # ---- escrita ------------------------------------------------------
    # Onde carimbar. Só consulta a planilha quando há algo a escrever, para
    # não gastar chamada de API em execução que não muda nada — e são 96 por
    # dia com o cron de 15 minutos.
    col_uid_por_aba: dict[str, str] = {}
    for aba in {p.aba for p in novos}:
        idx, _ = planilha.indice_coluna_uid(fonte, aba)
        col_uid_por_aba[aba] = planilha.letra_coluna(idx)

    col_uid_titulares = None
    if titulares_a_carimbar:
        col_uid_titulares, _ = planilha.info_coluna_uid_titulares(fonte)

    # Processos novos primeiro: o carimbo vai para a planilha ANTES do banco.
    # Se o banco falhar, a planilha já tem o uid e a execução seguinte
    # reaproveita. Na ordem inversa, uma falha no carimbo faria a próxima
    # execução gerar outro uid e duplicar o processo.
    for p in novos:
        fonte.escrever_celula(p.aba, p.numero_linha, col_uid_por_aba[p.aba], p.uid)

        proc = banco.gravar_processo(sb, {
            "uid_planilha": p.uid,
            "modalidade": p.modalidade,
            "imovel": p.imovel,
            "corretor": p.corretor or None,
            "data_assinatura": p.data_assinatura,
            "ativo": True,
        })
        no_banco[p.uid] = proc
        uid_para_id[p.uid] = proc["id"]

        etapas_novas, hist_novo = [], []
        for codigo, status in p.etapas.items():
            etapa_id = ids_etapa[(p.modalidade, codigo)]
            etapas_novas.append({
                "processo_id": proc["id"], "etapa_id": etapa_id,
                "modalidade": p.modalidade, "status": status,
            })
            hist_novo.append({
                "processo_id": proc["id"], "etapa_id": etapa_id,
                "status_de": None, "status_para": status, "origem": "sync",
            })
        banco.gravar_etapas(sb, etapas_novas)
        banco.gravar_historico(sb, hist_novo)

    # Carimba na aba Titulares o uid que foi resolvido pelo imóvel, para a
    # próxima execução casar direto e não depender de o texto do imóvel
    # continuar idêntico.
    for numero_linha, uid in titulares_a_carimbar:
        fonte.escrever_celula(planilha.ABA_TITULARES, numero_linha, col_uid_titulares, uid)

    # Recado para o técnico, na própria planilha. Em lote: uma chamada de API
    # em vez de uma por linha.
    if obs_a_escrever:
        col_obs = planilha.info_coluna_obs(fonte)
        if col_obs is None:
            print(f"\nAVISO: a aba {planilha.ABA_TITULARES} não tem a coluna "
                  f"{planilha.COLUNA_OBS!r}.")
            print("  Crie essa coluna para o técnico receber os avisos na")
            print("  planilha. Sem ela, eles só aparecem aqui no log.")
        else:
            fonte.escrever_celulas(
                planilha.ABA_TITULARES,
                [(lin, col_obs, texto) for lin, texto in obs_a_escrever],
            )
            escritos = sum(1 for _, texto in obs_a_escrever if texto)
            limpos = len(obs_a_escrever) - escritos
            print(f"\n{planilha.COLUNA_OBS}: {escritos} aviso(s) escrito(s), "
                  f"{limpos} apagado(s).")

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
    # Grava antes de remover: se algo falhar no meio, sobra acesso a mais, não
    # a menos. Cliente sem acesso abre chamado; acesso que some sem aviso
    # parece que o sistema perdeu o processo dele.
    # Agora todo processo existe no banco, inclusive os criados acima, então o
    # uid vira id sem perder ninguém.
    registros_titulares = []
    for d in desejados.values():
        pid = uid_para_id.get(d["uid"])
        if pid is None:
            print(f"  AVISO: {d['email']} aponta para um processo que não existe")
            continue
        registros_titulares.append(
            {"processo_id": pid, "nome": d["nome"], "email": d["email"]})

    banco.gravar_titulares(sb, registros_titulares)
    banco.remover_titulares(sb, [t["id"] for t in a_remover])

    ligados = banco.vincular_titulares_pendentes(sb)

    # ---- acessos ------------------------------------------------------
    # Titular novo na planilha precisa de conta ANTES de pedir o magic link,
    # senão a API responde 422 otp_disabled e nenhum e-mail sai — sem erro na
    # tela, que esconde de propósito se o endereço existe. Passo que falha em
    # silêncio não pode depender de alguém lembrar.
    res_acessos = None
    if not args.sem_provisionar:
        print()
        print("--- acessos ---")
        try:
            res_acessos = acessos.provisionar(sb, aplicar=True)
            acessos.relatar(res_acessos, aplicar=True, prefixo="  ")
        except Exception as e:
            print(f"  FALHA ao provisionar acessos: {e}", file=sys.stderr)
            print("  Os dados foram gravados. Rode provisionar_acessos.py --aplicar",
                  file=sys.stderr)

    print(f"\n=== Aplicado ===")
    print(f"etapas atualizadas   : {len(etapas_reg)}")
    print(f"linhas de histórico  : {len(hist_reg)}")
    print(f"processos desativados: {len(sumidos)}")
    print(f"processos criados    : {len(novos)}")
    print(f"titulares gravados   : {len(registros_titulares)}")
    print(f"acessos revogados    : {len(a_remover)}")
    print(f"titulares ligados    : {ligados}")
    if res_acessos is not None:
        print(f"contas criadas       : {len(res_acessos.criados)}")
        if res_acessos.sem_acesso:
            print(f"AINDA SEM ACESSO     : {len(res_acessos.sem_acesso)}")

    # Saída 3: gravou tudo que podia, mas alguém ficou sem acesso por causa de
    # célula malpreenchida. Não é falha de infraestrutura e não é a guarda —
    # é pendência humana, e precisa de notificação própria. Sem isso a
    # execução fica verde no Actions enquanto um cliente não consegue entrar,
    # que é exatamente o modo de falha silenciosa que este projeto combate.
    if pendencias:
        print(f"\n>>> {pendencias} LINHA(S) PENDENTE(S) NA ABA "
              f"{planilha.ABA_TITULARES} <<<", file=sys.stderr)
        print(f"O que deu para sincronizar foi gravado. O detalhe de cada "
              f"linha está na coluna {planilha.COLUNA_OBS!r} da planilha, "
              f"para o técnico corrigir.", file=sys.stderr)
        return 3

    return 0


def _guarda(ativos, tocados, sumidos, sem_uid, desconhecidos,
            a_remover, total_titulares, forcar):
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
            f"{len(sem_uid)} linha(s) sem uid que o sync não pôde criar. "
            "Com o Google Sheets ele carimba sozinho; isto acontece quando a "
            "fonte é o arquivo local (que não aceita escrita sem estragar a "
            "validação de dados) ou quando a linha está sem imóvel.")

    if a_remover and total_titulares and len(a_remover) / total_titulares > 0.30:
        motivos.append(
            f"{len(a_remover)} de {total_titulares} acessos seriam revogados. "
            "Trocar e-mail em massa na aba Titulares é legítimo, mas some com "
            "o acesso de quem estava lá — confira a lista acima antes.")

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
