"""Labelled sketches of what the Design step's settings change (inline SVG).

The sketches are schematic, not to scale. Labels use the settings' names on the page, so a
reader can match a slider to the dimension it controls. Text and lines use ``currentColor``
so the sketches follow the page's text colour.
"""

from __future__ import annotations

import math
from html import escape

OBJECT = "#5b6b8c"
HOLDER = "#3f72af"
BOARD = "#c8a97e"
DIM = "#e15759"
W = 340  # sketch width (px); the settings column is 360 px wide


class Sketch:
    def __init__(self, height: int, title: str):
        self.h = height
        self.title = title
        self.items: list[str] = []

    # -- shapes -----------------------------------------------------------------------
    def rect(self, x, y, w, h, fill, opacity=1.0, dash=False, stroke="currentColor", sw=0.8):
        d = ' stroke-dasharray="4 3"' if dash else ""
        if fill == "bg":  # the page background (CSS variables only work in style, not attributes)
            d += ' style="fill: var(--panel-background-color, #fff)"'
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
                          f'fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def poly(self, pts, fill, opacity=1.0, dash=False, stroke="currentColor", sw=0.8):
        d = ' stroke-dasharray="4 3"' if dash else ""
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.items.append(f'<polygon points="{p}" fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" '
                          f'stroke-width="{sw}"{d}/>')

    def circle(self, x, y, r, fill, opacity=1.0, dash=False, stroke="currentColor", sw=0.8):
        d = ' stroke-dasharray="3 2"' if dash else ""
        self.items.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" fill-opacity="{opacity}" '
                          f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def line(self, x1, y1, x2, y2, color="currentColor", sw=0.8, dash=False):
        d = ' stroke-dasharray="3 3"' if dash else ""
        self.items.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, anchor="middle", size=10, color="currentColor", italic=False):
        style = ' font-style="italic"' if italic else ""
        self.items.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}"'
                          f'{style}>{escape(s)}</text>')

    # -- dimensions ---------------------------------------------------------------------
    def dim(self, x1, y1, x2, y2, label, lx=None, ly=None, anchor="middle", vertical=False):
        """A dimension line with arrows at both ends and its label (default: at the middle).
        ``vertical`` writes the label along a vertical line, reading upwards."""
        self.items.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{DIM}" stroke-width="1.2" '
                          f'marker-start="url(#pt-arrow)" marker-end="url(#pt-arrow)"/>')
        if lx is None:
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 4
        if vertical:
            self.items.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="10" fill="{DIM}" '
                              f'transform="rotate(-90 {lx} {ly})">{escape(label)}</text>')
        else:
            self.text(lx, ly, label, anchor=anchor, color=DIM, size=10)

    def leader(self, x1, y1, x2, y2, label, anchor="start"):
        """A label at (x2, y2) pointing at (x1, y1)."""
        self.items.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{DIM}" stroke-width="0.8"/>')
        self.circle(x1, y1, 1.6, DIM, stroke=DIM)
        self.text(x2 + (3 if anchor == "start" else -3 if anchor == "end" else 0), y2 + 3.5, label,
                  anchor=anchor, color=DIM)

    def svg(self) -> str:
        defs = (f'<defs><marker id="pt-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" '
                f'markerHeight="6" orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="{DIM}"/>'
                f'</marker></defs>')
        title = f'<text x="4" y="12" font-size="11" font-weight="600" fill="currentColor">{escape(self.title)}</text>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {self.h}" width="100%" '
                f'style="max-width:{W}px; display:block; font-family: inherit">{defs}{title}'
                + "".join(self.items) + "</svg>")


def _legend(*entries) -> str:
    sw = "".join(f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px">'
                 f'<span style="width:10px;height:10px;background:{c};opacity:{o};display:inline-block;'
                 f'border:1px solid currentColor"></span>{escape(t)}</span>' for t, c, o in entries)
    return f'<div style="font-size:11px;margin:2px 0 6px 4px">{sw}</div>'


LEGEND = _legend(("object", OBJECT, 0.55), ("holder", HOLDER, 0.85), ("pegboard", BOARD, 0.9))


def _side_section(s: Sketch, top: float, bottom: float, lip_note: str, plate: bool = True,
                  hy: float | None = None) -> None:
    """Section through the holder from the side: board, back plate, object, extra depth, lip.
    Board on the left, front of the holder on the right; ``top``/``bottom`` bound the band.
    ``plate=False`` leaves the back plate for the caller to draw; ``hy`` is the hook's height."""
    y0, y1 = 24, s.h - 62
    bd, bp, ob, ex, lp = 52, 70, 84, 164, 176   # x of board, back plate, object, extra depth, lip
    s.rect(bd, y0, bp - bd, y1 - y0, BOARD, 0.9)
    if plate:
        s.rect(bp, top, ob - bp, y1 - 10 - top, HOLDER, 0.85)   # back plate (and the tab below)
    s.rect(ob, y0 + 8, ex - ob, y1 - y0 - 16, OBJECT, 0.55)
    s.rect(lp, top, 14, bottom - top, HOLDER, 0.85)              # lip / front bar
    hy = y1 - 26 if hy is None else hy                           # a hook through the board
    s.rect(40, hy - 3, bp - 40, 6, HOLDER, 0.85)
    s.rect(40, hy - 16, 6, 16, HOLDER, 0.85)
    yd = s.h - 34
    for x in (bp, ob, lp, lp + 14):
        s.line(x, min(bottom, y1 - 10) + 4, x, yd + 4, dash=True, sw=0.6)
    s.line(ex, y1 - 8, ex, yd + 4, dash=True, sw=0.6)
    s.dim(ob, yd - 12, ex, yd - 12, "Object thickness", (ob + ex) / 2, yd - 16)
    s.dim(bp, yd, ob, yd, "Back plate", bp - 4, yd + 14, "end")
    s.dim(ex, yd, lp, yd, "Extra depth", (ex + lp) / 2 + 4, yd + 14)
    s.dim(lp, yd - 12, lp + 14, yd - 12, lip_note, lp + 18, yd - 9, "start")
    s.text((bd + bp) / 2, y0 - 4, "board", size=9)
    s.text((ob + ex) / 2, y0 + 22, "object", size=9, color="#fff")
    s.text(4, s.h - 4, "side section: board on the left, front on the right", anchor="start", size=9, italic=True)


def flat_sketch() -> str:
    front = Sketch(276, "Front view: Top Y and Bottom Y")
    y0 = 206                                                    # the objects' lowest point: 0
    # left: a ring. A T hangs by its bar; the band circles the stem below it.
    top, bot = 52, 90
    front.rect(33, top, 64, 50, HOLDER, 0.3, dash=True)         # back plate behind
    front.circle(65, 96, 4, HOLDER, 0.9)
    front.rect(15, 26, 100, 22, OBJECT, 0.55)
    front.rect(53, 48, 24, y0 - 48, OBJECT, 0.55)
    front.rect(33, top, 14, bot - top, HOLDER, 0.85)
    front.rect(83, top, 14, bot - top, HOLDER, 0.85)
    front.poly([(33, bot), (47, bot), (47, bot + 12)], HOLDER, 0.5)   # sloped supports under the ring
    front.poly([(97, bot), (83, bot), (83, bot + 12)], HOLDER, 0.5)
    front.line(97, top, 126, top, dash=True, sw=0.6)
    front.line(97, bot, 146, bot, dash=True, sw=0.6)
    front.dim(122, y0, 122, top, "Top Y", 130, 150, vertical=True)
    front.dim(142, y0, 142, bot, "Bottom Y", 150, 160, vertical=True)
    front.dim(33, 222, 47, 222, "Wall", 58, 226, "start")
    front.dim(47, 236, 53, 236, "Gap around outline", 58, 240, "start")
    for x in (33, 47, 53):
        front.line(x, bot + 14 if x != 53 else y0, x, 240, dash=True, sw=0.6)
    front.text(80, 268, "Bottom Y above 0: a ring", size=10)
    # right: a pocket. A hammer sits head down in a cup with a floor.
    hx0, hx1, ptop, fl = 196, 284, 140, 218
    gap, wall, ov = 4, 10, 8
    cx = (hx0 + hx1) / 2
    front.rect(cx - 20, 100, 40, fl - 100, HOLDER, 0.3, dash=True)  # back plate behind
    front.circle(cx, 116, 4, HOLDER, 0.9)
    front.poly([(hx0 - gap - wall, ptop), (hx0 - gap, ptop), (hx0 - gap, y0 + gap), (hx1 + gap, y0 + gap),
                (hx1 + gap, ptop), (hx1 + gap + wall, ptop), (hx1 + gap + wall, fl), (hx0 - gap - wall, fl)],
               HOLDER, 0.85)
    front.rect(hx0, 174, hx1 - hx0, y0 - 174, OBJECT, 0.55)
    front.rect(cx - 12, 40, 24, 134, OBJECT, 0.55)
    # lip in front: covers the gap and the object's edge by the overlap
    front.poly([(hx0 - gap - wall, ptop), (hx0 + ov, ptop), (hx0 + ov, y0 - ov), (hx1 - ov, y0 - ov),
                (hx1 - ov, ptop), (hx1 + gap + wall, ptop), (hx1 + gap + wall, fl), (hx0 - gap - wall, fl)],
               HOLDER, 0.25, dash=True)
    front.dim(hx0, 128, hx0 + ov, 128, "Lip overlap", hx0 - 4, 124, "end")
    front.line(hx0, 128, hx0, 172, dash=True, sw=0.6)
    front.line(hx0 + ov, 128, hx0 + ov, ptop, dash=True, sw=0.6)
    front.circle(cx, ptop, 11, "none", dash=True, stroke=DIM)
    front.leader(cx + 9, ptop - 6, 262, 98, "Thumb notch")
    front.line(hx1 + gap + wall, ptop, 330, ptop, dash=True, sw=0.6)
    front.line(hx1 + gap + wall, fl, 336, fl, dash=True, sw=0.6)
    front.dim(318, y0, 318, ptop, "Top Y", 326, 173, vertical=True)
    front.dim(332, y0, 332, fl, "", 0, 0)
    front.text(328, 236, "Bottom Y below 0", anchor="end", size=10, color=DIM)
    front.text(328, 248, "(a floor)", anchor="end", size=9, color=DIM)
    front.text(258, 268, "Bottom Y below 0: a pocket", size=10)
    front.leader(hx1 + gap + 5, y0 - 30, 336, 72, "lip (in front)", anchor="end")
    # 0: the objects' lowest point
    front.line(4, y0, 336, y0, color=DIM, dash=True, sw=0.8)
    front.text(160, y0 - 4, "0", size=10, color=DIM)
    side = Sketch(260, "Side section (a ring)")
    top, bot, k = 64, 106, 0.55          # the band, and the slope of the supports under it (schematic)
    _side_section(side, top, bot, "Lip thickness", plate=False, hy=96)
    slope = lambda x: bot + k * (190 - x)  # noqa: E731  the sloped underside, from the front bar's front edge
    side.poly([(176, bot), (190, bot), (176, slope(176))], HOLDER, 0.85)             # support under the lip
    side.poly([(70, top), (84, top), (84, slope(84)), (70, slope(70))], HOLDER, 0.85)  # back plate
    d = 12                                                                          # "below the supports"
    side.poly([(70, slope(70)), (84, slope(84)), (84, slope(84) + d), (70, slope(70) + d)], "none", dash=True)
    side.line(60, slope(60), 196, slope(196), DIM, 0.8, dash=True)
    side.dim(64, slope(70), 64, slope(70) + d, "a", 58, slope(70) + d / 2 + 4, "end")
    for i, line in enumerate(["a: Back plate below the", "ring supports. At 0 the", "plate's bottom and the",
                              "supports (dashed line)", "make one flat face.", "(A pocket's bottom is", "flat at Bottom Y.)"]):
        side.text(204, 120 + 12 * i, line, anchor="start", size=9, color=DIM)
    side.dim(206, bot, 206, top, "Lip height", 210, 82, "start")
    side.text(210, 94, "(% of held height)", anchor="start", size=9)
    return LEGEND + front.svg() + side.svg()


def shelf_sketch() -> str:
    side = Sketch(220, "Shelf: side view")
    bx, x0, x1 = 30, 44, 256        # back plate from bx to x0; shelf out to x1
    sb, depth, floor = 196, 34, 16   # shelf bottom, pocket depth, floor
    top = sb - depth - floor
    side.rect(bx - 16, 20, 16, 190, BOARD, 0.9)                          # board
    side.rect(bx, 34, x0 - bx, sb - 34, HOLDER, 0.85)                    # back plate
    side.poly([(x0, top), (x0, top - 60), (x0 + 50, top)], HOLDER, 0.4)   # gusset (at the shelf ends)
    side.poly([(x0, top), (104, top), (104, top + depth), (232, top + depth), (232, top), (x1, top),
               (x1, sb), (x0, sb)], HOLDER, 0.85)                        # shelf with the pocket cut in
    side.rect(92, top - 16, 12, 16, HOLDER, 0.85)                        # rim
    side.rect(232, top - 16, 12, 16, HOLDER, 0.85)
    side.rect(108, 40, 120, top + depth - 40, OBJECT, 0.55)              # the object standing in the pocket
    side.dim(268, top, 268, top + depth, "Pocket depth", 272, top + depth / 2 + 3, "start")
    side.dim(268, top + depth, 268, sb, "Floor", 272, sb - 3, "start")
    side.line(x1, top, 272, top, dash=True, sw=0.6)
    side.dim(250, top - 16, 250, top, "Rim height", 256, top - 18, "start")
    side.dim(232, top - 30, 244, top - 30, "Rim thickness", 250, top - 34, "start")
    side.leader(x0 + 10, top - 12, 60, 54, "Support gussets")
    side.dim(bx, sb + 10, x0, sb + 10, "Back plate", x0 + 4, sb + 14, "start")
    side.text(168, 70, "object", size=9, color="#fff")
    side.text(168, 82, "(Object height:", size=9, color="#fff")
    side.text(168, 93, "preview only)", size=9, color="#fff")
    top_v = Sketch(176, "Shelf: top view")
    top_v.rect(20, 22, 300, 12, BOARD, 0.9)                             # board, seen from above
    top_v.rect(40, 34, 260, 12, HOLDER, 0.85)                           # back plate
    top_v.rect(60, 46, 220, 104, HOLDER, 0.85)                          # shelf
    top_v.rect(84, 58, 172, 76, "none", stroke=DIM, dash=True)          # pocket = outline + gap
    top_v.rect(92, 66, 156, 60, OBJECT, 0.55)                           # object footprint
    top_v.dim(60, 160, 84, 160, "Shelf margin", 88, 164, "start")
    top_v.line(60, 150, 60, 164, dash=True, sw=0.6)
    top_v.line(84, 134, 84, 164, dash=True, sw=0.6)
    top_v.dim(84, 100, 92, 100, "Gap", 80, 104, "end")
    top_v.text(170, 100, "footprint", size=9, color="#fff")
    top_v.text(320, 16, "board", anchor="end", size=9)
    return LEGEND + side.svg() + top_v.svg() + (
        '<div style="font-size:11px;margin:0 4px 6px">Cut all the way through: no floor, the pocket is a hole '
        '(for handles and shafts).</div>')


def pegs_sketch() -> str:
    side = Sketch(214, "Pegs: side section")
    bx0, bx1 = 120, 146
    side.rect(bx0, 34, bx1 - bx0, 152, BOARD, 0.9)                      # board
    for hy in (72, 158):                                                # holes
        side.rect(bx0, hy - 9, bx1 - bx0, 18, "bg", 1.0, stroke="none")
        side.line(bx0, hy - 9, bx1, hy - 9, sw=0.6)
        side.line(bx0, hy + 9, bx1, hy + 9, sw=0.6)
    side.rect(bx1, 40, 16, 150, HOLDER, 0.85)                           # back plate
    # hook through the upper hole, curving up behind the board
    hy, r, xs, big = 72, 6, 110, 22                                     # peg axis, radius, curve start, radius
    tip = hy - 38

    def arc(rad, a0, a1):  # points on a circle about the curve's centre (SVG y points down)
        return [(xs + rad * math.cos(math.radians(a)), hy - big + rad * math.sin(math.radians(a)))
                for a in (a0 + (a1 - a0) * i / 12 for i in range(13))]

    xr = xs - big                                                       # the rise's axis
    cap = [(xr + r * math.cos(math.radians(a)), tip - r * math.sin(math.radians(a))) for a in range(180, -1, -15)]
    side.poly([(bx1, hy + r), *arc(big + r, 90, 180), *cap, *arc(big - r, 180, 90), (bx1, hy - r)],
              HOLDER, 0.85)
    side.line(xs, hy - big, xs - (big - r) * 0.707, hy - big + (big - r) * 0.707, dash=True, sw=0.6)
    side.leader(xs - (big - r) * 0.5, hy - big + (big - r) * 0.3, 160, 22, "Hook bend radius")
    # straight pin through the lower hole
    side.rect(126, 158 - r, bx1 - 126, 2 * r, HOLDER, 0.85)
    side.dim(bx0, 200, bx1, 200, "Board thickness", 133, 212)
    side.line(bx0, 186, bx0, 204, dash=True, sw=0.6)
    side.line(bx1, 186, bx1, 204, dash=True, sw=0.6)
    side.dim(xs, 98, bx0, 98, "Extra peg length", xs - 4, 102, "end")
    side.line(xs, hy + r, xs, 102, dash=True, sw=0.6)
    side.line(bx0, 90, bx0, 102, dash=True, sw=0.6)
    side.line(xr - r - 2, tip, 60, tip, dash=True, sw=0.6)
    side.line(xr + 2, hy, 60, hy, dash=True, sw=0.6)
    side.dim(64, hy, 64, tip, "Hook rise", 60, (hy + tip) / 2 + 3, "end")
    side.dim(176, hy - 9, 176, hy + 9, "Hole diameter", 182, hy - 2, "start")
    side.text(182, hy + 10, "(peg = hole − Peg clearance)", anchor="start", size=9)
    side.dim(200, hy, 200, 158, "Pins: holes below hooks", 204, 118, "start")
    side.line(162, hy, 204, hy, dash=True, sw=0.6)
    side.line(162, 158, 204, 158, dash=True, sw=0.6)
    side.dim(126, 176, bx1, 176, "Pin length", 112, 180, "end")
    side.text(bx0 - 4, 140, "back of board", anchor="end", size=9)
    side.text(bx1 + 20, 34, "holder", anchor="start", size=9)
    front = Sketch(176, "Pegs: front view of the board")
    sp = 34
    xs = [40 + i * sp for i in range(9)]
    for yy in (58, 92, 126):
        for x in xs:
            front.circle(x, yy, 5, "none", sw=0.7)
    front.rect(xs[2] - 20, 38, xs[6] - xs[2] + 40, 108, HOLDER, 0.3, dash=True)   # back plate
    for x in (xs[2], xs[4], xs[6]):                                     # hooks every 2nd hole
        front.circle(x, 58, 5, HOLDER, 0.9)
    for x in (xs[2], xs[4], xs[6]):                                     # pins one row down
        front.circle(x, 92, 4, HOLDER, 0.6)
    front.dim(xs[0], 156, xs[1], 156, "Hole spacing", xs[1] + 6, 160, "start")
    front.dim(xs[2] - 20, 30, xs[2], 30, "Plate margin", xs[2] - 24, 34, "end")
    front.leader(xs[4], 58, xs[4] + 22, 18, "hooks: Peg columns,")
    front.text(xs[4] + 25, 32, "Use every Nth hole (here 2)", anchor="start", color=DIM)
    front.leader(xs[6], 92, xs[7] - 6, 112, "pins")
    return LEGEND + side.svg() + front.svg()


SKETCHES = {"flat": flat_sketch, "shelf": shelf_sketch, "pegs": pegs_sketch}
