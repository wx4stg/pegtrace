"""Shared holder result type and output orientation."""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .csg import Solid
from .pegs import PegLayout


@dataclass
class HolderResult:
    mode: str  # "flat" | "shelf"
    solid: Solid  # final printable body, mounted frame (x along board, y up, z out)
    parts: dict[str, Solid]  # individual parts for coloured previews
    regions: dict[str, BaseGeometry]  # 2D regions used to build it
    outline: Polygon  # object outline in the holder frame
    ghost: Solid  # object stand-in for previews
    keepout: Solid  # space the object needs (for collision checks)
    pegs: PegLayout
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def oriented(solid: Solid, orientation: str) -> Solid:
    """Transform a mounted-frame solid for export.

    ``print (upright)``: +y becomes +Z (the holder stands on its flat bottom),
    then the part is centred on the bed with its lowest point at Z = 0.
    ``as mounted``: board plane is XY, Z points out of the board.
    """
    if orientation.startswith("print"):
        s = solid.rotate(90, 0, 0)  # (x, y, z) -> (x, -z, y)
    else:
        s = solid
    lo, hi = s.bounds()
    return s.translate(-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])
