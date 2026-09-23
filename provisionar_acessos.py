#!/usr/bin/env python
"""Cria as contas de acesso dos titulares no Supabase Auth.

    python provisionar_acessos.py             # simula, não cria nada
    python provisionar_acessos.py --aplicar   # cria as contas

Por que este passo existe
-------------------------
O site pede o magic link com `shouldCreateUser: false`, e o cadastro público
está desligado no painel. As duas travas juntas impedem que um e-mail
desconhecido crie conta — que é o que queremos — mas também impedem o primeiro
acesso de quem é cliente de verdade.

A conta precisa existir ANTES de a pessoa pedir o link. Quem cria é este
script, a partir da tabela `titulares`, usando a service_role.

O que ele NÃO faz
-----------------
Não envia e-mail. A conta é criada em silêncio e já com o endereço confirmado;
o cliente recebe o link quando ele mesmo pedir, na tela de login. Isso evita
gastar a cota de envio do Supabase com mensagens que ninguém pediu.

Regra do produto que este script materializa: conta existe só para quem é
titular de algum processo.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from sync import banco


def emails_existentes(sb) -> set[str]:
    """E-mails que já têm conta em auth.users."""
    achados: set[str] = set()
    pagina = 1
    while True:
        try:
            r = sb.auth.admin.list_users(page=pagina, per_page=200)
        except TypeError:
            # versões antigas do cliente não aceitam paginação
            r = sb.auth.admin.list_users()
            pagina = None

        usuarios = getattr(r, "users", r) or []
        for u in usuarios:
            email = getattr(u, "email", None) or (u.get("email") if isinstance(u, dict) else None)
            if email:
                achados.add(email.strip().lower())

        if pagina is None or len(usuarios) < 200:
            break
        pagina += 1

    return achados


def principal() -> int:
    ap = argparse.ArgumentParser(
        description="Cria contas de acesso para os titulares cadastrados.")
    ap.add_argument("--aplicar", action="store_true",
                    help="cria as contas; sem esta flag apenas simula")
    args = ap.parse_args()

    load_dotenv()

    modo = "APLICANDO" if args.aplicar else "SIMULAÇÃO (nada será criado)"
    print(f"=== Provisionamento de acessos — {modo} ===\n")

    try:
        sb = banco.criar_cliente()
    except banco.BancoError as e:
        print(f"ERRO DE CONFIGURAÇÃO\n{e}", file=sys.stderr)
        return 1

    r = sb.table("titulares").select("id, processo_id, nome, email, auth_uid").execute()
    titulares = [t for t in (r.data or []) if t.get("email")]

    if not titulares:
        print("Nenhum titular com e-mail cadastrado.")
        print("Preencha a aba Titulares da planilha e rode carga_inicial.py --aplicar.")
        return 0

    # Um e-mail pode ser titular de vários processos; a conta é uma só.
    por_email: dict[str, list[dict]] = {}
    for t in titulares:
        por_email.setdefault(t["email"].strip().lower(), []).append(t)

    print(f"{len(titulares)} titular(es) em {len(por_email)} e-mail(s) distinto(s)\n")

    try:
        ja_tem = emails_existentes(sb)
    except Exception as e:
        print(f"ERRO ao listar usuários existentes: {e}", file=sys.stderr)
        print("Confira se SUPABASE_SERVICE_ROLE_KEY é mesmo a service_role.", file=sys.stderr)
        return 1

    faltando = [e for e in sorted(por_email) if e not in ja_tem]
    presentes = [e for e in sorted(por_email) if e in ja_tem]

    for email in presentes:
        print(f"  [ja existe] {email}  ({len(por_email[email])} processo(s))")
    for email in faltando:
        print(f"  [criar    ] {email}  ({len(por_email[email])} processo(s))")

    criados, falhas = 0, []
    if args.aplicar and faltando:
        print()
        for email in faltando:
            try:
                sb.auth.admin.create_user({
                    "email": email,
                    # Já confirmado: a conta não nasce pendente de um e-mail
                    # de confirmação que ninguém pediu. O magic link que o
                    # cliente solicitar é a própria prova de posse.
                    "email_confirm": True,
                })
                criados += 1
            except Exception as e:
                falhas.append((email, str(e)))
                print(f"  FALHA em {email}: {e}", file=sys.stderr)

    if args.aplicar:
        ligados = banco.vincular_titulares_pendentes(sb)
        print(f"\n{criados} conta(s) criada(s), {ligados} titular(es) ligado(s) à conta")

    # Quem não consegue logar hoje. É a informação que a tela de login esconde
    # de propósito, para não revelar a terceiros quem é cliente da Royal.
    r2 = sb.table("titulares").select("nome, email, auth_uid").execute()
    sem_conta = [t for t in (r2.data or []) if t.get("email") and not t.get("auth_uid")]

    print("\n=== Resumo ===")
    print(f"e-mails distintos      : {len(por_email)}")
    print(f"já tinham conta        : {len(presentes)}")
    print(f"criados nesta execução : {criados}")
    if falhas:
        print(f"falhas                 : {len(falhas)}")

    if sem_conta:
        print(f"\nAINDA SEM ACESSO ({len(sem_conta)}):")
        for t in sem_conta:
            print(f"  {t['email']} ({t['nome']})")
        print("\nEsses titulares não conseguem logar. A tela de login não avisa")
        print("isso ao visitante de propósito, então este relatório é o único")
        print("lugar onde a falta aparece.")
    elif args.aplicar:
        print("\nTodos os titulares com e-mail têm acesso.")

    if not args.aplicar:
        print("\nNada foi criado. Para aplicar:  python provisionar_acessos.py --aplicar")

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(principal())
