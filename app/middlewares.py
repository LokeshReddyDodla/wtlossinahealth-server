import time
import uuid

import structlog
from fastapi import Request

from lib.core.server_context import Context


_SKIP_LOG_PREFIXES = ("/health/", "/healthz")
_SKIP_LOG_PATHS = {"/", "/health", "/healthz", "/favicon.ico"}

SLOW_REQUEST_MS = 1000


async def create_context(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    path = request.url.path
    skip_log = path in _SKIP_LOG_PATHS or path.startswith(_SKIP_LOG_PREFIXES)

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

    request.state.context = server_context

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    logger = request.app.state.logger

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        await logger.exception(
            "request.error",
            duration_ms=duration_ms,
            lifecycle="request",
        )
        raise

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    if not skip_log:
        is_error = status_code >= 400
        is_slow = duration_ms >= SLOW_REQUEST_MS
        is_mutation = request.method in ("POST", "PUT", "PATCH", "DELETE")

        if is_error or is_slow or is_mutation:
            log = logger.warning if (is_error or is_slow) else logger.info
            await log(
                "request",
                status_code=status_code,
                duration_ms=duration_ms,
                lifecycle="request",
            )

    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(duration_ms)

    return response
