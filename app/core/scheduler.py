"""
Singleton do APScheduler compartilhado entre main.py e endpoints.

Mantido aqui (em vez de main.py) pra evitar import circular quando os endpoints
precisam injetar o scheduler via Depends().
"""

from apscheduler.schedulers.background import BackgroundScheduler

# Singleton process-wide. Iniciado/parado no lifespan do FastAPI (main.py).
scheduler: BackgroundScheduler = BackgroundScheduler()


def get_scheduler() -> BackgroundScheduler:
    """FastAPI dependency que devolve o scheduler singleton."""
    return scheduler
