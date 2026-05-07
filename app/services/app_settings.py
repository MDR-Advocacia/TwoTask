"""Helper service pra leitura/escrita de app_settings.

Cache em memoria com TTL curto (60s) pra que callers em hot path
(taxonomy.get_active_taxonomy_version) nao batam no DB a cada
request. Setters invalidam o cache imediatamente.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
_CACHE: dict[str, str] = {}
_CACHE_AT: dict[str, float] = {}
_CACHE_LOCK = threading.Lock()


def invalidate_app_settings_cache(key: Optional[str] = None) -> None:
    """Apaga cache de uma key (ou tudo, quando key=None)."""
    with _CACHE_LOCK:
        if key is None:
            _CACHE.clear()
            _CACHE_AT.clear()
        else:
            _CACHE.pop(key, None)
            _CACHE_AT.pop(key, None)


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Le uma setting do cache ou DB. Retorna `default` se a key nao
    existe no DB ou se a leitura falha (DB indisponivel etc.)."""
    now = time.monotonic()
    cached_at = _CACHE_AT.get(key, 0.0)
    if key in _CACHE and (now - cached_at) < _CACHE_TTL_SECONDS:
        return _CACHE[key]

    try:
        from app.db.session import SessionLocal
        from app.models.app_setting import AppSetting
        with SessionLocal() as db:
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row is None:
                return default
            with _CACHE_LOCK:
                _CACHE[key] = row.value
                _CACHE_AT[key] = now
            return row.value
    except Exception as exc:  # noqa: BLE001
        logger.warning("app_settings: falha lendo '%s' do DB: %s", key, exc)
        return default


def set_setting(key: str, value: str, description: Optional[str] = None) -> None:
    """Persiste uma setting (UPSERT) e invalida o cache da chave.

    Caller deve ser admin — esse helper nao faz auth check, isso fica
    a cargo do endpoint."""
    from app.db.session import SessionLocal
    from app.models.app_setting import AppSetting
    with SessionLocal() as db:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row is None:
            row = AppSetting(key=key, value=value, description=description)
            db.add(row)
        else:
            row.value = value
            if description is not None:
                row.description = description
        db.commit()
    invalidate_app_settings_cache(key)
    logger.info("app_settings: '%s' atualizado para '%s'", key, value)
