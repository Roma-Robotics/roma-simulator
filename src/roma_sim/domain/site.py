"""Spatial layout of the jobsite.

A `Site` is a rectangular footprint partitioned into named `Zone`s. Zones own work
locations (centroids) that tasks reference. The 2D kinematic layer (Tier 1.5) and
spatial conflict checks both consume this same geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    """A rectangular work area on the site.

    Coordinates are in meters, axis-aligned, with `(x, y)` the lower-left corner.
    The centroid is the canonical "work location" tasks anchor to.
    """

    id: str
    name: str
    x: float
    y: float
    width: float
    height: float

    @property
    def cx(self) -> float:
        return self.x + self.width / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.height / 2.0

    @property
    def centroid(self) -> tuple[float, float]:
        return (self.cx, self.cy)

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


@dataclass(frozen=True)
class Site:
    name: str
    width: float
    height: float
    zones: tuple[Zone, ...]

    def __post_init__(self) -> None:
        ids = [z.id for z in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate zone ids in site {self.name!r}: {ids}")

    def zone(self, zone_id: str) -> Zone:
        for z in self.zones:
            if z.id == zone_id:
                return z
        raise KeyError(f"unknown zone {zone_id!r}")


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.hypot(dx, dy)
