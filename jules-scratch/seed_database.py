import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Adiciona o diretório raiz ao path para encontrar o módulo 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import Base
from app.models.legal_one import LegalOneUser, LegalOneOffice
from app.models.rules import Sector, Squad, SquadMember

# --- Configuração do Banco de Dados ---
# Usa a mesma URL do arquivo .env para consistência
DATABASE_URL = "sqlite:///./data/database.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def seed_data():
    # Recria as tabelas para garantir um estado limpo
    # NOTA: Em um ambiente real, teríamos mais cuidado com dados existentes.
    # Base.metadata.drop_all(bind=engine)
    # Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # --- Verificar se os dados já existem para evitar duplicatas ---
        sector = db.query(Sector).filter(Sector.name == "Administrativo").first()
        if not sector:
            sector = Sector(name="Administrativo", is_active=True)
            db.add(sector)
            db.commit()
            db.refresh(sector)
            print("Setor 'Administrativo' criado.")

        squad = db.query(Squad).filter(Squad.name == "Squad Alpha").first()
        if not squad:
            squad = Squad(name="Squad Alpha", is_active=True, sector_id=sector.id)
            db.add(squad)
            db.commit()
            db.refresh(squad)
            print("Squad 'Squad Alpha' criado.")

        user = db.query(LegalOneUser).filter(LegalOneUser.email == "jonilson.test@example.com").first()
        if not user:
            user = LegalOneUser(
                external_id=101,
                name="Jonilson Vilela Cid Júnior",
                email="jonilson.test@example.com",
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print("Usuário 'Jonilson Vilela Cid Júnior' criado.")

        squad_member = db.query(SquadMember).filter(SquadMember.legal_one_user_id == user.id, SquadMember.squad_id == squad.id).first()
        if not squad_member:
            squad_member = SquadMember(squad_id=squad.id, legal_one_user_id=user.id, is_leader=False)
            db.add(squad_member)
            db.commit()
            print("Usuário associado ao squad.")

        office = db.query(LegalOneOffice).filter(LegalOneOffice.name == "Autor").first()
        if not office:
            office = LegalOneOffice(
                external_id=22,
                name="Autor",
                path="MDR Advocacia / Área operacional / Banco do Brasil / ... / Autor",
                is_active=True
            )
            db.add(office)
            db.commit()
            print("Escritório 'Autor' com path completo criado.")

        # Adicionar um segundo usuário para testar a ordenação
        user2 = db.query(LegalOneUser).filter(LegalOneUser.email == "ana.clara@example.com").first()
        if not user2:
            user2 = LegalOneUser(external_id=102, name="Ana Clara", email="ana.clara@example.com", is_active=True)
            db.add(user2)
            db.commit()
            db.refresh(user2)
            print("Usuário 'Ana Clara' criado para teste de ordenação.")

        print("\nBanco de dados populado com dados de teste com sucesso!")

    except Exception as e:
        print(f"Ocorreu um erro ao popular o banco de dados: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Garante que o diretório de dados exista
    if not os.path.exists("./data"):
        os.makedirs("./data")
    seed_data()