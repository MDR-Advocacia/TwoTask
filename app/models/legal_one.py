from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.session import Base

from .associations import squad_task_type_association


class LegalOneTaskSubType(Base):
    __tablename__ = "legal_one_task_subtypes"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    parent_type_external_id = Column(
        Integer,
        ForeignKey("legal_one_task_types.external_id"),
        index=True,
        nullable=False,
    )

    parent_type = relationship("LegalOneTaskType", back_populates="subtypes")


class LegalOneTaskType(Base):
    __tablename__ = "legal_one_task_types"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    subtypes = relationship(
        "LegalOneTaskSubType",
        back_populates="parent_type",
        cascade="all, delete-orphan",
    )
    squads = relationship(
        "Squad",
        secondary=squad_task_type_association,
        back_populates="task_types",
    )


class LegalOneOffice(Base):
    __tablename__ = "legal_one_offices"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    path = Column(String)
    is_active = Column(Boolean, default=True)


class LegalOneUser(Base):
    __tablename__ = "legal_one_users"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    email = Column(String, index=True, unique=True)
    is_active = Column(Boolean, default=True, nullable=False)
    hashed_password = Column(String, nullable=True)

    squad_members = relationship("SquadMember", back_populates="user")
