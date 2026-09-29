#!/usr/bin/env python
"""Cria as contas de acesso dos titulares no Supabase Auth.

    python provisionar_acessos.py             # simula, não cria nada
    python provisionar_acessos.py --aplicar   # cria as contas

O `sincronizar.py` já faz isso ao final de cada execução. Este script continua
existindo para dois usos:

  - auditar quem está sem acesso, sem tocar em nada (execução sem --aplicar)
  - provisionar isolado, quando o sync foi rodado com --sem-provisionar

A lógica mora em sync/acessos.py, compartilhada com o sincronizador.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from sync import acessos, banco


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

    try:
        res = acessos.provisionar(sb, aplicar=args.aplicar)
    except Exception as e:
        print(f"ERRO ao provisionar: {e}", file=sys.stderr)
        print("Confira se SUPABASE_SERVICE_ROLE_KEY é mesmo a service_role.",
              file=sys.stderr)
        return 1

    if not res.emails_desejados:
        print("Nenhum titular com e-mail cadastrado.")
        print("Preencha a aba Titulares da planilha e rode sincronizar.py --aplicar.")
        return 0

    print(f"{len(res.emails_desejados)} e-mail(s) distinto(s) entre os titulares\n")
    for email in sorted(res.ja_existiam):
        print(f"  [ja existe] {email}")
    for email in res.a_criar:
        marca = "criada" if email in res.criados else "criar"
        print(f"  [{marca:9}] {email}")

    print("\n=== Resumo ===")
    print(f"e-mails distintos      : {len(res.emails_desejados)}")
    print(f"já tinham conta        : {len(res.ja_existiam)}")
    print(f"criados nesta execução : {len(res.criados)}")
    if res.falhas:
        print(f"falhas                 : {len(res.falhas)}")
        for email, erro in res.falhas:
            print(f"  {email}: {erro}")
    if args.aplicar:
        print(f"titulares ligados      : {res.ligados}")

    if res.sem_acesso:
        print(f"\nAINDA SEM ACESSO ({len(res.sem_acesso)}):")
        for t in res.sem_acesso:
            print(f"  {t['email']} ({t['nome']})")
        print("\nEsses titulares não conseguem logar. A tela de login não avisa")
        print("isso ao visitante de propósito, então este relatório é o único")
        print("lugar onde a falta aparece.")
    elif args.aplicar:
        print("\nTodos os titulares com e-mail têm acesso.")

    if not args.aplicar:
        print("\nNada foi criado. Para aplicar:  python provisionar_acessos.py --aplicar")

    return 1 if res.falhas else 0


if __name__ == "__main__":
    sys.exit(principal())
