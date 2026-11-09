"""Application state shared by all UI steps (no Panel widgets in here)."""

from __future__ import annotations

import base64
import io
import json

import numpy as np
import param
from PIL import Image, ImageOps
from shapely.geometry import Polygon

from . import __version__
from .calibration import Calibration, find_rectangle_corners, rectify_rectangle, scale_two_points
from .params import PAPER_SIZES, ExportParams, FlatParams, PegboardParams, ShelfParams
from .tracing import auto_down_angle, autodetect, orient_polygon, prepare_outline

CUSTOM = "Custom"
RECT = "Rectangle (paper, card)"
RULER = "Two points (ruler)"
PROJECT_VERSION = 1


def load_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


class AppState(param.Parameterized):
    # step 1: photo
    photo = param.Parameter(default=None, doc="RGB PIL image, EXIF orientation applied")
    photo_name = param.String(default="")

    # step 2: scale reference
    cal_method = param.Selector(default=RECT, objects=[RECT, RULER])
    paper = param.Selector(default=next(iter(PAPER_SIZES)), objects=[*PAPER_SIZES, CUSTOM])
    custom_w = param.Number(default=100.0, bounds=(1, 2000))
    custom_h = param.Number(default=100.0, bounds=(1, 2000))
    corners_px = param.List(default=[], doc="4 reference corners in photo pixels (u, v), v down")
    ruler_px = param.List(default=[], doc="2 ruler points in photo pixels")
    ruler_mm = param.Number(default=100.0, bounds=(0.1, 5000))
    px_per_mm = param.Number(default=4.0, bounds=(1, 12))
    calibration = param.Parameter(default=None)

    # step 3: outline (mm, calibrated frame)
    raw_outline = param.Parameter(default=None)
    simplify_tol = param.Number(default=0.5, bounds=(0, 5), step=0.05)
    outline = param.Parameter(default=None)

    # step 4: orientation
    mode = param.Selector(default="flat", objects=["flat", "shelf"])
    direction = param.Number(default=270.0, bounds=(0, 360), step=1)

    # step 5/6
    pegboard = param.ClassSelector(class_=PegboardParams)
    flat = param.ClassSelector(class_=FlatParams)
    shelf = param.ClassSelector(class_=ShelfParams)
    export = param.ClassSelector(class_=ExportParams)
    result = param.Parameter(default=None)
    stale = param.Boolean(default=False, doc="Design settings changed since the holder was built")
    error = param.String(default="")
    message = param.String(default="")
    theme = param.Selector(default="default", objects=["default", "dark"], doc="UI theme (not saved)")

    def __init__(self, **params):
        params.setdefault("pegboard", PegboardParams())
        params.setdefault("flat", FlatParams())
        params.setdefault("shelf", ShelfParams())
        params.setdefault("export", ExportParams())
        super().__init__(**params)
        for obj in (self.pegboard, self.flat, self.shelf):
            obj.param.watch(self._params_changed, [p for p in obj.param if p != "name"])

    # ------------------------------------------------------------ photo
    def set_photo(self, img: Image.Image, name: str = "") -> None:
        with param.parameterized.batch_call_watchers(self):
            self.calibration = None
            self.raw_outline = None
            self.outline = None
            self.result = None
            self.corners_px = []
            self.ruler_px = []
            self.photo_name = name
            self.photo = img
        self.guess_reference()

    def load_photo_bytes(self, data: bytes, name: str = "") -> None:
        self.set_photo(load_image(data), name)

    def guess_reference(self) -> None:
        """Pre-place reference points: paper corners if found, else a centred box."""
        if self.photo is None:
            return
        w, h = self.photo.size
        quad = find_rectangle_corners(self.photo)
        if quad is None:
            quad = np.array([[0.3 * w, 0.3 * h], [0.7 * w, 0.3 * h], [0.7 * w, 0.7 * h], [0.3 * w, 0.7 * h]])
            self.message = "Could not find the paper automatically; drag the 4 points onto its corners."
        else:
            self.message = "Found the paper; check the 4 corner points, then apply."
        self.corners_px = [tuple(map(float, p)) for p in quad]
        self.ruler_px = [(0.35 * w, 0.5 * h), (0.65 * w, 0.5 * h)]

    # ------------------------------------------------------------ calibration
    def reference_size(self) -> tuple[float, float]:
        if self.paper == CUSTOM:
            return (self.custom_w, self.custom_h)
        return PAPER_SIZES[self.paper]

    def calibrate(self) -> Calibration:
        if self.photo is None:
            raise ValueError("Load a photo first.")
        if self.cal_method == RECT:
            if len(self.corners_px) != 4:
                raise ValueError("Place exactly 4 corner points.")
            cal = rectify_rectangle(self.photo, self.corners_px, self.reference_size(), px_per_mm=self.px_per_mm)
        else:
            if len(self.ruler_px) != 2:
                raise ValueError("Place exactly 2 ruler points.")
            cal = scale_two_points(self.photo, self.ruler_px[0], self.ruler_px[1], self.ruler_mm)
        with param.parameterized.batch_call_watchers(self):
            self.raw_outline = None
            self.outline = None
            self.result = None
            self.calibration = cal
        return cal

    # ------------------------------------------------------------ outline
    def set_outline(self, poly: Polygon | None, simplify: bool = True) -> None:
        """Set the traced outline. ``simplify=False`` (points placed by hand) keeps every
        point; the smoothing slider still applies when it is moved."""
        if poly is not None and not poly.is_empty:
            poly = prepare_outline(poly)
        self._simplify_raw = simplify
        self.raw_outline = poly if poly is not None and not poly.is_empty else None

    def autodetect(self) -> bool:
        if self.calibration is None:
            raise ValueError("Calibrate first.")
        p = autodetect(self.calibration)
        if p.is_empty:
            return False
        self.set_outline(p)
        return True

    @param.depends("raw_outline", watch=True)
    def _update_outline(self):
        self._apply_simplify(self.simplify_tol if getattr(self, "_simplify_raw", True) else 0.0)

    @param.depends("simplify_tol", watch=True)
    def _on_simplify(self):
        self._apply_simplify(self.simplify_tol)

    def _apply_simplify(self, tol: float):
        if self.raw_outline is None:
            self.outline = None
        else:
            p = prepare_outline(self.raw_outline, tol)
            self.outline = p if not p.is_empty else None

    def auto_direction(self) -> None:
        """Long axis vertical. Pocket style: heavier end down. Ring style: whichever way up
        has a narrow part under a wide part to hang it by (e.g. a T the right way up)."""
        if self.outline is None:
            return
        angle = auto_down_angle(self.outline)
        if self.mode == "flat" and self.flat.style == "ring":
            from .holder_flat import ring_level

            def score(a):
                pc = orient_polygon(self.outline, a).buffer(self.flat.clear_xy, quad_segs=12)
                found = ring_level(pc, self.flat)
                return found[1] if found else -1.0

            flipped = (angle + 180.0) % 360.0
            if score(flipped) > score(angle):
                angle = flipped
        self.direction = angle

    def oriented_outline(self) -> Polygon | None:
        if self.outline is None:
            return None
        return orient_polygon(self.outline, self.direction)

    # ------------------------------------------------------------ build
    def _params_changed(self, *events):
        # Building takes seconds on the static site, so settings only mark the holder out of
        # date; the Design step's Update button (or an export) rebuilds it.
        self.stale = True

    @param.depends("outline", "mode", "direction", watch=True)
    def rebuild(self):
        from .holder_flat import build_flat
        from .holder_shelf import build_shelf

        self.stale = False
        o = self.oriented_outline()
        if o is None:
            self.result = None
            return
        try:
            if self.mode == "flat":
                res = build_flat(o, self.flat, self.pegboard)
            else:
                res = build_shelf(o, self.shelf, self.pegboard)
            self.error = ""
            self.result = res
        except Exception as e:  # keep the UI alive on odd geometry
            self.error = f"Could not build the holder: {e}"
            self.result = None

    def suggest_pocket(self) -> float | None:
        from .stability import suggest_pocket_percent

        o = self.oriented_outline()
        if o is None:
            return None
        pct = suggest_pocket_percent(o, self.flat, self.pegboard)
        if pct is not None:
            self.flat.param.update(pocket_mode="percent", pocket_percent=pct)
        return pct

    def stl_bytes(self) -> bytes:
        from .export import solid_stl

        if self.stale:  # export what the settings say, not the last preview
            self.rebuild()
        if self.result is None:
            raise ValueError("Nothing to export yet.")
        return solid_stl(self.result.solid, self.export.orientation)

    # ------------------------------------------------------------ project files
    def to_json(self) -> str:
        photo_b64 = None
        if self.photo is not None:
            buf = io.BytesIO()
            img = self.photo
            if max(img.size) > 3000:
                img = img.copy()
                img.thumbnail((3000, 3000))
            img.save(buf, format="JPEG", quality=90)
            photo_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        scale = 1.0
        if self.photo is not None and photo_b64 is not None:
            scale = min(1.0, 3000 / max(self.photo.size))
        doc = {
            "app": "pegtrace",
            "version": PROJECT_VERSION,
            "pegtrace_version": __version__,
            "photo_name": self.photo_name,
            "photo_jpeg_b64": photo_b64,
            "cal_method": self.cal_method,
            "paper": self.paper,
            "custom_size": [self.custom_w, self.custom_h],
            "corners_px": [[x * scale, y * scale] for x, y in self.corners_px],
            "ruler_px": [[x * scale, y * scale] for x, y in self.ruler_px],
            "ruler_mm": self.ruler_mm,
            "px_per_mm": self.px_per_mm,
            "calibrated": self.calibration is not None,
            "outline_mm": None if self.raw_outline is None else np.asarray(self.raw_outline.exterior.coords).tolist(),
            "simplify_tol": self.simplify_tol,
            "mode": self.mode,
            "direction": self.direction,
            "pegboard": json.loads(self.pegboard.param.serialize_parameters()),
            "flat": json.loads(self.flat.param.serialize_parameters()),
            "shelf": json.loads(self.shelf.param.serialize_parameters()),
            "export": json.loads(self.export.param.serialize_parameters()),
        }
        return json.dumps(doc)

    def from_json(self, text: str) -> None:
        doc = json.loads(text)
        if doc.get("app") != "pegtrace":
            raise ValueError("Not a PegTrace project file.")
        for key, obj in (("pegboard", self.pegboard), ("flat", self.flat), ("shelf", self.shelf),
                         ("export", self.export)):
            vals = doc.get(key) or {}
            vals.pop("name", None)
            if key == "pegboard":
                vals.pop("preset", None)  # restore exact values, not a preset's
                obj.param.update(preset="Custom")
            known = {k: v for k, v in vals.items() if k in obj.param}
            obj.param.update(**obj.param.deserialize_parameters(json.dumps(known)))
        if doc.get("photo_jpeg_b64"):
            self.set_photo(load_image(base64.b64decode(doc["photo_jpeg_b64"])), doc.get("photo_name", ""))
        self.param.update(
            cal_method=doc.get("cal_method", RECT),
            paper=doc.get("paper", self.paper),
            custom_w=doc.get("custom_size", [100, 100])[0],
            custom_h=doc.get("custom_size", [100, 100])[1],
            corners_px=[tuple(p) for p in doc.get("corners_px", [])],
            ruler_px=[tuple(p) for p in doc.get("ruler_px", [])],
            ruler_mm=doc.get("ruler_mm", 100.0),
            px_per_mm=doc.get("px_per_mm", 4.0),
        )
        if doc.get("calibrated") and self.photo is not None:
            self.calibrate()
        self.param.update(simplify_tol=doc.get("simplify_tol", 0.5), mode=doc.get("mode", "flat"),
                          direction=doc.get("direction", 270.0))
        if doc.get("outline_mm"):
            self.set_outline(Polygon(doc["outline_mm"]))
        self.rebuild()
