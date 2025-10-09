# app/core/auth.py

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt  # JWTError foi removido
from passlib.context import CryptContext
from pydantic import BaseModel

# --- Configurações de Segurança ---
SECRET_KEY = "sua-chave-secreta-super-segura-aqui"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- Funções de Utilitário ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se uma senha em texto plano corresponde a um hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Gera o hash de uma senha."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Cria um novo token de acesso JWT.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Schemas Pydantic para os tokens ---

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None