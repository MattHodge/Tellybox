"""History `/admin/history` (AD-4): the last 21 watch days, newest first."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from tellybox import store
from tellybox.history import history_days
from tellybox.i18n import N_, _
from tellybox.web.admin.common import AdminContext, render

OVERRIDE_LABELS = {
    "extra_minutes": N_("Added time"),
    "unlimited": N_("Unlimited today"),
    "block": N_("Block"),
    "stop_now": N_("Stop now"),
}


def create_router(ctx: AdminContext) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/history")
    def history_page(request: Request) -> HTMLResponse:
        reset_time = store.timer_settings(ctx.conn, ctx.config.tz).reset_time
        days = history_days(ctx.conn, ctx.clock.now(), ctx.config.tz, reset_time)
        has_any = any(d.episodes or d.overrides for d in days)
        return render(
            request, "history.html", nav="history",
            days=days, tz=ctx.config.tz, has_any=has_any, override_labels={kind: _(label) for kind, label in OVERRIDE_LABELS.items()},
        )

    return router
