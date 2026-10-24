"""Redis is an expendable accelerator; never a source of authorization or truth."""
import json
import logging
from functools import lru_cache

from redis import Redis
from app.core.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def client():
    return Redis.from_url(get_settings().redis_url, decode_responses=True,
                          socket_connect_timeout=0.15, socket_timeout=0.15,
                          max_connections=16)


def key(value):
    return f"knownest:{get_settings().environment}:v1:{value}"


def read(name, ttl=None):
    if not get_settings().context_cache_enabled:
        return None
    try:
        value = client().get(key(name))
        if value and ttl:
            client().expire(key(name), ttl)
        return json.loads(value) if value else None
    except Exception:
        log.debug("Redis read unavailable", exc_info=True)
        return None


def write(name, value, ttl):
    if not get_settings().context_cache_enabled:
        return
    try:
        client().set(key(name), json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except Exception:
        log.debug("Redis write unavailable", exc_info=True)
