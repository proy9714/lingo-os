"""Signing in to a Lingo OS that runs on a server (LINGO_ACCESS_TOKEN).

On a laptop the app answers only this computer (127.0.0.1) and needs no sign-in. A server answers the network, so
when LINGO_ACCESS_TOKEN is set every /api/... request must carry it: the browser signs in once at /login (the token
is kept in an HttpOnly cookie for a year), scripts can send "Authorization: Bearer <token>".

Not covered, on purpose:
  /sync/...      phones prove themselves with their own pairing key on every request (app/sync/server.py)
  /api/health    so a monitor or the app can tell the server is up
  the app's own files (index.html, scripts, styles), so the page can load and send you to /login
"""

from __future__ import annotations

import hmac
from html import escape
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "lingo_access"
OPEN_PATHS = ("/api/health",)


def _matches(given: str | None, token: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), token.encode())


def _cookie(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode("latin-1").split(";"):
                key, _, val = part.strip().partition("=")
                if key == COOKIE:
                    return val
    return None


def _bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return None


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Lingo OS</title>
<style>
  body {{ margin:0; min-height:100dvh; display:grid; place-items:center; background:#0b0f1a; color:#e8ecf4;
         font:16px/1.5 system-ui, sans-serif; }}
  form {{ width:min(360px, 90vw); display:flex; flex-direction:column; gap:12px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }} p {{ margin:0; color:#a9b2c6; font-size:14px; }}
  input {{ padding:12px 14px; border-radius:12px; border:1px solid #2b3550; background:#141b2d; color:inherit; font:inherit; }}
  button {{ padding:12px; border:0; border-radius:999px; background:#f5b443; color:#1a1405; font-weight:700; font:inherit;
           cursor:pointer; }}
  .error {{ color:#ff9f6b; }}
</style></head>
<body><form method="post" action="/login">
  <h1>Lingo OS</h1>
  <p>This Lingo OS runs on a server. Enter its access token (LINGO_ACCESS_TOKEN in the server's settings).</p>
  {error}
  <input name="token" type="password" autocomplete="current-password" placeholder="Access token" autofocus required>
  <button type="submit">Sign in</button>
</form></body></html>"""


class AccessMiddleware:
    def __init__(self, app: ASGIApp, token: str, secure_cookie: bool = False) -> None:
        self.app = app
        self.token = token
        self.secure = secure_cookie

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        if path == "/login":
            response = await self._login(scope, receive)
            await response(scope, receive, send)
            return
        if path == "/logout":
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE)
            await response(scope, receive, send)
            return
        guarded = path.startswith("/api/") and path not in OPEN_PATHS
        if guarded and not (_matches(_cookie(scope), self.token) or _matches(_bearer(scope), self.token)):
            await JSONResponse({"detail": "sign in first", "login": "/login"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _login(self, scope: Scope, receive: Receive) -> Response:
        if scope["method"] != "POST":
            return HTMLResponse(LOGIN_PAGE.format(error=""))
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        given = (parse_qs(body.decode("utf-8", "replace")).get("token") or [""])[0].strip()
        if not _matches(given, self.token):
            return HTMLResponse(LOGIN_PAGE.format(error=f'<p class="error">{escape("That token is not right.")}</p>'), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, self.token, max_age=365 * 86400, httponly=True, samesite="lax", secure=self.secure)
        return response
