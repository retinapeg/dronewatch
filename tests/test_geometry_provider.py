import copy
import math

import pytest

from dronewatch.adsb_provider import normalize_aircraft, normalize_response
from dronewatch.geometry import Origin, enu_geometry, geodetic_to_enu


NOW = 1788513000.0


def aircraft(**changes):
    return {"hex": "406b90", "flight": "BAW281 ", "lat": 51.6, "lon": -.2,
            "alt_geom": 5000, "alt_baro": 4500, "gs": 200, "track": 90,
            "geom_rate": 600, "seen_pos": 2, **changes}


def test_origin_is_zero_and_unknown_angle_is_not_invented():
    origin = Origin()
    point = geodetic_to_enu(origin.latitude, origin.longitude, origin.altitude_m, origin)
    assert point["horizontal_range_m"] == pytest.approx(0, abs=1e-6)
    assert point["up_m"] == pytest.approx(0, abs=1e-6)
    assert point["slant_range_m"] == pytest.approx(0, abs=1e-6)
    assert point["azimuth_deg"] is None


@pytest.mark.parametrize("dlat,dlon,azimuth", [(.01,0,0),(0,.01,90),(-.01,0,180),(0,-.01,270)])
def test_cardinal_azimuths(dlat, dlon, azimuth):
    origin = Origin()
    point = geodetic_to_enu(origin.latitude+dlat, origin.longitude+dlon, 0, origin)
    error = (point["azimuth_deg"]-azimuth+180)%360-180
    assert error == pytest.approx(0, abs=.02)


def test_slant_range_and_elevation_are_derived_from_enu():
    point = enu_geometry(300, 400, 500)
    assert point["horizontal_range_m"] == 500
    assert point["slant_range_m"] == pytest.approx(math.sqrt(500000))
    assert point["elevation_deg"] == pytest.approx(45)
    assert point["azimuth_deg"] == pytest.approx(36.86989765)


def test_longitude_wrap_uses_short_distance_not_a_world_circumference():
    point = geodetic_to_enu(0, -179.999, 0, Origin(0,179.999,0))
    assert 222 < point["horizontal_range_m"] < 224
    assert point["azimuth_deg"] == pytest.approx(90)


@pytest.mark.parametrize("lat,lon",[(91,0),(0,181),(float('nan'),0),(0,float('inf')),('51',0),(True,0)])
def test_invalid_coordinates_are_rejected(lat, lon):
    with pytest.raises(ValueError):
        geodetic_to_enu(lat,lon,0)


def test_provider_units_and_best_available_altitude():
    point = normalize_aircraft(aircraft(r="G-TEST", t="A320"), NOW, NOW)
    assert point["track_id"] == "DW-406B90"
    assert point["callsign"] == "BAW281"
    assert point["registration"] == "G-TEST"
    assert point["aircraft_type"] == "A320"
    assert point["altitude_m"] == pytest.approx(1524)
    assert point["ground_speed_mps"] == pytest.approx(200*1852/3600)
    assert point["vertical_rate_mps"] == pytest.approx(3.048)
    assert point["position_observed_at"] == NOW-2
    assert point["heading_basis"] == "GROUND TRACK / COURSE"
    assert not point["synthetic"]


def test_missing_metadata_and_altitude_stay_null_and_baro_is_labelled():
    raw={"hex":"406b90","lat":51.6,"lon":-.2,"alt_baro":"ground"}
    point=normalize_aircraft(raw,NOW)
    assert point["on_ground"]
    for field in ["registration","callsign","aircraft_type","altitude_m","up_m","slant_range_m","elevation_deg","heading_deg","vertical_rate_mps"]:
        assert point[field] is None
    assert point["horizontal_range_m"] > 0
    baro=normalize_aircraft({**raw,"alt_baro":1000},NOW)
    assert baro["altitude_m"] == pytest.approx(304.8)
    assert "BAROMETRIC" in baro["altitude_basis"]


def test_normalisation_is_defensive_bounded_and_does_not_modify_provider_response():
    data={"now":NOW*1000,"ac":[aircraft(hex="%06x"%i, lat=51.51+i*.001) for i in range(100)]}
    data["ac"] += [None,{},aircraft(lat=None),aircraft(hex="~012345"),aircraft(alt_baro="ground"),aircraft(seen_pos=999)]
    original=copy.deepcopy(data)
    result=normalize_response(data,NOW)
    assert data == original
    assert len(result["tracks"]) == 60
    ranges=[track["horizontal_range_m"] for track in result["tracks"]]
    assert ranges == sorted(ranges)
    assert len({track["track_id"] for track in result["tracks"]}) == 60
    assert result["provider"] == "ADSB.LOL"
    for invalid in [None,[],{"ac":None},{"aircraft":[]}]:
        with pytest.raises(ValueError):
            normalize_response(invalid,NOW)
