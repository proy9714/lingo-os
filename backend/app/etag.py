"""Revalidation for API answers: an unchanged answer costs a few bytes instead of the whole body.

Every successful GET /api/... that answers JSON gets an ETag (a short hash of the body) and
"Cache-Control: private, no-cache": the browser keeps the answer but asks each time whether it changed. When the body
is the same as the one it already has (If-None-Match), the answer is "304 Not Modified" with no body. The server
still does the work; what's saved is the transfer and the parsing (lists of suggestions, word lists, the library).

Streams (Server-Sent Events), files and anything that isn't JSON pass through untouched, as do answers that already
set their own Cache-Control.
"""

from __future__ import annotations

import hashlib

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY = 8 * 1024 * 1024  # larger answers aren't hashed (they pass through as they are)


class ETagMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        wanted = Headers(scope=scope).get("if-none-match")
        start: Message | None = None
        chunks: list[bytes] = []
        size = 0
        passing = False  # not something we tag: forward as it comes

        async def wrapped(message: Message) -> None:
            nonlocal start, size, passing
            if passing:
                await send(message)
                return
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                taggable = (
                    message["status"] == 200
                    and headers.get("content-type", "").startswith("application/json")
                    and "cache-control" not in headers
                    and "etag" not in headers
                )
                if not taggable:
                    passing = True
                    await send(message)
                    return
                start = message
                return
            if message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                size += len(chunks[-1])
                if size > MAX_BODY:  # too big to hold: give up tagging and send what we have
                    passing = True
                    assert start is not None
                    await send(start)
                    await send({"type": "http.response.body", "body": b"".join(chunks), "more_body": message.get("more_body", False)})
                    return
                if message.get("more_body", False):
                    return
                assert start is not None
                body = b"".join(chunks)
                etag = 'W/"' + hashlib.blake2b(body, digest_size=12).hexdigest() + '"'
                headers = MutableHeaders(raw=start["headers"])
                headers["ETag"] = etag
                headers["Cache-Control"] = "private, no-cache"
                if wanted and etag in {t.strip() for t in wanted.split(",")}:
                    if "content-length" in headers:
                        del headers["content-length"]
                    if "content-type" in headers:
                        del headers["content-type"]
                    await send({**start, "status": 304, "headers": headers.raw})
                    await send({"type": "http.response.body", "body": b""})
                    return
                await send({**start, "headers": headers.raw})
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped)
