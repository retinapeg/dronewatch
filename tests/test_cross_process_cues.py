"""The renderer and HTTP server must produce identical loss/camera timelines."""
import os
from pathlib import Path
import subprocess
import sys


def test_loss_timeline_and_camera_cues_ignore_python_hash_seed():
    code = '''
import hashlib, json
from dronewatch.synthetic.generator import pipeline_input, FaultSpec, T_ZERO
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.cueing import plan_camera_cues
from dronewatch.tracks.tracker import TrackerConfig
observations, scans = pipeline_input('operator_demo', seed=42, count=3,
    duration_s=55, faults=FaultSpec.parse('radar:40-70'))
timeline = build_timeline(observations, t_zero=T_ZERO, duration_s=55,
    scans=scans, admit=['radar-north'], config=TrackerConfig(drop_after_s=45))
cues = plan_camera_cues(timeline['frames'], (0.0,560.0), rest_deg=90.0)
assert any(c['target'] for c in cues if c['t'] >= 44)
print(hashlib.sha256(json.dumps([timeline,cues],sort_keys=True).encode()).hexdigest())
'''
    outputs = [subprocess.check_output(
        [sys.executable, '-c', code], text=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'PYTHONHASHSEED': seed},
    ) for seed in ['1', '7654321']]
    assert outputs[0] == outputs[1]
