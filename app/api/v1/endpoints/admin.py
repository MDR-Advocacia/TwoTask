# Criar o arquivo: app/api/v1/endpoints/admin.py

from fastapi import APIRouter, Depends, BackgroundTasks, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.metadata_sync_service import MetadataSyncService

router = APIRouter()

# Define o esquema de segurança: espera um header 'X-Admin-Token'
api_key_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    """
    Dependência de segurança que valida o token de admin.
    Em um app real, isso seria mais complexo (ex: validar um JWT de um usuário admin).
    """
    # TODO: Mover o token para uma variável de ambiente segura.
    if api_key == "SECRET_ADMIN_TOKEN_123":
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

@router.post(
    "/sync-metadata",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(get_api_key)], # Aplica a segurança a este endpoint
    summary="Inicia a sincronização de metadados do Legal One"
)
async def trigger_metadata_sync(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Dispara o processo de sincronização de todos os metadados
    (Escritórios, Tipos/Subtipos de Tarefa) em segundo plano.

    Esta operação pode demorar alguns minutos. A resposta é imediata,
    e o processo continua no servidor.
    """
    
    def run_sync():
        # A lógica real da sincronização precisa ser síncrona para rodar em background
        # ou necessitaria de um executor de loop de eventos.
        # Por simplicidade, vamos adaptar o serviço para rodar de forma síncrona aqui.
        # NOTA: O ideal seria usar uma fila de tarefas como Celery para jobs longos.
        
        # Como os métodos do cliente da API não são async, podemos chamar assim:
        sync_service = MetadataSyncService(db)
        
        # O ideal é adaptar o serviço para ter um método síncrono ou usar um executor.
        # Por enquanto, vamos assumir que o serviço pode ser chamado diretamente.
        # Em um próximo passo, podemos refatorar o serviço para ser mais flexível (async/sync).
        
        # Placeholder para a chamada síncrona.
        # Em um cenário real, você usaria asyncio.run() ou um executor.
        # Por simplicidade, vamos adaptar o serviço para ter um método síncrono.
        # Neste momento, o código abaixo é um pseudo-código.
        # sync_service.sync_all_metadata_sync() -> criaríamos uma versão síncrona.

        # Vamos criar uma função wrapper para chamar a função async
        import asyncio
        asyncio.run(sync_service.sync_all_metadata())

    background_tasks.add_task(run_sync)
    
    return {"message": "A sincronização de metadados foi iniciada em segundo plano."}