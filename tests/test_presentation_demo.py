import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from dronewatch.presentation_demo import PresentationDemo, install_presentation


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now


@pytest.mark.parametrize('scenario,category,identity', [('drone','DRONE','DW-001'),('aircraft','AIRCRAFT','AC-001'),('bird','BIRD','VC-001')])
def test_visual_detection_precedes_stable_track(scenario,category,identity):
    clock = Clock(); demo = PresentationDemo(clock); demo.start(scenario)
    assert demo.state()['track'] is None and demo.state()['detection'] is None
    clock.now = 3.1
    detected = demo.state()
    assert detected['detection']['class'] == category
    assert detected['track'] is None
    assert detected['measurement']['source'] == 'SIMULATED EO SENSOR'
    clock.now = 6.1
    first = demo.state()
    assert first['track']['track_id'] == identity
    for second in [8.,24.9,25.1,29.9,30.1,35.,100.]:
        clock.now = second
        current = demo.state(); track = current['track']
        assert track['track_id'] == identity
        assert track['range_m'] == pytest.approx(math.hypot(track['x'],track['y']))
        assert current == demo.state()
        if scenario != 'drone':
            assert current['threat'] == 'INFO'
            assert not any(e['category'] in ('HIGH','WARNING') for e in current['events'])
    assert current['complete'] and not current['running']
    assert demo.reset()['banner'] == 'AIRSPACE CLEAR'


def test_drone_warning_at_25_high_at_30_and_final_held():
    clock = Clock(); demo = PresentationDemo(clock); demo.start()
    for second, severity in [(24.9,'CONTACT'),(25.,'WARNING'),(29.9,'WARNING'),(30.,'HIGH'),(35.,'HIGH')]:
        clock.now = second
        state = demo.state()
        assert state['threat'] == severity
    final = demo.state()
    assert len(final['events']) == 7
    clock.now = 150
    assert demo.state() == final
    assert len({e['id'] for e in final['events']}) == 7


def test_all_scenario_api_controls_and_invalid_input():
    app=FastAPI(); install_presentation(app,PresentationDemo(Clock()))
    with TestClient(app) as client:
        for scenario in ('drone','aircraft','bird'):
            assert client.post('/api/stage/start',json={'scenario':scenario}).json()['scenario'] == scenario
            assert client.post('/api/stage/manual/acquire').json()['track'] is not None
            assert client.post('/api/stage/reset').json()['track'] is None
        assert client.post('/api/stage/start',json={'scenario':'bad'}).status_code == 400
        assert client.post('/api/stage/start',json={'scenario':[]}).status_code == 400
        assert client.get('/api/stage/state').headers['cache-control'] == 'no-store'
