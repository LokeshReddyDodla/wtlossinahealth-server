import uuid

import structlog
from fastapi import Request

from lib.core.server_context import Context


async def create_context(request: Request, call_next):
    """
    Create server context and bind it to the request
    Also bind request context variables to the logger
    """
    # Generate request ID
    request_id = uuid.uuid4().hex

    # Create context
    server_context = Context(
        logger=request.app.logger,
        request_id=request_id,
        cache_store=request.app.cache_store,
        secret_store=request.app.secret_store,
        session_store=request.app.session_store,
        otp_store=request.app.otp_store,
        config_store=request.app.config_store,
        rate_limit_store=request.app.rate_limit_store,
        address_mapping_store=request.app.address_mapping_store,
        postgres_store=request.app.postgres_store,
        mongo_store=request.app.mongo_store,
        influx_store=request.app.influx_store,
    )

    # Bind vars to structlog logger
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        url=request.url.path,
        request_id=request_id,
    )

    # Bind context to request state
    request.state.context = server_context

    # Process API call
    response = await call_next(request)

    return response
