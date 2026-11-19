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


def legacy_flat(vals: dict, doc: dict) -> dict:
    """Flat settings from a project saved before the ring and pocket styles became one holder
    set by Top Y and Bottom Y."""
    vals = dict(vals)
    style = vals.pop("style", "pocket")
    ring_top, ring_height = vals.pop("ring_top", 40.0), vals.pop("ring_height", 10.0)
    mode, pct, mm = vals.pop("pocket_mode", "percent"), vals.pop("pocket_percent", 40.0), vals.pop("pocket_mm", 30.0)
    vals.pop("flat_bottom", None)
    clear = vals.get("clear_xy", FlatParams.param.clear_xy.default)
    if style == "ring":
        vals.update(top_y=ring_top, bottom_y=ring_top - ring_height)
        return vals
    height = 100.0
    if doc.get("outline_mm"):
        o = orient_polygon(Polygon(doc["outline_mm"]), doc.get("direction", 270.0))
        height = o.bounds[3] - o.bounds[1] + 2 * clear  # the old pocket depth counted the gap
    depth = pct / 100 * height if mode == "percent" else mm
    depth = min(max(depth, 0.5), height)
    wall = vals.get("wall", FlatParams.param.wall.default)
    vals.update(top_y=max(depth - clear, 0.5), bottom_y=-(clear + wall))
    return vals


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

    def __init__(self, **params):
        params.setdefault("pegboard", PegboardParams())
        params.setdefault("flat", FlatParams())
        params.setdefault("shelf", ShelfParams())
        params.setdefault("export", ExportParams())
        super().__init__(**params)
        for obj in (self.pegboard, self.flat, self.shelf):
            obj.param.watch(self._params_changed, [p for p in obj.param if p != "name"])
        self._loading = False
        self._band_for = None  # (outline, direction) the last suggestion was made for
        self.param.watch(self._geometry_changed, ["outline", "mode", "direction"])

    # ------------------------------------------------------------ photo
    def set_photo(self, img: Image.Image | None, name: str = "") -> None:
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
        pw, ph = self.reference_size()
        quad = find_rectangle_corners(self.photo, aspect=max(pw, ph) / min(pw, ph))
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
        """Long axis vertical. In flat mode, whichever way up has a wider part over a narrower
        one to hang it by in a ring (a T the right way up), else the heavier end down for a
        pocket. Then suggest the holder's top and bottom for that way up."""
        if self.outline is None:
            return
        angle = auto_down_angle(self.outline)
        if self.mode == "flat":
            from .holder_flat import find_ring

            def score(a):  # 2: a ring holds it securely, 1: a ring holds it, 0: no ring
                ring = find_ring(orient_polygon(self.outline, a), self.flat, self.pegboard)
                return 0 if ring is None else 2 if ring[2] else 1

            flipped = (angle + 180.0) % 360.0
            if score(flipped) > score(angle):
                angle = flipped
        if angle != self.direction:
            self.direction = angle  # suggests the band and rebuilds (see _geometry_changed)
        else:
            self.suggest_band()
            self.rebuild()

    def suggest_band(self) -> str | None:
        """Set Top Y and Bottom Y for the current outline and direction: a ring if the object
        gets wider going up and a ring holds it, else a pocket. Returns which, or None."""
        from .holder_flat import suggest_band

        o = self.oriented_outline()
        if o is None or self.mode != "flat":
            return None
        top_y, bottom_y, kind = suggest_band(o, self.flat, self.pegboard)
        self.flat.param.update(top_y=top_y, bottom_y=bottom_y)
        self._band_for = self._band_key()
        return kind

    def oriented_outline(self) -> Polygon | None:
        if self.outline is None:
            return None
        return orient_polygon(self.outline, self.direction)

    # ------------------------------------------------------------ build
    def _params_changed(self, *events):
        # Building takes seconds on the static site, so settings only mark the holder out of
        # date; the Design step's Update button (or an export) rebuilds it.
        self.stale = True

    def _geometry_changed(self, *events):
        """A new outline (not an edit of one), another direction or a switch to flat mode makes
        the old Top Y and Bottom Y meaningless: suggest new ones, then rebuild. A project
        being loaded keeps its own."""
        new_shape = any(e.name == "outline" and e.old is None for e in events)
        turned = any(e.name == "direction" for e in events)
        # back to flat mode: only if this outline and direction never had a suggestion
        to_flat = any(e.name == "mode" for e in events) and self._band_for != self._band_key()
        if not self._loading and (new_shape or turned or to_flat):
            self.suggest_band()
        self.rebuild()

    def _band_key(self):
        return (id(self.outline), self.direction)

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

    def stl_bytes(self) -> bytes:
        from .export import solid_stl

        if self.stale:  # export what the settings say, not the last preview
            self.rebuild()
        if self.result is None:
            raise ValueError("Nothing to export yet.")
        return solid_stl(self.result.solid)  # standing upright, ready to print

    # ------------------------------------------------------------ project files
    def to_json(self, include_photo: bool | None = None) -> str:
        """The project as JSON. Without the photo the file is a few KB instead of a few hundred;
        it still holds the outline (in mm), the scale reference and all settings."""
        if include_photo is None:
            include_photo = self.export.include_photo
        photo_b64 = None
        if self.photo is not None and include_photo:
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
        self._loading = True
        try:
            self._load(doc)
        finally:
            self._loading = False
        self._band_for = self._band_key()  # the project's own values count as chosen
        self.rebuild()

    def _load(self, doc: dict) -> None:
        if doc.get("flat") and "top_y" not in doc["flat"]:
            doc["flat"] = legacy_flat(doc["flat"], doc)
        for key, obj in (("pegboard", self.pegboard), ("flat", self.flat), ("shelf", self.shelf),
                         ("export", self.export)):
            vals = doc.get(key) or {}
            vals.pop("name", None)
            if key == "pegboard":
                vals.pop("preset", None)  # restore exact values, not a preset's
                obj.param.update(preset="Custom")
            known = {k: v for k, v in vals.items() if k in obj.param}
            obj.param.update(**obj.param.deserialize_parameters(json.dumps(known)))
        has_photo = bool(doc.get("photo_jpeg_b64"))
        if has_photo:
            self.set_photo(load_image(base64.b64decode(doc["photo_jpeg_b64"])), doc.get("photo_name", ""))
        else:  # a photo already on screen belongs to another project
            self.set_photo(None, doc.get("photo_name", ""))
        self.param.update(
            cal_method=doc.get("cal_method", RECT),
            paper=doc.get("paper", self.paper),
            custom_w=doc.get("custom_size", [100, 100])[0],
            custom_h=doc.get("custom_size", [100, 100])[1],
            corners_px=[tuple(p) for p in doc.get("corners_px", [])] if has_photo else [],
            ruler_px=[tuple(p) for p in doc.get("ruler_px", [])] if has_photo else [],
            ruler_mm=doc.get("ruler_mm", 100.0),
            px_per_mm=doc.get("px_per_mm", 4.0),
        )
        if doc.get("calibrated") and self.photo is not None:
            self.calibrate()
        self.param.update(simplify_tol=doc.get("simplify_tol", 0.5), mode=doc.get("mode", "flat"),
                          direction=doc.get("direction", 270.0))
        if doc.get("outline_mm"):
            self.set_outline(Polygon(doc["outline_mm"]))
        if not has_photo:
            self.param.trigger("calibration")  # redraw the Trace view around the outline
