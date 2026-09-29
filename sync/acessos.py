"""Criação das contas de login dos titulares.

Vive em módulo próprio porque dois caminhos precisam dela: o `sincronizar.py`,
que provisiona ao final de cada execução, e o `provisionar_acessos.py`, que
serve para rodar isolado e para auditar quem está sem acesso.

Por que o sync provisiona sozinho
---------------------------------
A conta em `auth.users` precisa existir ANTES de a pessoa pedir o magic link:
o cadastro público está desligado e a tela manda `shouldCreateUser: false`.

Quando esse passo era manual, esquecer dele produzia uma falha silenciosa — a
API respondia `422 otp_disabled`, nenhum e-mail saía, e a tela mostrava a
mensagem de sucesso mesmo assim, de propósito, para não revelar quem é cliente
da Royal. O cliente ficava esperando um link que o servidor nunca tentou
enviar, e ninguém via erro em lugar nenhum.

Passo que falha em silêncio não pode ser manual. Por isso ele virou parte do
sync, com bandeira para desligar quando se quiser controlar.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResultadoAcessos:
    emails_desejados: set[str] = field(default_factory=set)
    ja_existiam: set[str] = field(default_factory=set)
    a_criar: list[str] = field(default_factory=list)
    criados: list[str] = field(default_factory=list)
    falhas: list[tuple[str, str]] = field(default_factory=list)
    ligados: int = 0
    sem_acesso: list[dict] = field(default_factory=list)


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


def provisionar(sb, aplicar: bool) -> ResultadoAcessos:
    """Cria conta para todo titular com e-mail que ainda não tem uma.

    Não envia mensagem: a conta nasce em silêncio e já com o endereço
    confirmado. O cliente recebe o link quando ele mesmo pedir, na tela de
    login — o que evita gastar a cota de envio com e-mails que ninguém pediu.
    """
    res = ResultadoAcessos()

    r = sb.table("titulares").select("id, nome, email, auth_uid").execute()
    titulares = [t for t in (r.data or []) if t.get("email")]
    res.emails_desejados = {t["email"].strip().lower() for t in titulares}

    if not res.emails_desejados:
        return res

    ja_tem = emails_existentes(sb)
    res.ja_existiam = res.emails_desejados & ja_tem
    res.a_criar = sorted(res.emails_desejados - ja_tem)

    if aplicar:
        for email in res.a_criar:
            try:
                sb.auth.admin.create_user({"email": email, "email_confirm": True})
                res.criados.append(email)
            except Exception as e:
                res.falhas.append((email, str(e)))

        from . import banco
        res.ligados = banco.vincular_titulares_pendentes(sb)

    # Quem não consegue logar hoje. É a informação que a tela de login esconde
    # de propósito, e este é o único lugar do sistema onde ela aparece.
    r2 = sb.table("titulares").select("nome, email, auth_uid").execute()
    res.sem_acesso = [
        t for t in (r2.data or []) if t.get("email") and not t.get("auth_uid")
    ]

    return res


def relatar(res: ResultadoAcessos, aplicar: bool, prefixo: str = "") -> None:
    """Imprime o resultado. `prefixo` recua o bloco quando vem dentro do sync."""
    p = prefixo

    if not res.emails_desejados:
        print(f"{p}nenhum titular com e-mail cadastrado")
        return

    if res.a_criar and not aplicar:
        for email in res.a_criar:
            print(f"{p}conta a criar: {email}")
    for email in res.criados:
        print(f"{p}conta criada: {email}")
    for email, erro in res.falhas:
        print(f"{p}FALHA ao criar {email}: {erro}")

    if res.sem_acesso:
        print(f"{p}AINDA SEM ACESSO ({len(res.sem_acesso)}):")
        for t in res.sem_acesso:
            print(f"{p}  {t['email']} ({t['nome']})")
        print(f"{p}Esses titulares não conseguem logar. A tela de login não")
        print(f"{p}avisa isso ao visitante, então este é o único aviso.")
