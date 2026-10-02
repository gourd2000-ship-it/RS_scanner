"""Unregistered support router for the protected browser backtest feature.

The application router is deliberately not changed here; the feature API task
registers this router once it owns the complete protected route surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db_session
from app.schemas.backtest_common import BacktestCsrfResponse, BacktestLoginRequest, BacktestLoginResponse, BacktestLogoutResponse
from app.services.backtest.auth import BacktestOperatorAuthService, InvalidCsrfToken


router = APIRouter(prefix="/auth")
_PREAUTH_COOKIE = "rs_backtest_preauth"
_OPERATOR_COOKIE = "rs_backtest_operator"


def _client_subject(request: Request) -> str:
    # Do not trust forwarding headers unless a future deployment explicitly
    # installs trusted-proxy middleware.
    return request.client.host if request.client else "unknown"


def _service(session: Session) -> BacktestOperatorAuthService:
    settings = get_settings()
    return BacktestOperatorAuthService(
        session, password=settings.backtest_operator_password,
        max_failures=settings.backtest_login_max_failures,
        lock_minutes=settings.backtest_login_lock_minutes,
    )


def _set_cookie(response: Response, key: str, value: str, *, max_age: int) -> None:
    response.set_cookie(
        key=key, value=value, max_age=max_age, httponly=True, secure=True,
        samesite="strict", path="/api/v1/backtests",
    )


def _csrf_header(request: Request) -> str:
    token = request.headers.get("X-CSRF-Token", "")
    if not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token is required")
    return token


def require_backtest_operator(request: Request, session: Session = Depends(get_db_session)):
    token = request.cookies.get(_OPERATOR_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator session is required")
    row = _service(session).find_operator(token)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator session is required")
    return row


def require_backtest_csrf(
    request: Request, session: Session = Depends(get_db_session),
):
    token = request.cookies.get(_OPERATOR_COOKIE)
    csrf_token = _csrf_header(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator session is required")
    try:
        return _service(session).require_operator(token, csrf_token)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token") from exc


@router.get("/csrf", response_model=BacktestCsrfResponse)
def issue_csrf(request: Request, response: Response, session: Session = Depends(get_db_session)):
    preauth_token, csrf_token = _service(session).issue_pre_auth(
        request_subject=_client_subject(request), request_id=getattr(request.state, "request_id", None)
    )
    session.commit()
    _set_cookie(response, _PREAUTH_COOKIE, preauth_token, max_age=15 * 60)
    return BacktestCsrfResponse(csrf_token=csrf_token)


@router.post("/login", response_model=BacktestLoginResponse)
def login(
    body: BacktestLoginRequest, request: Request, response: Response,
    session: Session = Depends(get_db_session),
):
    preauth_token = request.cookies.get(_PREAUTH_COOKIE, "")
    try:
        operator_token, csrf_token = _service(session).login(
            preauth_token=preauth_token, csrf_token=_csrf_header(request), password=body.password,
            request_subject=_client_subject(request), request_id=getattr(request.state, "request_id", None),
        )
        session.commit()
    except TimeoutError as exc:
        session.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="login temporarily locked") from exc
    except (PermissionError, InvalidCsrfToken) as exc:
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login failed") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="backtest operator access is unavailable") from exc
    _set_cookie(response, _OPERATOR_COOKIE, operator_token, max_age=8 * 3600)
    response.delete_cookie(_PREAUTH_COOKIE, path="/api/v1/backtests")
    return BacktestLoginResponse(csrf_token=csrf_token)


@router.post("/logout", response_model=BacktestLogoutResponse)
def logout(
    request: Request, response: Response, session: Session = Depends(get_db_session),
):
    token = request.cookies.get(_OPERATOR_COOKIE, "")
    try:
        _service(session).logout(token, _csrf_header(request), request_id=getattr(request.state, "request_id", None))
        session.commit()
    except (PermissionError, InvalidCsrfToken) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator session is required") from exc
    response.delete_cookie(_OPERATOR_COOKIE, path="/api/v1/backtests")
    return BacktestLogoutResponse()
