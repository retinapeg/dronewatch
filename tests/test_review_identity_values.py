"""Manager-selected identity regression from Claude's final-review proposals.

The original proposed review checked only the number/type of identities.
This assertion checks exact values end-to-end and rejects silent normalization
or conflation of punctuation, composed characters, or combining marks.
"""
import importlib

from fastapi.testclient import TestClient


def test_identifier_values_preserve_punctuation_unicode_and_combining_marks(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "identity-values.db"))
    import main
    importlib.reload(main)
    identifiers = {"track_1", "track-1", "track.1", "drone-🚁", "target-é-̈", "ट्रैक-1"}
    with TestClient(main.app) as client:
        for index, target_id in enumerate(sorted(identifiers)):
            response = client.post("/webhook/viso", json={
                "event_id": f"identity-review-{index}",
                "target_id": target_id,
                "source": "camera-identity-review",
                "state": "DETECTED",
            })
            assert response.status_code == 200
        for _ in range(2):
            response = client.get("/api/targets")
            assert response.status_code == 200
            targets = response.json()["targets"]
            assert {item["target_id"] for item in targets} == identifiers
            assert len(targets) == len(identifiers)
            assert {item["source"] for item in targets} == {"camera-identity-review"}
            assert {item["source_kind"] for item in targets} == {"WEBHOOK_EVENT"}
