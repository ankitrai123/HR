"""Admin accounts: password hashing, login sessions and rate limiting.

* Passwords are hashed with scrypt (standard library) and a per-user salt.
* A login creates a server-side session; the browser gets an opaque random
  token in an HttpOnly, SameSite=Strict cookie. Only its SHA-256 hash is
  stored, so a database leak doesn't expose usable sessions.
* Each session also has a CSRF token that the admin app must echo in the
  X-CSRF-Token header on every state-changing request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select

from database_models import AdminSession, AdminUser, Database, as_utc, utcnow

SESSION_COOKIE = "admin_session"
SESSION_TTL = timedelta(hours=12)
MIN_PASSWORD_LENGTH = 10

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(base64.b64decode(digest)))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Password must mix upper- and lower-case letters and include a number."
    return None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Verifying against this when the email is unknown keeps login timing uniform.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class LoginRateLimiter:
    """At most `max_failures` failed logins per (email, client) per window."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900):
        self.max_failures, self.window = max_failures, window_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple[str, str]) -> list[float]:
        cutoff = time.monotonic() - self.window
        attempts = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = attempts
        return attempts

    def blocked(self, email: str, client: str) -> bool:
        with self._lock:
            return len(self._recent((email, client))) >= self.max_failures

    def fail(self, email: str, client: str) -> None:
        with self._lock:
            self._recent((email, client)).append(time.monotonic())

    def reset(self, email: str, client: str) -> None:
        with self._lock:
            self._failures.pop((email, client), None)


@dataclass
class AdminIdentity:
    id: int | None  # None for API-key access
    email: str
    name: str
    csrf_token: str | None = None


class AuthService:
    def __init__(self, db: Database):
        self.db = db
        self.limiter = LoginRateLimiter()

    # -- accounts -------------------------------------------------------------

    def admin_count(self) -> int:
        with self.db.session() as s:
            return s.scalar(select(func.count()).select_from(AdminUser)) or 0

    def create_admin(self, email: str, name: str, password: str) -> AdminUser:
        email = email.strip().lower()
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        with self.db.session() as s:
            if s.scalar(select(AdminUser).where(AdminUser.email == email)):
                raise ValueError("An admin with this email already exists.")
            user = AdminUser(email=email, name=name.strip(), password_hash=hash_password(password))
            s.add(user)
            s.flush()
            return user

    def list_admins(self) -> list[AdminUser]:
        with self.db.session() as s:
            return list(s.scalars(select(AdminUser).order_by(AdminUser.created_at)))

    def delete_admin(self, admin_id: int) -> None:
        with self.db.session() as s:
            if (s.scalar(select(func.count()).select_from(AdminUser)) or 0) <= 1:
                raise ValueError("You can't remove the last admin account.")
            s.execute(delete(AdminSession).where(AdminSession.admin_id == admin_id))
            user = s.get(AdminUser, admin_id)
            if user is None:
                raise LookupError("admin not found")
            s.delete(user)

    def change_password(self, admin_id: int, current: str, new: str) -> None:
        problem = password_problem(new)
        if problem:
            raise ValueError(problem)
        with self.db.session() as s:
            user = s.get(AdminUser, admin_id)
            if user is None or not verify_password(current, user.password_hash):
                raise PermissionError("Current password is incorrect.")
            user.password_hash = hash_password(new)

    # -- sessions -------------------------------------------------------------

    def authenticate(self, email: str, password: str) -> AdminUser | None:
        with self.db.session() as s:
            user = s.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
            if user is None:
                verify_password(password, _DUMMY_HASH)
                return None
            if not verify_password(password, user.password_hash):
                return None
            return user

    def create_session(self, admin_id: int) -> tuple[str, str]:
        """Returns (cookie token, csrf token)."""
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.db.session() as s:
            s.execute(delete(AdminSession).where(AdminSession.expires_at < utcnow()))
            user = s.get(AdminUser, admin_id)
            if user is not None:
                user.last_login_at = utcnow()
            s.add(AdminSession(token_hash=token_hash(token), admin_id=admin_id, csrf_token=csrf,
                               expires_at=utcnow() + SESSION_TTL))
        return token, csrf

    def resolve_session(self, token: str) -> AdminIdentity | None:
        with self.db.session() as s:
            session = s.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash(token)))
            if session is None or as_utc(session.expires_at) <= utcnow():
                return None
            user = s.get(AdminUser, session.admin_id)
            if user is None:
                return None
            session.expires_at = utcnow() + SESSION_TTL  # sliding expiry
            return AdminIdentity(user.id, user.email, user.name, session.csrf_token)

    def end_session(self, token: str) -> None:
        with self.db.session() as s:
            s.execute(delete(AdminSession).where(AdminSession.token_hash == token_hash(token)))

    def end_other_sessions(self, admin_id: int, keep_token: str | None) -> None:
        with self.db.session() as s:
            query = delete(AdminSession).where(AdminSession.admin_id == admin_id)
            if keep_token:
                query = query.where(AdminSession.token_hash != token_hash(keep_token))
            s.execute(query)
