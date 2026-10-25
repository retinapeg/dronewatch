"""WGS84 Earth-centred coordinates and local East/North/Up geometry."""
import math
from dataclasses import asdict, dataclass


WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def validate_coordinates(latitude, longitude):
    lat, lon = finite_number(latitude), finite_number(longitude)
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("latitude/longitude must be finite degrees within [-90,90] / [-180,180]")
    return lat, lon


@dataclass(frozen=True)
class Origin:
    latitude: float = 51.4995
    longitude: float = -0.1248
    altitude_m: float = 0.0
    name: str = "Palace of Westminster"

    def __post_init__(self):
        validate_coordinates(self.latitude, self.longitude)
        if finite_number(self.altitude_m) is None:
            raise ValueError("origin altitude must be finite")

    def snapshot(self):
        return {**asdict(self), "height_reference": "0 m WGS84 reference; not surveyed site elevation",
                "coordinate_frame": "WGS84 ECEF -> LOCAL ENU"}


def geodetic_to_ecef(latitude, longitude, altitude_m):
    lat, lon = validate_coordinates(latitude, longitude)
    if finite_number(altitude_m) is None:
        raise ValueError("altitude must be finite metres")
    phi, lam = math.radians(lat), math.radians(lon)
    radius = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi)**2)
    return ((radius+altitude_m)*math.cos(phi)*math.cos(lam),
            (radius+altitude_m)*math.cos(phi)*math.sin(lam),
            (radius*(1-WGS84_E2)+altitude_m)*math.sin(phi))


def enu_geometry(east_m, north_m, up_m):
    if finite_number(east_m) is None or finite_number(north_m) is None:
        raise ValueError("east/north must be finite metres")
    if up_m is not None and finite_number(up_m) is None:
        raise ValueError("up must be finite metres or null")
    horizontal = math.hypot(east_m, north_m)
    return {"east_m": east_m, "north_m": north_m, "up_m": up_m,
        "horizontal_range_m": horizontal,
        "azimuth_deg": math.degrees(math.atan2(east_m, north_m)) % 360 if horizontal > 1e-8 else None,
        "slant_range_m": math.hypot(horizontal, up_m) if up_m is not None else None,
        "elevation_deg": math.degrees(math.atan2(up_m, horizontal)) if up_m is not None and (horizontal > 1e-8 or abs(up_m)>1e-8) else None}


def geodetic_to_enu(latitude, longitude, altitude_m, origin=None):
    origin = origin or Origin()
    # Unknown altitude is used ONLY to project horizontal position at the datum.
    # Vertical/slant/elevation values remain null, never fabricated as zero.
    xyz = geodetic_to_ecef(latitude, longitude, altitude_m if altitude_m is not None else origin.altitude_m)
    centre = geodetic_to_ecef(origin.latitude, origin.longitude, origin.altitude_m)
    dx, dy, dz = (point-base for point,base in zip(xyz, centre))
    phi, lam = math.radians(origin.latitude), math.radians(origin.longitude)
    east = -math.sin(lam)*dx + math.cos(lam)*dy
    north = -math.sin(phi)*math.cos(lam)*dx - math.sin(phi)*math.sin(lam)*dy + math.cos(phi)*dz
    up = math.cos(phi)*math.cos(lam)*dx + math.cos(phi)*math.sin(lam)*dy + math.sin(phi)*dz
    return enu_geometry(east, north, up if altitude_m is not None else None)
