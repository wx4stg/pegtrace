"""Step 1: load a photo."""

from __future__ import annotations

import holoviews as hv
import panel as pn

from ..sample import make_photo
from ..plotting import equal_aspect
from ..state import AppState
from .common import FILL_WINDOW, help_text, photo_rgb, show, status_alert


class LoadStep:
    title = "1 · Photo"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.file = pn.widgets.FileInput(accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff", multiple=False)
        self.sample = pn.widgets.Button(name="Try the sample photo", button_type="default")
        self.alert = status_alert()
        self.file.param.watch(self._on_file, "value")
        self.sample.on_click(self._on_sample)

    def _on_file(self, event):
        if not event.new:
            return
        try:
            self.state.load_photo_bytes(event.new, self.file.filename or "")
            w, h = self.state.photo.size
            show(self.alert, f"Loaded **{self.file.filename}** ({w} × {h} px).", "success")
            if self.on_done:
                self.on_done()
        except Exception as e:
            show(self.alert, f"Could not read that image: {e}", "danger")

    def _on_sample(self, _):
        photo, _truth = make_photo()
        self.state.set_photo(photo, "sample.jpg")
        show(self.alert, "Loaded the sample photo: a tool on US Letter paper, shot at an angle.", "success")
        if self.on_done:
            self.on_done()

    def view(self):
        controls = pn.Column(
            "### Photo",
            help_text(
                "Photograph the object lying flat on a **sheet of paper** (or next to a ruler). "
                "Shoot from roughly above, with all four paper corners visible and good contrast "
                "between the object and the paper."),
            self.file, self.sample, self.alert,
            width=340,
        )
        @pn.depends(self.state.param.photo)
        def image(photo):
            return photo_rgb(photo).opts(data_aspect=1, hooks=[equal_aspect], responsive=True, min_height=500, xaxis=None, yaxis=None,
                                         default_tools=["pan", "wheel_zoom", "reset"], active_tools=["wheel_zoom"])

        return pn.Row(controls, pn.pane.HoloViews(image, sizing_mode="stretch_both", min_height=500, linked_axes=False),
                      sizing_mode="stretch_width", styles=FILL_WINDOW)
