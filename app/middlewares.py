import time
import uuid

import structlog
from fastapi import Request

from lib.core.server_context import Context


async def create_context(request: Request, call_next):
    """
    Create server context and bind it to the request
    Also bind request context variables to the logger
    """
    start_time = time.perf_counter()

    # Reuse incoming request ID if provided
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex

    # Create context
    server_context = Context(
        logger=request.app.state.logger,
        request_id=request_id,
        cache_store=request.app.state.cache_store,
        secret_store=request.app.state.secret_store,
        session_store=request.app.state.session_store,
        otp_store=request.app.state.otp_store,
        config_store=request.app.state.config_store,
        rate_limit_store=request.app.state.rate_limit_store,
        address_mapping_store=request.app.state.address_mapping_store,
        postgres_store=request.app.state.postgres_store,
        mongo_store=request.app.state.mongo_store,
        clickhouse_store=request.app.state.clickhouse_store,
        qdrant_store=request.app.state.qdrant_store,
    )

    # Bind vars to structlog logger
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    # Bind context to request state
    request.state.context = server_context

    # Log request path and method
    logger = structlog.get_logger("rest_server")
    await logger.info(
        "Request received",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        query_params=str(request.query_params) if request.query_params else None,
    )

    # Process API call
    response = await call_next(request)

    # Add tracing headers
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(
        int((time.perf_counter() - start_time) * 1000)
    )

    return response
