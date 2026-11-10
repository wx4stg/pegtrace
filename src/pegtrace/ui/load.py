"""Step 1: load a photo."""

from __future__ import annotations

import holoviews as hv
import panel as pn

from ..plotting import equal_aspect
from ..state import AppState
from .common import FILL_WINDOW, help_text, photo_rgb, run_busy, show, status_alert


class LoadStep:
    title = "1 · Photo"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.file = pn.widgets.FileInput(accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff", multiple=False)
        self.alert = status_alert()
        self.file.param.watch(self._on_file, "value")
        self.file.param.watch(self._on_filename, "filename")
        self._unnamed = False

    def _on_file(self, event):
        if event.new:
            # with a spinner: decoding a big photo takes a moment on the static site
            run_busy(self.image_pane, self._load)

    def _load(self):
        data, name = self.file.value, self.file.filename or ""
        if not data:
            return
        try:
            self.state.load_photo_bytes(data, name)
        except Exception as e:
            show(self.alert, f"Could not read that image: {e}", "danger")
            return
        self._unnamed = not name
        self._loaded_message()
        if self.on_done:
            self.on_done()

    def _on_filename(self, event):
        # On the static site the file's name reaches Python after its contents.
        if self._unnamed and event.new:
            self._unnamed = False
            self.state.photo_name = event.new
            self._loaded_message()

    def _loaded_message(self):
        w, h = self.state.photo.size
        name = self.state.photo_name
        show(self.alert, f"Loaded **{name}** ({w} × {h} px)." if name else f"Loaded the photo ({w} × {h} px).",
             "success")

    def view(self):
        controls = pn.Column(
            "### Photo",
            help_text(
                "Photograph the object lying flat on a **sheet of paper** (or next to a ruler). "
                "Shoot from roughly above, with all four paper corners visible and good contrast "
                "between the object and the paper."),
            self.file, self.alert,
            width=340,
        )
        @pn.depends(self.state.param.photo)
        def image(photo):
            return photo_rgb(photo).opts(hooks=[equal_aspect], responsive=True, min_height=500, xaxis=None, yaxis=None,
                                         default_tools=["pan", "wheel_zoom", "reset"], active_tools=["wheel_zoom"])

        self.image_pane = pn.pane.HoloViews(image, sizing_mode="stretch_both", min_height=500, linked_axes=False)
        return pn.Row(controls, self.image_pane, sizing_mode="stretch_width", styles=FILL_WINDOW)
