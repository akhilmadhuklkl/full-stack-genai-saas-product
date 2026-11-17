import logging
import time
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("forge_review")


class RequestLoggingMiddleware:
    """Log request metadata without logging credentials or request bodies."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                duration_ms,
            )


def validation_error_handler(_: Request, exception: RequestValidationError) -> JSONResponse:
    """Return a stable validation shape without echoing submitted values."""
    fields = [".".join(str(part) for part in error["loc"]) for error in exception.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "fields": fields},
    )


def unhandled_error_handler(request: Request, _: Exception) -> JSONResponse:
    """Return a safe error while keeping detailed diagnostics in server logs."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "unhandled_error request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "request_id": request_id},
    )
