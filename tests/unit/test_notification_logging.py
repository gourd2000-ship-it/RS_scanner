import logging

from app.core.logging import configure_logging
from app.core.notification import NotificationService


def test_httpx_request_urls_are_not_logged_at_info_level(monkeypatch):
    root_logger = logging.getLogger()
    httpx_logger = logging.getLogger("httpx")
    monkeypatch.setattr(root_logger, "level", logging.INFO)
    monkeypatch.setattr(httpx_logger, "level", logging.NOTSET)

    configure_logging()

    assert httpx_logger.getEffectiveLevel() >= logging.WARNING


def test_telegram_request_exception_does_not_log_bot_token(monkeypatch, caplog):
    class FailingClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            raise RuntimeError(
                "request failed for https://api.telegram.org/botsecret-token/sendMessage"
            )

    service = NotificationService()
    service.telegram_enabled = True
    service.telegram_bot_token = "secret-token"
    service.telegram_chat_id = "chat"
    monkeypatch.setattr("app.core.notification.httpx.Client", FailingClient)

    with caplog.at_level(logging.ERROR):
        assert service.send_step_completed_sync("symbols", 1, 0.1) is False

    assert "Unexpected error sending telegram step notification" in caplog.text
    assert "secret-token" not in caplog.text
