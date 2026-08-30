import logging
import os
import sys
from logging import handlers

import structlog
from decouple import config

ENV = os.getenv("ENV", "dev")

LOG_ROTATE_WHEN = config("LOG_ROTATE_WHEN", default="W6")
LOG_ROTATE_BACKUP = config("LOG_ROTATE_BACKUP", default=4, cast=int)


def setup_logging(app):
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    file_handler = handlers.TimedRotatingFileHandler(
        filename="logs/rest_server.log",
        when=LOG_ROTATE_WHEN,  # type: ignore
        backupCount=LOG_ROTATE_BACKUP,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)
    file_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    for name in (
        "uvicorn.access",
        "uvicorn.error",
        "lib.core.postgres_store",
        "httpx", "httpcore",
        "litellm", "LiteLLM",
        "openai",
        "boto3", "botocore", "s3transfer",
        "urllib3",
        "qdrant_client",
        "grpc",
        "socketio", "engineio",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("instructor").setLevel(logging.ERROR)

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.stdlib.AsyncBoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    app.state.logger = structlog.get_logger("rest_server")
