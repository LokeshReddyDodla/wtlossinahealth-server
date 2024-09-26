import structlog

from lib.core.logger import initialize_logger


def setup_logger(app):
    initialize_logger()
    app.state.logger = structlog.get_logger("rest_server")
