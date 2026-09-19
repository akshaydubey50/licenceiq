"""Bound upload request bodies before Starlette's multipart parser consumes them."""

from typing import Any
from uuid import uuid4

from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.schemas.common import ErrorCode


class UploadBodyLimitMiddleware:
    """Reject oversized document uploads, including chunked bodies without a length."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] in {"/api/documents", "/api/documents/"}
        ):
            await self.app(scope, receive, send)
            return

        # Prevent a trailing-slash redirect from completing before a chunked body is read.
        if scope["path"] == "/api/documents/":
            scope = dict(scope)
            scope["path"] = "/api/documents"
            scope["raw_path"] = b"/api/documents"

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await self._send_invalid_length(scope, receive, send)
                return
            if declared_size < 0:
                await self._send_invalid_length(scope, receive, send)
                return
            if declared_size > self.max_bytes:
                await self._send_too_large(scope, receive, send)
                return

        consumed = 0
        exceeded = False
        buffered_messages: list[Message] = []

        async def bounded_receive() -> Message:
            nonlocal consumed, exceeded
            if exceeded:
                raise MultiPartException("Upload request exceeded its limit.")
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    exceeded = True
                    # Abort parsing instead of faking EOF: a complete file may already
                    # have arrived. The parser closes its spooled files on this exception
                    # and never reaches the endpoint that would persist that prefix.
                    raise MultiPartException("Upload request exceeded its limit.")
            return message

        async def buffered_send(message: Message) -> None:
            buffered_messages.append(message)

        await self.app(scope, bounded_receive, buffered_send)
        if exceeded:
            await self._send_too_large(scope, receive, send)
            return
        for message in buffered_messages:
            await send(message)

    @staticmethod
    def _request(scope: Scope, receive: Receive) -> Request:
        state: dict[str, Any] = scope.setdefault("state", {})
        state.setdefault("request_id", str(uuid4()))
        return Request(scope, receive=receive)

    async def _send_too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = self._request(scope, receive)
        response = error_response(
            request,
            code=ErrorCode.FILE_TOO_LARGE,
            message="The upload request is too large.",
            status_code=413,
        )
        await response(scope, receive, send)

    async def _send_invalid_length(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = self._request(scope, receive)
        response = error_response(
            request,
            code=ErrorCode.INVALID_REQUEST,
            message="The request has an invalid Content-Length header.",
            status_code=400,
        )
        await response(scope, receive, send)
