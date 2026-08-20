"""Hermes Agent API 인증과 scope 검증."""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address, ip_network
import logging

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentPrincipal:
    """원문 token을 노출하지 않는 인증 주체."""

    token_id: str
    scopes: frozenset[str]


def parse_service_tokens(spec: str | None) -> tuple[tuple[str, frozenset[str]], ...]:
    """token=scopes 형식의 rotation 목록을 파싱한다.

    예: token-a=rs:read,stock:read;token-b=status:read
    """
    parsed: list[tuple[str, frozenset[str]]] = []
    for entry in (spec or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        token, separator, raw_scopes = entry.partition("=")
        if not separator or not token.strip():
            continue
        scopes = frozenset(
            scope.strip()
            for scope in raw_scopes.split(",")
            if scope.strip()
        )
        if scopes:
            parsed.append((token.strip(), scopes))
    return tuple(parsed)


def parse_allowed_networks(spec: str | None) -> tuple:
    networks = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ip_network(item, strict=False))
        except ValueError:
            logger.warning("ignoring invalid AGENT_ALLOWED_IPS entry")
    return tuple(networks)


class AgentAuthenticator:
    """Bearer token, scope, IP allowlist를 검증한다."""

    def __init__(
        self,
        *,
        token_spec: str | None,
        allowed_ips: str | None = None,
    ) -> None:
        self._tokens = parse_service_tokens(token_spec)
        self._networks = parse_allowed_networks(allowed_ips)

    def authenticate(
        self,
        *,
        authorization: str | None,
        client_ip: str | None,
        required_scope: str,
    ) -> AgentPrincipal:
        if self._networks:
            try:
                address = ip_address(client_ip or "")
            except ValueError:
                address = None
            if address is None or not any(address in network for network in self._networks):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Agent client IP is not allowed",
                )

        if not authorization:
            raise self._unauthorized()

        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token:
            raise self._unauthorized()

        for configured_token, scopes in self._tokens:
            if compare_digest(token, configured_token):
                if required_scope not in scopes:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Missing scope: {required_scope}",
                    )
                return AgentPrincipal(
                    token_id=sha256(configured_token.encode("utf-8")).hexdigest()[:16],
                    scopes=scopes,
                )

        raise self._unauthorized()

    @staticmethod
    def _unauthorized() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _client_ip(request: Request) -> str | None:
    # Internal agent routes are bound directly to host loopback.  There is no
    # trusted reverse proxy in this path, so a caller-controlled
    # X-Forwarded-For header must not influence the IP allowlist decision.
    return request.client.host if request.client else None


def require_agent_scope(required_scope: str):
    """FastAPI dependency factory for read-only agent scopes."""

    def dependency(request: Request) -> AgentPrincipal:
        settings = get_settings()
        if not settings.agent_api_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        principal = AgentAuthenticator(
            token_spec=settings.agent_service_tokens,
            allowed_ips=settings.agent_allowed_ips,
        ).authenticate(
            authorization=request.headers.get("authorization"),
            client_ip=_client_ip(request),
            required_scope=required_scope,
        )
        request.state.agent_principal = principal
        return principal

    return dependency


def require_repair_scope(required_scope: str):
    """FastAPI dependency for the separately gated Sam repair API."""

    def dependency(request: Request) -> AgentPrincipal:
        settings = get_settings()
        if not settings.repair_api_enabled or not settings.legacy_repair_api_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        principal = AgentAuthenticator(
            token_spec=settings.agent_service_tokens,
            allowed_ips=settings.agent_allowed_ips,
        ).authenticate(
            authorization=request.headers.get("authorization"),
            client_ip=_client_ip(request),
            required_scope=required_scope,
        )
        request.state.agent_principal = principal
        return principal

    return dependency


def require_analysis_scope(required_scope: str):
    """Authenticate the separately enabled crawl-quality analysis API."""

    def dependency(request: Request) -> AgentPrincipal:
        settings = get_settings()
        if not settings.analysis_api_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        principal = AgentAuthenticator(
            token_spec=settings.agent_service_tokens,
            allowed_ips=settings.agent_allowed_ips,
        ).authenticate(
            authorization=request.headers.get("authorization"),
            client_ip=_client_ip(request),
            required_scope=required_scope,
        )
        request.state.agent_principal = principal
        return principal

    return dependency
