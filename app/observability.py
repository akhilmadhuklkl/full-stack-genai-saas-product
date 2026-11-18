import logging
import re
import secrets
import time
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("forge_review")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RequestLoggingMiddleware:
    """Log request metadata without logging credentials or request bodies."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_request_id = dict(scope.get("headers", [])).get(b"x-request-id", b"").decode(
            "ascii", errors="ignore"
        )
        request_id = (
            incoming_request_id
            if REQUEST_ID_PATTERN.fullmatch(incoming_request_id)
            else str(uuid4())
        )
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


class SecurityHeadersMiddleware:
    """Add browser security headers without exposing application secrets."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; style-src 'self' 'unsafe-inline'",
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class CSRFMiddleware:
    """Protect cookie-authenticated state changes with a double-submit token."""

    protected_methods = {"POST", "PUT", "PATCH", "DELETE"}
    exempt_prefixes = ("/api/v1/auth/", "/health", "/metrics", "/docs", "/redoc", "/openapi.json")

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in self.protected_methods:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(self.exempt_prefixes):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("ascii", errors="ignore")
        cookies = {
            item.split("=", 1)[0].strip(): item.split("=", 1)[1].strip()
            for item in headers.get(b"cookie", b"").decode("ascii", errors="ignore").split("; ")
            if "=" in item
        }
        access_cookie = cookies.get("forge_access_token")
        csrf_cookie = cookies.get("forge_csrf_token")
        csrf_header = headers.get(b"x-csrf-token", b"").decode("ascii", errors="ignore")
        csrf_invalid = not csrf_cookie or not csrf_header or not secrets.compare_digest(
            csrf_cookie, csrf_header
        )
        uses_bearer_auth = authorization.lower().startswith("bearer ")
        if access_cookie and not uses_bearer_auth and csrf_invalid:
            from starlette.responses import PlainTextResponse

            await PlainTextResponse("CSRF validation failed", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


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
