# app/api/v1/endpoints/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core import auth
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.api.v1 import schemas

router = APIRouter()

@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    Endpoint de login. Recebe e-mail (como username) e senha.
    Retorna um token de acesso JWT em caso de sucesso.
    """
    # 1. Busca o usuário pelo e-mail no banco de dados.
    user = db.query(LegalOneUser).filter(LegalOneUser.email == form_data.username).first()

    # 2. Verifica se o usuário existe e se a senha está correta.
    # Usamos a função `verify_password` que criamos anteriormente.
    if not user or not user.hashed_password or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Cria o token de acesso.
    # O "sub" (subject) do token será o e-mail do usuário.
    access_token = auth.create_access_token(
        data={"sub": user.email}
    )

    # 4. Retorna o token.
    return {"access_token": access_token, "token_type": "bearer"}