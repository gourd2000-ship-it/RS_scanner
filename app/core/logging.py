import logging


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # httpx logs complete request URLs at INFO; Telegram embeds its bot token
    # in the URL path, so those request lines must never enter batch logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
