# create_user.py

import argparse
from sqlalchemy.orm import sessionmaker
from app.db.session import engine
from app.models.legal_one import LegalOneUser
from app.core.auth import get_password_hash

# Configura a sessão com o banco de dados
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def set_user_password(email: str, password: str):
    """
    Encontra um usuário pelo e-mail e define uma nova senha para ele.
    """
    db = SessionLocal()
    try:
        # 1. Encontra o usuário no banco de dados
        user = db.query(LegalOneUser).filter(LegalOneUser.email == email).first()

        if not user:
            print(f"Erro: Usuário com e-mail '{email}' não encontrado.")
            return

        # 2. Gera o hash da nova senha
        hashed_password = get_password_hash(password)

        # 3. Atualiza o usuário e salva no banco
        user.hashed_password = hashed_password
        db.commit()
        print(f"Sucesso! A senha para o usuário '{email}' foi definida.")

    finally:
        db.close()

if __name__ == "__main__":
    # Configura os argumentos da linha de comando para facilitar o uso
    parser = argparse.ArgumentParser(description="Define a senha para um usuário existente.")
    parser.add_argument("--email", required=True, help="E-mail do usuário a ser atualizado.")
    parser.add_argument("--password", required=True, help="A nova senha para o usuário.")

    args = parser.parse_args()

    # Chama a função principal
    set_user_password(args.email, args.password)