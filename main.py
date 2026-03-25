from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import admin, auth, dashboard, offices, sectors, squads, tasks, users
from app.core import auth as auth_security
from app.core.config import settings
from app.services.batch_worker import BatchExecutionWorker

batch_worker = BatchExecutionWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    batch_worker.start()
    try:
        yield
    finally:
        batch_worker.stop()


app = FastAPI(title="OneTask API", version="1.0.0", lifespan=lifespan)

origins = settings.cors_origins
allow_origin_regex = None
allow_credentials = True

if "*" in origins:
    origins = []
    allow_origin_regex = ".*"
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_dependencies = [Depends(auth_security.get_current_user)]

app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"], dependencies=protected_dependencies)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"], dependencies=protected_dependencies)
app.include_router(squads.router, prefix="/api/v1/squads", tags=["Squads"], dependencies=protected_dependencies)
app.include_router(sectors.router, prefix="/api/v1/sectors", tags=["Sectors"], dependencies=protected_dependencies)
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"], dependencies=protected_dependencies)
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"], dependencies=protected_dependencies)
app.include_router(offices.router, prefix="/api/v1", tags=["Offices"], dependencies=protected_dependencies)
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Autenticacao"])


@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo a API OneTask"}


@app.get("/healthz", tags=["Health"])
async def healthcheck():
    return {
        "status": "ok",
        "batch_worker_enabled": settings.batch_worker_enabled,
    }
