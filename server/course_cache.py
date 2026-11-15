"""Redis只缓存可重建的课表结果，不保存账户密码或登录凭据。"""
import json
import logging
import os
import time
from functools import lru_cache

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

logger = logging.getLogger(__name__)
_last_warning = -60.0


@lru_cache(maxsize=4)
def _client(url):
    return redis.Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=0.2,
        socket_timeout=0.2, max_connections=10,
        retry=Retry(NoBackoff(), 0),
    )


def client():
    url = os.environ.get("REDIS_URL", "").strip()
    return _client(url) if url else None


def ttl():
    try:
        return max(30, min(3600, int(os.environ.get("COURSE_CACHE_TTL", "300"))))
    except ValueError:
        return 300


def key(user_id, schedule_id, version, week):
    return f"p4schedule:courses:v1:u:{user_id}:s:{schedule_id}:r:{version}:w:{week if week is not None else 'all'}"


def warn(error):
    global _last_warning
    now = time.monotonic()
    if now - _last_warning >= 60:
        # 不输出Redis连接地址，避免带密码的URL进入日志。
        logger.warning("Redis缓存不可用，已回退到MySQL（%s）", type(error).__name__)
        _last_warning = now


def read(cache_key):
    try:
        connection = client()
        if connection is None:
            return None, "BYPASS"
        raw = connection.get(cache_key)
        if raw is None:
            return None, "MISS"
        value = json.loads(raw)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            return None, "MISS"
        return value, "HIT"
    except (redis.RedisError, OSError, ValueError, TypeError) as error:
        warn(error)
        return None, "BYPASS"


def write(cache_key, records):
    try:
        connection = client()
        if connection is None:
            return False
        connection.set(cache_key, json.dumps(records, ensure_ascii=False), ex=ttl())
        return True
    except (redis.RedisError, OSError, ValueError, TypeError) as error:
        warn(error)
        return False
