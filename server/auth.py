"""用户名密码登录与可撤销会话，不使用共享导入口令。"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pymysql
import database
from security import hash_password, normalize_username, token_digest, verify_password


class InvalidLogin(Exception):
    pass


class UsernameTaken(Exception):
    pass


class RateLimited(Exception):
    pass


DUMMY_HASH = hash_password("not-a-real-account-password")


def utc_now():
    # MySQL DATETIME不含时区；统一约定按UTC存储。
    return datetime.now(timezone.utc).replace(tzinfo=None)


def consume_rate_limit(action, subject, maximum, seconds):
    """跨进程数据库限速；subject不可逆散列后存储，不信任X-Forwarded-For。"""
    bucket = hashlib.sha256(f"{action}:{subject}".encode()).hexdigest()
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s,5) AS acquired", ("auth:" + bucket[:55],))
            if cursor.fetchone()["acquired"] != 1:
                raise RateLimited()
            now = utc_now()
            cursor.execute("DELETE FROM auth_rate_limits WHERE reset_at < %s", (now,))
            cursor.execute("SELECT hits,reset_at FROM auth_rate_limits WHERE bucket_key=%s", (bucket,))
            row = cursor.fetchone()
            if row and row["hits"] >= maximum:
                raise RateLimited()
            if row:
                cursor.execute("UPDATE auth_rate_limits SET hits=hits+1 WHERE bucket_key=%s", (bucket,))
            else:
                cursor.execute("INSERT INTO auth_rate_limits (bucket_key,hits,reset_at) VALUES (%s,%s,%s)",
                               (bucket, 1, now + timedelta(seconds=seconds)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_session(cursor, user):
    token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(hours=24)
    cursor.execute("DELETE FROM auth_sessions WHERE expires_at < %s", (utc_now(),))
    cursor.execute("INSERT INTO auth_sessions (token_hash,user_id,expires_at) VALUES (%s,%s,%s)",
                   (token_digest(token), user["id"], expires))
    return {"access_token": token, "token_type": "bearer", "expires_in": 86400,
            "user": {"id": user["id"], "username": user["username"]}}


def register(username, password):
    username = normalize_username(username)
    encoded = hash_password(password)
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO users (username,password_hash) VALUES (%s,%s)", (username, encoded))
            user = {"id": cursor.lastrowid, "username": username}
            cursor.execute("INSERT INTO schedules (user_id,label,semester_start) VALUES (%s,%s,%s)",
                           (user["id"], "我的课表", database.semester_start()))
            result = create_session(cursor, user)
        connection.commit()
        return result
    except pymysql.IntegrityError as error:
        connection.rollback()
        if error.args[0] == 1062:
            raise UsernameTaken() from error
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def login(username, password):
    username = normalize_username(username)
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id,username,password_hash FROM users WHERE username=%s", (username,))
            user = cursor.fetchone()
            valid = verify_password(password, user["password_hash"] if user else DUMMY_HASH)
            if not user or not valid:
                raise InvalidLogin()
            result = create_session(cursor, user)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def authenticate(token):
    if not token or len(token) > 256:
        raise InvalidLogin()
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT u.id,u.username FROM auth_sessions a
                JOIN users u ON u.id=a.user_id WHERE a.token_hash=%s AND a.expires_at > %s""",
                           (token_digest(token), utc_now()))
            user = cursor.fetchone()
        if not user:
            raise InvalidLogin()
        return user
    finally:
        connection.close()


def logout(token):
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (token_digest(token),))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
