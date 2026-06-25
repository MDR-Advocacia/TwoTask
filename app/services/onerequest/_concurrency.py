"""Lock entre workers do uvicorn.

Cada worker do uvicorn cria seu PRÓPRIO APScheduler, então um job horário
dispara N vezes (uma por worker) ao mesmo tempo. Pra jobs que escrevem
(sync da fonte, auto-refresh), isso causa corrida (ex.: duplicate key em
inserts concorrentes) e trabalho N× duplicado.

`single_worker_lock` usa um ADVISORY LOCK do Postgres (escopo de sessão, global
no servidor) numa conexão DEDICADA — só o worker que pega o lock roda; os outros
pulam o tick. O lock é de sessão (sobrevive a commit/rollback) e é liberado
explicitamente no fim (+ no close da conexão, por garantia).
"""

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def single_worker_lock(key: int):
    """Cede True se ESTE processo pegou o lock; False se outro já está com ele.

    Em dev local (sqlite) não há multi-worker — cede sempre True.
    """
    from sqlalchemy import text

    from app.db.session import engine

    if engine.dialect.name != "postgresql":
        yield True
        return

    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    got = False
    try:
        got = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        )
        yield got
    finally:
        try:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        except Exception:  # noqa: BLE001
            logger.warning("single_worker_lock: falha ao liberar lock %s", key, exc_info=True)
        finally:
            conn.close()
