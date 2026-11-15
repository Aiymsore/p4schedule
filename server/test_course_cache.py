import json
import time

import pytest
import redis

import course_cache
import database
from test_mysql_import import site, signup, schedule_id, entry, Cursor


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.now = 0
        self.reads = []

    def get(self, key):
        self.reads.append(key)
        value = self.values.get(key)
        if value is None or value[1] <= self.now:
            return None
        return value[0]

    def set(self, key, value, ex):
        assert ex == 300
        self.values[key] = (value, self.now + ex)


@pytest.fixture
def cache(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(course_cache, "client", lambda: fake)
    monkeypatch.setenv("COURSE_CACHE_TTL", "300")
    return fake


def test_first_query_misses_second_hits_without_course_join(site, cache, monkeypatch):
    client, _ = site
    user, headers = signup(client, "alice")
    sid = schedule_id(client, headers)
    database.import_courses([entry()], user["user"]["id"], sid)
    joins = []
    execute = Cursor.execute
    def count(cursor, sql, params=()):
        if "JOIN schedules t" in sql:
            joins.append(sql)
        return execute(cursor, sql, params)
    monkeypatch.setattr(Cursor, "execute", count)
    url = f"/api/courses?schedule_id={sid}&week=1"
    first = client.get(url, headers=headers)
    second = client.get(url, headers=headers)
    assert first.headers["x-cache"] == "MISS"
    assert second.headers["x-cache"] == "HIT"
    assert first.json() == second.json() and len(second.json()) == 1
    assert len(joins) == 1
    cache.now += 301
    assert client.get(url, headers=headers).headers["x-cache"] == "MISS"
    assert len(joins) == 2


def test_week_filter_and_empty_results_are_cached(site, cache):
    client, _ = site
    user, headers = signup(client, "alice")
    sid = schedule_id(client, headers)
    database.import_courses([entry(), {**entry("Other"), "date":"2026-09-14"}], user["user"]["id"], sid)
    first = client.get(f"/api/courses?schedule_id={sid}&week=1", headers=headers)
    assert [r["course"] for r in first.json()] == ["Ecology"]
    assert client.get(f"/api/courses?schedule_id={sid}&week=2", headers=headers).json()[0]["course"] == "Other"
    url = f"/api/courses?schedule_id={sid}&week=3"
    assert client.get(url, headers=headers).json() == []
    assert client.get(url, headers=headers).headers["x-cache"] == "HIT"
    assert client.get(f"/api/courses?schedule_id={sid}&week=0", headers=headers).status_code == 422


def test_cache_cannot_bypass_ownership(site, cache):
    client, _ = site
    alice, ha = signup(client, "alice")
    bob, hb = signup(client, "bob")
    sa, sb = schedule_id(client, ha), schedule_id(client, hb)
    database.import_courses([entry()], alice["user"]["id"], sa)
    assert len(client.get(f"/api/courses?schedule_id={sa}", headers=ha).json()) == 1
    before = len(cache.reads)
    assert client.get(f"/api/courses?schedule_id={sa}", headers=hb).status_code == 404
    assert len(cache.reads) == before  # 归属检查失败时连Redis都不读取
    assert client.get(f"/api/courses?schedule_id={sb}", headers=hb).json() == []
    assert len(cache.values) == 2
    assert any(f"u:{alice['user']['id']}:s:{sa}:" in key for key in cache.values)
    assert any(f"u:{bob['user']['id']}:s:{sb}:" in key for key in cache.values)


def test_import_and_clear_change_version_even_when_old_cache_still_exists(site, cache):
    client, raw = site
    user, headers = signup(client, "alice")
    uid = user["user"]["id"]
    sid = schedule_id(client, headers)
    url = f"/api/courses?schedule_id={sid}&week=1"
    assert client.get(url, headers=headers).json() == []
    old_key = next(iter(cache.values))
    database.import_courses([entry()], uid, sid)
    changed = client.get(url, headers=headers)
    assert changed.headers["x-cache"] == "MISS" and len(changed.json()) == 1
    assert old_key in cache.values  # 旧键尚未过期，但再也不会用于新版本
    version = raw.execute("SELECT cache_version FROM schedules WHERE id=?", (sid,)).fetchone()[0]
    assert database.import_courses([entry()], uid, sid)["skipped"] == 1
    assert raw.execute("SELECT cache_version FROM schedules WHERE id=?", (sid,)).fetchone()[0] == version
    assert client.get(url, headers=headers).headers["x-cache"] == "HIT"
    database.clear_schedule(uid, sid)
    assert client.get(url, headers=headers).json() == []


def test_redis_down_and_corrupt_cache_fall_back_to_mysql(site, cache, monkeypatch):
    client, _ = site
    user, headers = signup(client, "alice")
    sid = schedule_id(client, headers)
    database.import_courses([entry()], user["user"]["id"], sid)
    url = f"/api/courses?schedule_id={sid}"
    assert client.get(url, headers=headers).headers["x-cache"] == "MISS"
    for key in cache.values:
        cache.values[key] = ("not-json", 300)
    assert len(client.get(url, headers=headers).json()) == 1
    def down():
        raise redis.ConnectionError("synthetic outage")
    monkeypatch.setattr(course_cache, "client", down)
    response = client.get(url, headers=headers)
    assert response.status_code == 200 and response.headers["x-cache"] == "BYPASS"
    assert len(response.json()) == 1
    # Redis失败时仍能写MySQL，恢复后以数据库中的新版本为准。
    database.import_courses([entry("New")], user["user"]["id"], sid)
    monkeypatch.setattr(course_cache, "client", lambda: cache)
    assert len(client.get(url, headers=headers).json()) == 2


def test_failed_import_does_not_change_version_or_cached_results(site, cache):
    client, raw = site
    user, headers = signup(client, "alice")
    sid = schedule_id(client, headers)
    url = f"/api/courses?schedule_id={sid}"
    client.get(url, headers=headers)
    version = raw.execute("SELECT cache_version FROM schedules WHERE id=?", (sid,)).fetchone()[0]
    raw.executescript("""CREATE TRIGGER fail_session BEFORE INSERT ON course_sessions
        BEGIN SELECT RAISE(ABORT,'test failure'); END;""")
    import pymysql
    with pytest.raises(pymysql.IntegrityError):
        database.import_courses([entry()], user["user"]["id"], sid)
    assert raw.execute("SELECT cache_version FROM schedules WHERE id=?", (sid,)).fetchone()[0] == version
    response = client.get(url, headers=headers)
    assert response.json() == [] and response.headers["x-cache"] == "HIT"
