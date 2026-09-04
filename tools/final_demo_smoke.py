"""Real-time, offline API rehearsal. Starts drone, aircraft, bird, then drone again."""
import json
import math
import sys
import time
from urllib.request import Request, urlopen


base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else b"" if method == "POST" else None
    req = Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=3) as response:
        return json.load(response)


before = request("/api/events")["total_count"]
for iteration, scenario in enumerate(["drone", "aircraft", "bird", "drone"], 1):
    clear = request("/api/demo/reset", "POST")
    assert clear["system_state"] == "CLEAR" and clear["track"] is None
    state = request("/api/demo/start", "POST", {"scenario": scenario})
    assert state["running"] and state["track"] is None
    seen, tracks, previous_range = set(), set(), float("inf")
    started = time.monotonic()
    while True:
        state = request("/api/demo/state")
        phase = state["system_state"]
        if phase not in seen:
            print("RUN", iteration, scenario, round(state["elapsed_s"], 1), phase, flush=True)
        seen.add(phase)
        track = state["track"]
        if track:
            tracks.add(track["id"])
            assert math.isclose(track["range_m"], math.hypot(track["x"], track["y"]), abs_tol=1e-6)
            assert math.isclose(track["bearing_deg"], math.degrees(math.atan2(track["x"], track["y"])) % 360, abs_tol=1e-6)
            if scenario == "drone":
                assert track["range_m"] <= previous_range
                previous_range = track["range_m"]
        if scenario != "drone":
            assert state["severity"] == "NORMAL"
            assert not ({"HIGH", "WARNING"} & {e["category"] for e in state["events"]})
        if state["complete"]:
            break
        assert time.monotonic() - started < state["duration_s"] + 6
        time.sleep(.2)
    if scenario == "drone":
        assert {"CLEAR", "DETECTED", "ACQUIRED", "APPROACHING", "WARNING", "RESTRICTED"} <= seen
        assert tracks == {"DW-001"}
        assert len(state["events"]) == 5
    elif scenario == "aircraft":
        assert tracks == {"AC-001"} and "NORMAL" in seen
    else:
        assert tracks == {"BD-001"} and "NON_UAS" in seen
    time.sleep(1)
    assert request("/api/demo/state") == state, "Final state did not hold"
    print("PASS", scenario, "final state held; no duplicated events", flush=True)
assert request("/api/events")["total_count"] == before, "Demo touched persisted observations"
print("PASS ALL FOUR REHEARSALS; DRONE COMPLETED TWICE; DATABASE UNCHANGED", flush=True)
