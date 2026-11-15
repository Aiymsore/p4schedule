"""密码仅保存加盐哈希；数据库只保存会话令牌摘要。"""
import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000


def normalize_username(username):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
        raise ValueError("用户名需为3至32位英文字母、数字或下划线")
    return username


def hash_password(password):
    if not 6 <= len(password) <= 128:
        raise ValueError("密码长度需为6至128个字符")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, encoded):
    try:
        kind, iterations, salt, expected = encoded.split("$")
        if kind != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
