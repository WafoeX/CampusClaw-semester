"""Bound message JSON bytes before FastAPI/Pydantic buffers a request body."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ChatBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not path.startswith("/api/conversations/")
            or not path.endswith("/messages")
        ):
            await self.app(scope, receive, send)
            return
        # Four UTF-8 bytes per character plus a bounded JSON envelope allowance.
        limit = 4 * scope["app"].state.settings.CONVERSATION_MESSAGE_MAX_CHARS + 1_024
        chunks: list[bytes] = []
        used = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            used += len(chunk)
            if used > limit:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "message_too_large",
                            "message": "Message is too large",
                        }
                    },
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        buffered = False

        async def limited_receive() -> Message:
            nonlocal buffered
            if not buffered:
                buffered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, limited_receive, send)
