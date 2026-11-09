"""Small, targeted workarounds for library behaviour in the browser runtime."""

from __future__ import annotations

_patched = False


def patch_holoviews_callbacks() -> None:
    """Ignore stream callbacks whose plot has already been cleaned up.

    In the browser, HoloViews runs bokeh change/event callbacks as asyncio tasks.
    When a plot is replaced (e.g. a new photo), tasks queued for the old plot run
    after ``Callback.plot`` was cleared and fail with "'NoneType' object has no
    attribute 'document'". Those events belong to a plot that no longer exists,
    so dropping them is correct.
    """
    global _patched
    if _patched:
        return
    from holoviews.plotting.bokeh.callbacks import Callback

    orig_change = Callback.on_change
    orig_event = Callback.on_event

    async def on_change(self, attr, old, new):
        if getattr(self, "plot", None) is None:
            return
        return await orig_change(self, attr, old, new)

    async def on_event(self, event):
        if getattr(self, "plot", None) is None:
            return
        return await orig_event(self, event)

    Callback.on_change = on_change
    Callback.on_event = on_event
    _patched = True
