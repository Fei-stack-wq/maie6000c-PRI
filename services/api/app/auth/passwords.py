"""Salted PBKDF2 hashes; passwords never enter audit payloads or CLI arguments."""

import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", username):
        raise ValueError("账号须为 3–64 位小写字母、数字、下划线、点或连字符，以字母开头。")
    return username


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 256 or not password.strip():
        raise ValueError("密码须为 12–256 个字符，不能全为空格。")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            int(iterations),
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# An unknown/disabled account still pays the same password verification cost.
DUMMY_HASH = f"pbkdf2_sha256${ITERATIONS}$unknown-account-salt$" + "0" * 64
