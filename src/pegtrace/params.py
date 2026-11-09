"""User-adjustable settings (param.Parameterized so Panel can build widgets)."""

from __future__ import annotations

import param

INCH = 25.4

PEGBOARD_PRESETS: dict[str, dict[str, float]] = {
    "US 1/4 in hardboard (1 in grid, 1/4 in holes)": dict(
        spacing=25.4, hole_d=0.25 * INCH, board_t=0.25 * INCH
    ),
    "US 1/8 in hardboard (1 in grid, 3/16 in holes)": dict(
        spacing=25.4, hole_d=3 / 16 * INCH, board_t=0.125 * INCH
    ),
    "Metric 25 mm grid (5 mm holes)": dict(spacing=25.0, hole_d=5.0, board_t=5.0),
}
CUSTOM = "Custom"

PAPER_SIZES: dict[str, tuple[float, float]] = {
    "US Letter (8.5 x 11 in)": (215.9, 279.4),
    "A4 (210 x 297 mm)": (210.0, 297.0),
    "US Legal (8.5 x 14 in)": (215.9, 355.6),
    "A5 (148 x 210 mm)": (148.0, 210.0),
    "A3 (297 x 420 mm)": (297.0, 420.0),
    "Credit card (85.6 x 54 mm)": (53.98, 85.6),
}


class PegboardParams(param.Parameterized):
    """Pegboard geometry and peg/hook design."""

    preset = param.Selector(
        default=next(iter(PEGBOARD_PRESETS)),
        objects=[*PEGBOARD_PRESETS, CUSTOM],
        doc="Common pegboard types. Pick Custom to keep your own values.",
    )
    spacing = param.Number(25.4, bounds=(5, 100), step=0.1, doc="Hole pitch (mm)")
    hole_d = param.Number(6.35, bounds=(2, 20), step=0.05, doc="Hole diameter (mm)")
    board_t = param.Number(6.35, bounds=(1, 25), step=0.05, doc="Board thickness (mm)")
    peg_clear = param.Number(
        0.5, bounds=(0, 3), step=0.05, doc="Peg diameter is hole diameter minus this (mm)"
    )
    board_clear = param.Number(
        0.6, bounds=(0, 5), step=0.1, doc="Extra peg length beyond the board thickness (mm)"
    )
    hook_rise = param.Number(
        8.0, bounds=(0, 40), step=0.5, doc="How far the hook tip rises behind the board (mm)"
    )
    columns = param.Integer(0, bounds=(0, 12), doc="Number of peg columns (0 = auto)")
    max_pegs = param.Integer(3, bounds=(1, 12), doc="Max columns when auto")
    stride = param.Integer(1, bounds=(1, 6), doc="Use every Nth hole horizontally")
    add_pins = param.Boolean(True, doc="Add a lower row of straight anti-tilt pins")
    pin_rows = param.Integer(1, bounds=(1, 6), doc="Pin row is this many holes below the hooks")
    pin_length = param.Number(
        0.0, bounds=(0, 30), step=0.5, doc="Pin length (mm, 0 = 75% of board thickness)"
    )
    peg_profile = param.Selector(
        default="teardrop",
        objects=["teardrop", "round"],
        doc="Teardrop pegs print cleanly when the holder prints upright",
    )
    tab_margin = param.Number(4.0, bounds=(1, 20), step=0.5, doc="Back plate margin around pegs (mm)")

    @param.depends("preset", watch=True, on_init=True)
    def _apply_preset(self):
        vals = PEGBOARD_PRESETS.get(self.preset)
        if vals:
            self.param.update(**vals)

    @property
    def peg_d(self) -> float:
        return max(self.hole_d - self.peg_clear, 1.0)


class FlatParams(param.Parameterized):
    """Holder that cradles the object flat against the pegboard."""

    style = param.Selector(
        default="ring", objects=["ring", "pocket"],
        doc="Ring: a band around a narrow part, with a wider part above resting on it (hammer head, "
            "the bar of a T, pliers joint). Pocket: a cradle around the bottom of the object.",
    )
    ring_top = param.Number(40.0, bounds=(0.5, 1000), step=0.5,
                            doc="Height on the object (mm above its lowest point) where its wide part rests "
                                "on the ring: the top of the ring. Click the front view to set it.")
    ring_height = param.Number(10.0, bounds=(3, 60), step=0.5, doc="Height of the ring band (mm)")
    object_thickness = param.Number(
        20.0, bounds=(1, 200), step=0.5, doc="Object thickness perpendicular to the photo (mm)"
    )
    clear_xy = param.Number(1.0, bounds=(0, 10), step=0.1, doc="Gap around the outline (mm)")
    clear_z = param.Number(1.0, bounds=(0, 10), step=0.1, doc="Extra depth beyond object thickness (mm)")
    wall = param.Number(2.4, bounds=(0.8, 15), step=0.1, doc="Wall thickness (mm)")
    back_t = param.Number(3.0, bounds=(1, 15), step=0.1, doc="Back plate thickness (mm)")
    pocket_mode = param.Selector(default="percent", objects=["percent", "mm"])
    pocket_percent = param.Number(40.0, bounds=(5, 100), step=1, doc="Pocket depth, % of object height")
    pocket_mm = param.Number(30.0, bounds=(2, 500), step=1, doc="Pocket depth (mm)")
    lip = param.Boolean(True, doc="Front lip that stops the object tipping forward")
    lip_overlap = param.Number(4.0, bounds=(0.5, 100), step=0.5, doc="How far the lip covers the object's face (mm)")
    lip_t = param.Number(2.0, bounds=(0.8, 10), step=0.1, doc="Lip thickness (mm)")
    lip_height_percent = param.Number(100.0, bounds=(10, 100), step=5, doc="Lip height, % of pocket depth")
    flat_bottom = param.Boolean(True, doc="Flatten the underside so it prints upright with no supports")
    notch = param.Boolean(False, doc="Thumb notch at the top of the pocket")
    notch_d = param.Number(20.0, bounds=(5, 80), step=1, doc="Thumb notch diameter (mm)")


class ShelfParams(param.Parameterized):
    """Shelf sticking out from the board with a pocket shaped like the footprint."""

    clear_xy = param.Number(1.0, bounds=(0, 10), step=0.1, doc="Gap around the outline (mm)")
    pocket_depth = param.Number(12.0, bounds=(1, 200), step=0.5, doc="Pocket depth (or shelf thickness when through) (mm)")
    floor_t = param.Number(2.0, bounds=(0.6, 20), step=0.1, doc="Floor under the pocket (mm)")
    through = param.Boolean(False, doc="Cut the outline all the way through (for shafts/handles)")
    shelf_wall = param.Number(3.0, bounds=(1, 30), step=0.1, doc="Shelf material around the pocket (mm)")
    back_t = param.Number(3.0, bounds=(1, 15), step=0.1, doc="Back plate thickness (mm)")
    rim_height = param.Number(0.0, bounds=(0, 100), step=0.5, doc="Raised rim around the outline (mm)")
    rim_t = param.Number(1.6, bounds=(0.8, 10), step=0.1, doc="Rim wall thickness (mm)")
    gussets = param.Boolean(True, doc="Triangular supports on the shelf ends")
    gusset_t = param.Number(3.0, bounds=(1, 20), step=0.5, doc="Gusset thickness (mm)")
    object_height = param.Number(40.0, bounds=(1, 500), step=1, doc="Object height (preview only) (mm)")


class ExportParams(param.Parameterized):
    orientation = param.Selector(
        default="print (upright)",
        objects=["print (upright)", "as mounted"],
        doc="Print: bottom on the bed, needs no supports. As mounted: board plane is XY.",
    )
    filename = param.String("pegtrace_holder.stl")


# Human-readable widget labels (pn.Param uses Parameter.label)
_LABELS = {
    PegboardParams: {
        "preset": "Pegboard type", "spacing": "Hole spacing (mm)", "hole_d": "Hole diameter (mm)",
        "board_t": "Board thickness (mm)", "peg_clear": "Peg clearance (mm)", "board_clear": "Extra peg length (mm)",
        "hook_rise": "Hook rise (mm)", "columns": "Peg columns (0 = auto)", "max_pegs": "Max columns (auto)",
        "stride": "Use every Nth hole", "add_pins": "Anti-tilt pins", "pin_rows": "Pins: holes below hooks",
        "pin_length": "Pin length (mm, 0 = auto)", "peg_profile": "Peg profile",
        "tab_margin": "Plate margin around pegs (mm)",
    },
    FlatParams: {
        "style": "Holder style", "ring_top": "Ring top: height on the object (mm)", "ring_height": "Ring height (mm)",
        "object_thickness": "Object thickness (mm)", "clear_xy": "Gap around outline (mm)",
        "clear_z": "Extra depth (mm)", "wall": "Wall thickness (mm)", "back_t": "Back plate thickness (mm)",
        "pocket_mode": "Pocket depth in", "pocket_percent": "Pocket depth (% of height)",
        "pocket_mm": "Pocket depth (mm)", "lip": "Front lip", "lip_overlap": "Lip overlap (mm)",
        "lip_t": "Lip thickness (mm)", "lip_height_percent": "Lip height (% of pocket)",
        "flat_bottom": "Flat bottom (print upright)", "notch": "Thumb notch", "notch_d": "Notch diameter (mm)",
    },
    ShelfParams: {
        "clear_xy": "Gap around outline (mm)", "pocket_depth": "Pocket depth (mm)",
        "floor_t": "Floor thickness (mm)", "through": "Cut all the way through", "shelf_wall": "Shelf margin (mm)",
        "back_t": "Back plate thickness (mm)", "rim_height": "Rim height (mm, 0 = none)",
        "rim_t": "Rim thickness (mm)", "gussets": "Support gussets", "gusset_t": "Gusset thickness (mm)",
        "object_height": "Object height (preview, mm)",
    },
    ExportParams: {"orientation": "STL orientation", "filename": "File name"},
}
for _cls, _labels in _LABELS.items():
    for _name, _label in _labels.items():
        _cls.param[_name].label = _label
