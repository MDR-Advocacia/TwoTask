import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.legal_one import (
    LegalOneOffice,
    LegalOneTaskSubType,
    LegalOneTaskType,
    LegalOneUser,
)
from app.services.legal_one_client import LegalOneApiClient

logging.basicConfig(level=logging.INFO)


class MetadataSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.legal_one_client = LegalOneApiClient()
        self.logger = logging.getLogger(__name__)

    def sync_all_metadata(self) -> dict:
        self.logger.info("Iniciando sincronizacao completa de metadados...")
        summary = {
            "offices": False,
            "users": False,
            "task_types": False,
        }

        try:
            summary["offices"] = self.sync_offices()
            summary["users"] = self.sync_users()
            summary["task_types"] = self.sync_task_types_and_subtypes()
        except Exception as exc:
            self.logger.error("Erro critico durante a sincronizacao de metadados: %s", exc, exc_info=True)
            raise

        if all(summary.values()):
            self.logger.info("Sincronizacao completa de metadados concluida com sucesso.")
        else:
            self.logger.warning("Sincronizacao concluida com pendencias: %s", summary)

        return summary

    def sync_offices(self) -> bool:
        self.logger.info("Sincronizando escritorios (Offices)...")
        try:
            offices_data = self.legal_one_client.get_all_allocatable_areas()
            if not offices_data:
                self.logger.warning("Nenhum escritorio alocavel encontrado na API do Legal One.")
                return False

            with self.db.begin_nested():
                existing_offices = {office.external_id: office for office in self.db.query(LegalOneOffice).all()}

                for office_data in offices_data:
                    external_id = office_data.get("id")
                    if not external_id:
                        continue

                    office = existing_offices.get(external_id)
                    if office:
                        office.name = office_data.get("name")
                        office.path = office_data.get("path")
                        office.is_active = True
                    else:
                        self.db.add(
                            LegalOneOffice(
                                external_id=external_id,
                                name=office_data.get("name"),
                                path=office_data.get("path"),
                                is_active=True,
                            )
                        )

                active_external_ids = {office["id"] for office in offices_data if office.get("id")}
                for external_id, office in existing_offices.items():
                    if external_id not in active_external_ids:
                        office.is_active = False

            self.db.commit()
            self.logger.info("Sincronizacao de escritorios concluida.")
            return True
        except Exception as exc:
            self.db.rollback()
            self.logger.error("Erro ao sincronizar escritorios: %s", exc, exc_info=True)
            return False

    def sync_users(self) -> bool:
        self.logger.info("Sincronizando usuarios (Users)...")
        try:
            users_data = self.legal_one_client.get_all_users()
            if not users_data:
                self.logger.warning("Nenhum usuario encontrado na API do Legal One.")
                return False

            with self.db.begin_nested():
                existing_users = {user.external_id: user for user in self.db.query(LegalOneUser).all()}

                # Índice secundário por email para detectar usuários criados
                # manualmente (ex.: admin com external_id=0) e vinculá-los ao
                # external_id real do Legal One sem gerar UniqueViolation.
                existing_by_email = {u.email: u for u in existing_users.values() if u.email}

                for user_data in users_data:
                    external_id = user_data.get("id")
                    if not external_id:
                        continue

                    email = user_data.get("email")
                    user = existing_users.get(external_id)

                    if not user and email:
                        # Fallback: talvez exista pelo email (criado manualmente).
                        user = existing_by_email.get(email)
                        if user:
                            # Vincula ao external_id real; preserva role, senha
                            # e permissões que foram configurados manualmente.
                            user.external_id = external_id
                            existing_users[external_id] = user

                    if user:
                        user.name = user_data.get("name")
                        user.email = email
                        user.is_active = user_data.get("isActive", False)
                    else:
                        new_user = LegalOneUser(
                            external_id=external_id,
                            name=user_data.get("name"),
                            email=email,
                            is_active=user_data.get("isActive", False),
                        )
                        self.db.add(new_user)
                        if email:
                            existing_by_email[email] = new_user

                active_external_ids = {
                    user["id"]
                    for user in users_data
                    if user.get("id") and user.get("isActive")
                }
                for external_id, user in existing_users.items():
                    if external_id not in active_external_ids:
                        user.is_active = False

            self.db.commit()
            self.logger.info("Sincronizacao de usuarios concluida.")
            return True
        except Exception as exc:
            self.db.rollback()
            self.logger.error("Erro ao sincronizar usuarios: %s", exc, exc_info=True)
            return False

    def sync_task_types_and_subtypes(self) -> bool:
        self.logger.info("Iniciando sincronizacao de tipos e subtipos de tarefas...")
        try:
            self.logger.info("Buscando todos os tipos de tarefa (pais)...")
            parent_types_data = self.legal_one_client._paginated_catalog_loader(
                "/UpdateAppointmentTaskTypes",
                {"$filter": "isTaskType eq true", "$select": "id,name"},
            )
            self.logger.info("Encontrados %s tipos de tarefa pai.", len(parent_types_data))

            self.logger.info("Buscando todos os subtipos de tarefa (filhos)...")
            all_subtypes_data = self.legal_one_client._paginated_catalog_loader(
                "/UpdateAppointmentTaskSubtypes",
                {"$select": "id,name,parentTypeId"},
            )
            self.logger.info("Encontrados %s subtipos de tarefa.", len(all_subtypes_data))

            if not parent_types_data:
                self.logger.warning(
                    "Sincronizacao de tipos abortada: nenhum tipo pai foi retornado. O catalogo local foi preservado."
                )
                return False

            subtypes_map: dict[int, list[dict]] = {}
            for sub_data in all_subtypes_data:
                parent_id = sub_data.get("parentTypeId")
                if not parent_id:
                    continue
                subtypes_map.setdefault(parent_id, []).append(sub_data)

            with self.db.begin_nested():
                self.logger.info("Limpando tabelas antigas de tipos e subtipos...")
                self.db.query(LegalOneTaskSubType).delete()
                self.db.query(LegalOneTaskType).delete()

                parent_objects: list[LegalOneTaskType] = []
                for parent_data in parent_types_data:
                    parent_obj = LegalOneTaskType(
                        external_id=parent_data["id"],
                        name=parent_data["name"],
                        is_active=True,
                    )

                    for child_data in subtypes_map.get(parent_data["id"], []):
                        parent_obj.subtypes.append(
                            LegalOneTaskSubType(
                                external_id=child_data["id"],
                                name=child_data["name"],
                                parent_type_external_id=child_data["parentTypeId"],
                                is_active=True,
                            )
                        )

                    parent_objects.append(parent_obj)

                self.logger.info(
                    "Adicionando %s tipos de tarefa pai com seus subtipos a sessao.",
                    len(parent_objects),
                )
                self.db.add_all(parent_objects)

            self.db.commit()
            self.logger.info("Sincronizacao de tipos e subtipos concluida com sucesso.")
            return True
        except Exception as exc:
            self.db.rollback()
            self.logger.error("Erro ao sincronizar tipos e subtipos: %s", exc, exc_info=True)
            return False


def run_metadata_sync_job() -> None:
    db = SessionLocal()
    try:
        service = MetadataSyncService(db=db)
        service.sync_all_metadata()
    finally:
        db.close()
