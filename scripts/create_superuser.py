"""
Cria (ou promove) um superusuário admin no banco.

Uso dentro do container:
  python /app/scripts/create_superuser.py

Variáveis de ambiente opcionais (se não informadas, usa defaults):
  ADMIN_EMAIL    (default: admin@mdradvocacia.com)
  ADMIN_NAME     (default: Administrador)
  ADMIN_PASSWORD (default: pede no terminal)
"""
import os
import sys
import getpass

# Garante que o app está no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import SessionLocal
from app.models.legal_one import LegalOneUser
from app.core.auth import get_password_hash


def main():
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    name = os.environ.get("ADMIN_NAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()

    if not email:
        email = input("Email do admin [admin@mdradvocacia.com]: ").strip() or "admin@mdradvocacia.com"
    if not name:
        name = input("Nome [Administrador]: ").strip() or "Administrador"
    if not password:
        password = getpass.getpass("Senha: ")
        if not password:
            print("Senha não pode ser vazia.")
            sys.exit(1)
        confirm = getpass.getpass("Confirme a senha: ")
        if password != confirm:
            print("Senhas não conferem.")
            sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(LegalOneUser).filter_by(email=email).first()
        if existing:
            print(f"Usuário {email} já existe (id={existing.id}). Atualizando para admin...")
            existing.role = "admin"
            existing.is_active = True
            existing.hashed_password = get_password_hash(password)
            existing.can_schedule_batch = True
            existing.can_use_publications = True
            existing.must_change_password = False
            db.commit()
            print(f"Usuário #{existing.id} promovido a admin com nova senha.")
        else:
            # external_id=0 é reservado para o superusuário criado manualmente
            # (não vem do Legal One).
            user = LegalOneUser(
                external_id=0,
                name=name,
                email=email,
                is_active=True,
                hashed_password=get_password_hash(password),
                role="admin",
                can_schedule_batch=True,
                can_use_publications=True,
                must_change_password=False,
            )
            db.add(user)
            db.commit()
            print(f"Admin criado: {name} <{email}> (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
