# app/core/auth.py (versão corrigida e mais enxuta)

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
# Removido: from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.api.v1.schemas import TokenData # Importa TokenData do local correto

# --- Configurações de Segurança (sem alterações) ---
SECRET_KEY = "sua-chave-secreta-super-segura-aqui"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# --- Schemas Pydantic foram movidos para schemas.py ---

# --- Funções de Utilitário (sem alterações) ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    # ...
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    # ...
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    # ...
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Função de Dependência (agora importa TokenData de schemas) ---
def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> LegalOneUser:
    # ... (código inalterado, mas agora usa o TokenData importado) ...
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = db.query(LegalOneUser).filter(LegalOneUser.email == token_data.username).first()
    if user is None:
        raise credentials_exception
    
    return user