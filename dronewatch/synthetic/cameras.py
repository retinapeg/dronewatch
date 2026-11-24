"""Fixed security cameras as a drone sensor: how far each can see, and where they stand.

A camera's reach against a small drone is set by pixels on target. A drone of
width s at range R seen through a lens with horizontal field of view HFOV on a
sensor N_x pixels wide covers

    n = s / (R * theta_px),    theta_px = HFOV / N_x   (radians per pixel)

pixels. Below a handful of pixels there is nothing for a detector to work
with, so the reach of a camera is the range at which the drone still covers
`MIN_PIXELS`:

    R_max = s / (MIN_PIXELS * theta_px)

Reach therefore depends on the lens and the drone, and for ordinary security
cameras it is short: a 4K camera with a 40 degree lens sees a 1.2 m drone at 8
pixels out to about 0.8 km, and a 0.35 m camera drone only to about 0.24 km. A
long 12 degree lens stretches that to 2.7 km for the large drone, over a strip
never more than 576 m wide (N_x * s / MIN_PIXELS, whatever the lens). Warning
distance comes mostly from where the cameras stand, not from how far each one
sees. Field results are worse than this optical limit in haze, low contrast or
heavy video compression; nothing here models those.

A camera gives a good bearing and a poor range. The bearing is limited by how
well the camera's own pointing is known (taken as 0.1 degrees), not by its
pixels. The range comes only from how large the drone looks against an assumed
size, which is uncertain by tens of percent.

Everything in this module is a simulation assumption, not a specification of
any product.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

#: The drone the reach figures are for: a heavy-lift multirotor about 1.2 m
#: across (the DJI Matrice 600 class). Reach scales in proportion to size, so a
#: 0.35 m camera drone is seen at under a third of these distances.
TARGET_SIZE_M = 1.2
#: Pixels across the drone below which a camera reports nothing.
MIN_PIXELS = 8.0
#: One-sigma bearing and elevation error, degrees: how well a fixed camera's
#: pointing is known. A pixel is far smaller than this.
BEARING_SIGMA_DEG = 0.1
ELEVATION_SIGMA_DEG = 0.1
#: One-sigma error of the range-from-apparent-size, in log terms (a factor of ~1.4).
RANGE_LOG_SIGMA = 0.35
#: How often a camera's video is analysed, and how often a drone in view is picked up.
ANALYSIS_HZ = 2.0
DETECTION_PROBABILITY = 0.9
#: The height the near edge of each view is drawn for, metres above ground.
NOMINAL_ALTITUDE_M = 95.0
#: The reach of the site's radar against the same drone. A published tracking
#: range for a short-range counter-drone radar against this class is 1.4 km;
#: a medium-range radar reaches several times further and would see the drone
#: before these cameras do.
SHORT_RANGE_RADAR_REACH_M = 1400.0


def pixel_angle_rad(hfov_deg: float, width_px: int) -> float:
    """Angle one pixel covers, radians."""
    return math.radians(hfov_deg) / width_px


def pixels_on_target(size_m: float, range_m: float, hfov_deg: float, width_px: int) -> float:
    """How many pixels wide an object of `size_m` is at `range_m`."""
    return size_m / (range_m * pixel_angle_rad(hfov_deg, width_px))


def reach_m(hfov_deg: float, width_px: int, size_m: float = TARGET_SIZE_M,
            min_pixels: float = MIN_PIXELS) -> float:
    """The range at which the object still covers `min_pixels`."""
    return size_m / (min_pixels * pixel_angle_rad(hfov_deg, width_px))


@dataclass(frozen=True)
class FixedCamera:
    """One existing camera: where it stands, where it looks and its lens."""
    camera_id: str
    #: The place it stands, as an operator would call it.
    place: str
    x: float
    y: float
    #: Centre of view, degrees, mathematical convention (0 east, 90 north).
    heading_deg: float
    hfov_deg: float
    #: Height of the mount above the ground, metres.
    height_m: float = 6.0
    width_px: int = 3840

    @property
    def reach_m(self) -> float:
        return reach_m(self.hfov_deg, self.width_px)

    @property
    def vfov_deg(self) -> float:
        """Height of a 16:9 picture, degrees. Its lower edge is taken to sit on the horizon."""
        return self.hfov_deg * 9.0 / 16.0

    def near_m(self, altitude_m: float = NOMINAL_ALTITUDE_M) -> float:
        """Closer than this, a drone at `altitude_m` is above the top of the picture."""
        return max(0.0, altitude_m - self.height_m) / math.tan(math.radians(self.vfov_deg))

    @property
    def location(self) -> Tuple[float, float]:
        return (self.x, self.y)


#: A fan of long-lens cameras from one place: one camera per `spread_deg`, side by side.
def _fan(prefix: str, place: str, x: float, y: float, headings: Tuple[float, ...], hfov_deg: float,
         height_m: float) -> List[FixedCamera]:
    return [FixedCamera(f"{prefix}-{index}", place, x, y, heading, hfov_deg, height_m=height_m)
            for index, heading in enumerate(headings, start=1)]


#: Thirty-two cameras at fourteen places round the fictional site, all 4K.
#:
#: * Four ordinary wide cameras on the site's own fence. Each sees a 1.2 m drone
#:   only within about 0.8 km of itself, which from the fence is 1.4 km from the
#:   centre of the site: no further than the radar. They are here to show what
#:   an ordinary lens gives, which is no early warning at all.
#: * A fan of six long-lens cameras on each of the two northern corners of the
#:   fence, 850 m apart, and one more on the west and east sides. Each fan sees
#:   the northern approach out to 2.75 km. From two corners the same drone is
#:   seen from two directions 16 to 47 degrees apart, so the pair works as a
#:   rangefinder with an 850 m base, and a drone that flies in stays in the
#:   same two views for a long time.
#: * Cameras 1.5 to 2.4 km out, at the gate, two masts and two outbuildings to
#:   the north, looking further up the approach and across it, and on the
#:   roads to the east, south and west. The northern ones see a drone first,
#:   3.3 to 3.4 km from the site. Each mast also has one camera looking back
#:   across the flank of the approach, where the corner fans end.
#:
#: The layout is deliberate: the demonstration approach comes from the north,
#: and a view that does not cross another gives a direction but never a position.
#: It was arranged for the demonstration's seed (42). On other seeds a contact
#: that strays to the edge of the fans is held by one camera, or by none, for
#: part of its approach; experiments/camera_network.py measures how often.
CAMERA_NETWORK: List[FixedCamera] = [
    FixedCamera("cam-fence-n", "N FENCE", 0.0, 600.0, 90.0, 40.0, height_m=8.0),
    FixedCamera("cam-fence-e", "E FENCE", 600.0, 0.0, 0.0, 40.0, height_m=8.0),
    FixedCamera("cam-fence-s", "S FENCE", 0.0, -600.0, 270.0, 40.0, height_m=8.0),
    FixedCamera("cam-fence-w", "W FENCE", -600.0, 0.0, 180.0, 40.0, height_m=8.0),
    *_fan("cam-nw", "NW CORNER", -425.0, 425.0, (56.0, 68.0, 80.0, 92.0, 104.0, 116.0), 12.0, 8.0),
    *_fan("cam-ne", "NE CORNER", 425.0, 425.0, (124.0, 112.0, 100.0, 88.0, 76.0, 64.0), 12.0, 8.0),
    FixedCamera("cam-fence-w-long", "W FENCE", -600.0, 0.0, 48.0, 12.0, height_m=8.0),
    FixedCamera("cam-fence-e-long", "E FENCE", 600.0, 0.0, 132.0, 12.0, height_m=8.0),
    FixedCamera("cam-gate-n", "N GATE", 0.0, 1500.0, 90.0, 12.0),
    FixedCamera("cam-gate-nw", "N GATE", 0.0, 1500.0, 125.0, 16.0),
    FixedCamera("cam-gate-ne", "N GATE", 0.0, 1500.0, 55.0, 16.0),
    FixedCamera("cam-wmast-1", "W MAST", -1900.0, 1500.0, 40.0, 16.0, height_m=25.0),
    FixedCamera("cam-wmast-2", "W MAST", -1900.0, 1500.0, 65.0, 16.0, height_m=25.0),
    FixedCamera("cam-emast-1", "E MAST", 1900.0, 1500.0, 140.0, 16.0, height_m=25.0),
    FixedCamera("cam-emast-2", "E MAST", 1900.0, 1500.0, 115.0, 16.0, height_m=25.0),
    FixedCamera("cam-wmast-3", "W MAST", -1900.0, 1500.0, 350.0, 20.0, height_m=25.0),
    FixedCamera("cam-emast-3", "E MAST", 1900.0, 1500.0, 190.0, 20.0, height_m=25.0),
    FixedCamera("cam-pump", "PUMP HOUSE", -600.0, 1700.0, 75.0, 20.0),
    FixedCamera("cam-depot", "DEPOT", 600.0, 1700.0, 105.0, 20.0),
    FixedCamera("cam-road-e", "E ROAD", 2000.0, -200.0, 0.0, 20.0),
    FixedCamera("cam-lane-s", "S LANE", 0.0, -1500.0, 270.0, 20.0),
    FixedCamera("cam-road-w", "W ROAD", -2000.0, -200.0, 180.0, 20.0),
]
CAMERA_IDS = tuple(camera.camera_id for camera in CAMERA_NETWORK)


def views() -> dict:
    """What each camera can see, in the plain form the tracking side takes (crossfix.View)."""
    return {camera.camera_id: {"x": camera.x, "y": camera.y, "z": camera.height_m, "heading_deg": camera.heading_deg,
                               "hfov_deg": camera.hfov_deg, "reach_m": camera.reach_m,
                               "max_elevation_deg": camera.vfov_deg}
            for camera in CAMERA_NETWORK}

