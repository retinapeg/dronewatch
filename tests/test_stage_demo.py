import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from dronewatch.stage_demo import StageDemo, bearing, telemetry, gate_observation, install_stage, WARNING_RADIUS


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


def running():
    clock = Clock()
    demo = StageDemo(clock)
    demo.start()
    return clock, demo


@pytest.mark.parametrize('x,y,expected', [(0,1,0),(1,0,90),(0,-1,180),(-1,0,270)])
def test_cardinal_bearings(x,y,expected):
    assert bearing(x,y) == expected


def test_range_speed_heading_are_derived():
    value = telemetry((300,400,120), (3,4,12))
    assert value['range_m'] == 500
    assert value['altitude_m'] == 120
    assert value['speed_mps'] == 13
    assert value['heading_deg'] == pytest.approx(36.8698976)
    assert bearing(0,0) is None


def test_start_reset_deterministic_and_stable_identity():
    clock, demo = running()
    assert demo.state()['track'] is None
    for second in [3,8,20,30,37.2,45,60]:
        clock.now = second
        first = demo.state()
        assert first['track']['track_id'] == 'DW-001'
        assert first['track']['range_m'] == pytest.approx(math.hypot(first['track']['x'], first['track']['y']))
        assert demo.state() == first
    assert demo.reset()['track'] is None
    assert demo.state()['banner'] == 'AIRSPACE CLEAR'
    assert len(demo.state()['events']) == 1


def test_warning_and_restricted_are_real_zone_crossings():
    clock, demo = running()
    clock.now = 19.9
    assert demo.state()['threat'] == 'CONTACT'
    clock.now = 20.01
    warning = demo.state()
    assert warning['threat'] == 'WARNING'
    assert warning['track']['range_m'] <= WARNING_RADIUS
    clock.now = 42
    high = demo.state()
    assert high['threat'] == 'HIGH'
    assert high['track']['range_m'] <= 500
    assert high['banner'] == 'RESTRICTED AIRSPACE PENETRATION'


def test_dropout_has_no_measurement_prediction_moves_uncertainty_grows():
    clock, demo = running()
    clock.now = 28.9
    measured = demo.state()['track']
    clock.now = 30
    a = demo.state()
    clock.now = 35
    b = demo.state()
    assert a['measurement'] is None and b['measurement'] is None
    assert a['track']['confidence'] is None
    assert a['track']['state'] == b['track']['state'] == 'COASTING'
    assert b['track']['position_source'] == 'TRACK PREDICTION'
    assert b['track']['uncertainty_m'] > a['track']['uncertainty_m']
    assert b['track']['range_m'] < a['track']['range_m']
    assert b['track']['x'] == pytest.approx(measured['x'] + measured['vx'] * (35-28.9))
    assert b['track']['last_observation_age_s'] == 6.1
    assert any(point['predicted'] for point in b['track']['history'])
    assert 'ground_truth' not in b


def test_reacquisition_uses_spatial_gate_and_retains_identity():
    clock, demo = running()
    clock.now = 37.2
    state = demo.state()
    assert state['measurement'] is not None
    assert state['track']['state'] == 'REACQUIRED'
    assert state['track']['track_id'] == 'DW-001'
    assert state['association']['accepted'] is True
    assert state['association']['residual_m'] < 1
    assert state['track']['uncertainty_m'] == 20
    assert gate_observation((10,20,30), (11,21,31))['accepted']
    assert not gate_observation((1000,0,0), (0,0,0))['accepted']


def test_pause_resume_and_final_hold():
    clock, demo = running()
    clock.now = 15
    paused = demo.pause()
    clock.now = 25
    assert demo.state()['elapsed_s'] == paused['elapsed_s']
    demo.pause()
    clock.now = 30
    assert demo.state()['elapsed_s'] == 20
    clock.now = 100
    final = demo.state()
    clock.now = 200
    assert demo.state() == final
    assert final['threat'] == 'HIGH' and not final['running']
    assert final['track']['speed_mps'] == 0


def test_transitions_once_even_when_poll_skips_and_manual_controls():
    clock, demo = running()
    clock.now = 60
    first = demo.state()['events']
    assert len(first) == 10
    assert len({event['id'] for event in first}) == len(first)
    for _ in range(10): assert demo.state()['events'] == first
    assert demo.manual('acquire')['track']['track_id'] == 'DW-001'
    assert demo.manual('dropout')['track']['state'] == 'COASTING'
    assert demo.manual('reacquire')['track']['state'] == 'REACQUIRED'
    assert demo.manual('restricted')['threat'] == 'HIGH'
    with pytest.raises(ValueError): demo.manual('unknown')


def test_stage_api_controls_cache_policy_and_network_independence():
    app = FastAPI()
    install_stage(app, StageDemo(Clock()))
    with TestClient(app) as client:
        assert client.get('/api/stage/state').headers['cache-control'] == 'no-store'
        assert client.post('/api/stage/start').json()['running']
        assert client.post('/api/stage/pause').json()['running'] is False
        assert client.post('/api/stage/manual/dropout').json()['measurement'] is None
        assert client.post('/api/stage/manual/reacquire').json()['association']['accepted']
        assert client.post('/api/stage/manual/restricted').json()['threat'] == 'HIGH'
        assert client.post('/api/stage/manual/invalid').status_code == 400
        assert client.post('/api/stage/reset').json()['track'] is None
