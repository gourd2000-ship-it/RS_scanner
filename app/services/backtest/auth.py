"""Server-side password session and CSRF checks for backtest routes only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
import secrets

from sqlalchemy.orm import Session

from app.repositories.backtest_repository import BacktestRepository


class InvalidCsrfToken(PermissionError):
    """Raised when a session-bound CSRF token is absent or invalid."""


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class BacktestOperatorAuthService:
    """Issues short-lived opaque sessions without persisting any credential plaintext."""

    def __init__(
        self, session: Session, *, password: str | None, max_failures: int = 5,
        lock_minutes: int = 15,
    ) -> None:
        self.repository = BacktestRepository(session)
        self.password = password
        self.max_failures = max_failures
        self.lock_minutes = lock_minutes

    @staticmethod
    def subject_hash(request_subject: str) -> str:
        # This can be a peer IP or another request-local opaque value.  It is
        # salted by its purpose so it cannot be joined to unrelated audit data.
        return _hash(f"backtest-login-subject:{request_subject}")

    @staticmethod
    def _token() -> str:
        return secrets.token_urlsafe(32)

    def issue_pre_auth(
        self, *, request_subject: str, request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[str, str]:
        now = now or datetime.now(timezone.utc)
        subject_hash = self.subject_hash(request_subject)
        session_token, csrf_token = self._token(), self._token()
        self.repository.create_operator_session(
            session_token_hash=_hash(session_token), csrf_token_hash=_hash(csrf_token),
            operator_subject_hash=subject_hash, expires_at=now + timedelta(minutes=15), is_operator=False,
        )
        self.repository.record_operator_audit(
            subject_hash=subject_hash, event_type="preauth_issued", result="success", request_id=request_id, now=now,
        )
        return session_token, csrf_token

    def login(
        self, *, preauth_token: str, csrf_token: str, password: str, request_subject: str,
        request_id: str | None = None, now: datetime | None = None,
    ) -> tuple[str, str]:
        now = now or datetime.now(timezone.utc)
        subject_hash = self.subject_hash(request_subject)
        if not self.password:
            raise RuntimeError("backtest operator password is not configured")
        if self.repository.is_login_locked(subject_hash=subject_hash, now=now):
            self.repository.record_operator_audit(subject_hash=subject_hash, event_type="login", result="locked", request_id=request_id, now=now)
            raise TimeoutError("login temporarily locked")
        preauth = self.repository.get_active_operator_session_with_csrf(
            session_token_hash=_hash(preauth_token), csrf_token_hash=_hash(csrf_token), now=now,
            require_operator=False,
        )
        if preauth is None or preauth.is_operator:
            self.repository.record_operator_audit(subject_hash=subject_hash, event_type="login", result="csrf_rejected", request_id=request_id, now=now)
            raise InvalidCsrfToken("valid pre-auth CSRF token is required")
        if not compare_digest(password, self.password):
            lockout = self.repository.record_login_failure(
                subject_hash=subject_hash, now=now, max_failures=self.max_failures,
                lock_duration=timedelta(minutes=self.lock_minutes), window=timedelta(minutes=self.lock_minutes),
            )
            self.repository.record_operator_audit(
                subject_hash=subject_hash, event_type="login", result="locked" if lockout else "failed",
                request_id=request_id, now=now,
            )
            if lockout:
                raise TimeoutError("login temporarily locked")
            raise PermissionError("invalid operator password")
        self.repository.revoke_operator_session(session_token_hash=_hash(preauth_token), now=now)
        self.repository.record_login_success(subject_hash=subject_hash, now=now)
        operator_token, operator_csrf = self._token(), self._token()
        self.repository.create_operator_session(
            session_token_hash=_hash(operator_token), csrf_token_hash=_hash(operator_csrf),
            operator_subject_hash=subject_hash, expires_at=now + timedelta(hours=8), is_operator=True,
        )
        self.repository.record_operator_audit(subject_hash=subject_hash, event_type="login", result="success", request_id=request_id, now=now)
        return operator_token, operator_csrf

    def find_operator(self, session_token: str, *, now: datetime | None = None):
        row = self.repository.get_active_operator_session(
            session_token_hash=_hash(session_token), now=now or datetime.now(timezone.utc)
        )
        return row if row is not None and row.is_operator else None

    def require_operator(self, session_token: str, csrf_token: str, *, now: datetime | None = None):
        row = self.repository.get_active_operator_session_with_csrf(
            session_token_hash=_hash(session_token), csrf_token_hash=_hash(csrf_token),
            now=now or datetime.now(timezone.utc), require_operator=True,
        )
        if row is None:
            raise PermissionError("operator session is required")
        return row

    def logout(self, session_token: str, csrf_token: str, *, request_id: str | None = None, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        row = self.require_operator(session_token, csrf_token, now=now)
        self.repository.revoke_operator_session(session_token_hash=_hash(session_token), now=now)
        self.repository.record_operator_audit(
            subject_hash=row.operator_subject_hash, event_type="logout", result="success", request_id=request_id, now=now,
        )
