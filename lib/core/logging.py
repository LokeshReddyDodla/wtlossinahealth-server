import os
import logging
from logging import handlers

import structlog
from rich.logging import RichHandler
from decouple import config


ENV = os.getenv("ENV", "dev")

LOG_ROTATE_WHEN = config("LOG_ROTATE_WHEN", default="W6")
LOG_ROTATE_BACKUP = config("LOG_ROTATE_BACKUP", default=4, cast=int)


def setup_logging(app):
    handlers_list = []

    # ---- File handler (always on) ----
    file_handler = handlers.TimedRotatingFileHandler(
        filename="logs/rest_server.log",
        when=LOG_ROTATE_WHEN,  # type: ignore
        backupCount=LOG_ROTATE_BACKUP,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    handlers_list.append(file_handler)

    # ---- Console handler (dev only) ----
    if ENV == "dev":
        handlers_list.append(
            RichHandler(
                rich_tracebacks=True,
                tracebacks_show_locals=True,
                show_time=True,
                show_level=True,
                show_path=False,
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers_list,
    )

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("lib.core.postgres_store").setLevel(logging.WARNING)

    # Structlog configuration
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if ENV == "dev":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.AsyncBoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    app.state.logger = structlog.get_logger("rest_server")
