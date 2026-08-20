"""KRX Open API HTTP client."""

from typing import Any, Protocol

import httpx

from app.core.config import get_settings


_UNSET = object()


class KrxUniverseFetchError(RuntimeError):
    """KRX 유니버스 API 요청을 안전하게 완료할 수 없을 때 발생한다."""


class KrxHttpTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> Any: ...


class KrxHttpClient:
    """인증키를 request header로만 전달하는 KRX JSON client."""

    def __init__(
        self,
        *,
        auth_key: str | None | object = _UNSET,
        base_url: str | None | object = _UNSET,
        endpoint_urls: dict[str, str] | None | object = _UNSET,
        http_client: KrxHttpTransport | None = None,
    ) -> None:
        self.auth_key = (
            get_settings().krx_auth_key if auth_key is _UNSET else auth_key
        )
        configured_base_url = (
            get_settings().krx_api_base_url if base_url is _UNSET else base_url
        )
        self.base_url = configured_base_url.rstrip("/") if configured_base_url else None
        settings = get_settings()
        configured_endpoint_urls = {
            "stk_bydd_trd": settings.krx_stk_bydd_trd_url,
            "ksq_bydd_trd": settings.krx_ksq_bydd_trd_url,
            "stk_isu_base_info": settings.krx_stk_isu_base_info_url,
            "ksq_isu_base_info": settings.krx_ksq_isu_base_info_url,
            "etf_bydd_trd": settings.krx_etf_bydd_trd_url,
            "etn_bydd_trd": settings.krx_etn_bydd_trd_url,
        }
        if endpoint_urls is _UNSET:
            endpoint_url_values = configured_endpoint_urls if base_url is _UNSET else {}
        else:
            endpoint_url_values = endpoint_urls or {}
        self.endpoint_urls = {
            api_id: url.rstrip("/")
            for api_id, url in endpoint_url_values.items()
            if url
        }
        self._client = http_client or httpx.Client(timeout=20.0)

    def get_json(self, api_id: str, *, params: dict[str, str]) -> dict:
        if not self.auth_key:
            raise KrxUniverseFetchError("KRX_AUTH_KEY가 설정되지 않았습니다")
        endpoint_url = self.endpoint_urls.get(api_id)
        if not self.base_url and not endpoint_url:
            raise KrxUniverseFetchError("KRX_API_BASE_URL이 설정되지 않았습니다")

        url = endpoint_url or f"{self.base_url}/{api_id}"
        if not url.endswith(".json"):
            url = f"{url}.json"
        try:
            response = self._client.get(
                url,
                headers={"AUTH_KEY": self.auth_key},
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise KrxUniverseFetchError(
                f"KRX API 요청에 실패했습니다: {type(exc).__name__}"
            ) from exc
        except ValueError as exc:
            raise KrxUniverseFetchError("KRX API JSON 응답을 해석할 수 없습니다") from exc

        if not isinstance(payload, dict):
            raise KrxUniverseFetchError("KRX API JSON 응답 형식이 올바르지 않습니다")
        return payload
