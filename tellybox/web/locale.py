"""Per-request interface language (NF-13), from the browser's Accept-Language header.

A plain ASGI middleware, so streaming responses (SSE) are untouched. It sets the
language for everything the request does (tellybox.i18n.use_locale) and tells caches
that pages differ per language.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tellybox import i18n

# Media and images are the same in every language.
_NO_VARY = ("/media/", "/img/", "/static/", "/admin/static/", "/healthz")


class LocaleMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = None
        for name, value in scope.get("headers") or []:
            if name == b"accept-language":
                header = value.decode("latin-1")
                break
        lang = i18n.negotiate(header)
        varies = not scope.get("path", "").startswith(_NO_VARY)

        async def send_with_headers(message: Message) -> None:
            if varies and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Language"] = lang
                headers.add_vary_header("Accept-Language")
            await send(message)

        with i18n.use_locale(lang):
            await self.app(scope, receive, send_with_headers)
