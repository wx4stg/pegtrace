"""Step 1: load a photo."""

from __future__ import annotations

import holoviews as hv
import panel as pn
from bokeh.models import CustomJS

from ..plotting import equal_aspect
from ..state import AppState
from .common import FILL_WINDOW, help_text, photo_rgb, run_busy, show, status_alert


HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


def is_heif(data: bytes) -> bool:
    """HEIC/HEIF file signature: an ISO-BMFF ``ftyp`` box with a HEIF brand."""
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS

# heic-to bundles libheif built for WASM; it is loaded from the CDN the first time a HEIC photo is picked.
HEIC_TO_URL = "https://cdn.jsdelivr.net/npm/heic-to@1.6.5/dist/heic-to.min.js"

# Browsers other than Safari cannot decode HEIC, and neither can Pillow, so the upload widget
# converts HEIC photos to JPEG before sending them to Python (the same for `panel serve` and
# the static site). libheif applies the photo's rotation, so the JPEG needs no EXIF orientation.
_HEIC_JS = """
if (!globalThis.__pegtrace_heic) {
  globalThis.__pegtrace_heic = true;
  const P = Bokeh.Widgets.FileInput.prototype.default_view.prototype, read = P._read_file;
  const is_heic = (f) => /\\.(heic|heif)$/i.test(f.name) || /^image\\/hei[cf]/i.test(f.type);
  P._read_file = async function (file) {
    if (is_heic(file)) {
      try {
        const { heicTo } = await import(url);
        return await read.call(this, await heicTo({ blob: file, type: "image/jpeg", quality: 0.92 }));
      } catch (e) {
        console.warn("pegtrace: could not convert the HEIC photo:", e);
      }
    }
    return read.call(this, file);
  };
}
"""


def heic_upload(plot, element) -> None:
    """HoloViews hook that teaches every file input on the page to convert HEIC photos."""
    if getattr(plot, "_heic_upload", False):
        return
    plot.state.js_on_change("inner_width", CustomJS(args={"url": HEIC_TO_URL}, code=_HEIC_JS))
    plot._heic_upload = True


class LoadStep:
    title = "1 · Photo"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.on_done = on_done
        self.file = pn.widgets.FileInput(accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff,.heic,.heif", multiple=False)
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
            if is_heif(data):  # the browser could not convert it
                show(self.alert, "Could not convert that HEIC photo. The converter loads from the internet the "
                     "first time, so check the connection, or save the photo as JPEG and load that.", "danger")
            else:
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
                "between the object and the paper. JPEG, PNG and iPhone HEIC photos all work."),
            self.file, self.alert,
            width=340,
        )
        @pn.depends(self.state.param.photo)
        def image(photo):
            return photo_rgb(photo).opts(hooks=[equal_aspect, heic_upload], responsive=True, min_height=500, xaxis=None, yaxis=None,
                                         default_tools=["pan", "wheel_zoom", "reset"], active_tools=["wheel_zoom"])

        self.image_pane = pn.pane.HoloViews(image, sizing_mode="stretch_both", min_height=500, linked_axes=False)
        return pn.Row(controls, self.image_pane, sizing_mode="stretch_width", styles=FILL_WINDOW)
