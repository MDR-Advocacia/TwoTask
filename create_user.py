import argparse

from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from app.core.auth import get_password_hash
from app.db.session import engine
from app.models.legal_one import LegalOneUser

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _next_external_id(db) -> int:
    current_max = db.query(func.max(LegalOneUser.external_id)).scalar()
    return (current_max or 0) + 1


def set_user_password(
    email: str,
    password: str,
    *,
    create_if_missing: bool = False,
    name: str | None = None,
):
    db = SessionLocal()
    try:
        user = db.query(LegalOneUser).filter(LegalOneUser.email == email).first()

        if not user and not create_if_missing:
            print(f"Erro: usuário com e-mail '{email}' não encontrado.")
            return

        if not user:
            user = LegalOneUser(
                external_id=_next_external_id(db),
                email=email,
                name=(name or email.split("@")[0]).strip(),
                is_active=True,
            )
            db.add(user)
            db.flush()
            print(f"Usuário '{email}' criado com external_id {user.external_id}.")

        user.hashed_password = get_password_hash(password)
        db.commit()
        print(f"Sucesso! A senha para o usuário '{email}' foi definida.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Define a senha para um usuário existente ou cria um bootstrap local.")
    parser.add_argument("--email", required=True, help="E-mail do usuário.")
    parser.add_argument("--password", required=True, help="Senha do usuário.")
    parser.add_argument(
        "--create-if-missing",
        action="store_true",
        help="Cria o usuário caso ele ainda não exista.",
    )
    parser.add_argument(
        "--name",
        help="Nome exibido ao criar o usuário. Se omitido, usa o prefixo do e-mail.",
    )

    args = parser.parse_args()

    set_user_password(
        args.email,
        args.password,
        create_if_missing=args.create_if_missing,
        name=args.name,
    )
