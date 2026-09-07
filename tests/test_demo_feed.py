import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import demo_feed
from demo_feed import (
    CopyResult,
    ReplayFailure,
    ReplayInputs,
    atomic_copy,
    copy_once,
    make_handler,
    parse_args,
    run_replay,
)
from replay_artifacts import (
    ReplayFailureCode,
    ReplayState,
    load_replay_run_record,
)


ROOT = Path(__file__).resolve().parents[1]
CHECKED_MANIFEST = ROOT / "fixtures" / "halmstad-selection.v1.json"


def _replay_setup(tmp_path, *, source_bytes=b"bounded replay bytes" * 20, count=3):
    source = tmp_path / "V_DRONE_001.mp4"
    source.write_bytes(source_bytes)
    watched = tmp_path / "watched"
    watched.mkdir()
    records = tmp_path / "records"

    manifest_payload = json.loads(CHECKED_MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(source_bytes).hexdigest()
    fixture = manifest_payload["fixtures"][0]
    fixture["source_sha256"] = digest
    fixture["derived_sha256"] = digest
    fixture["source_bytes"] = len(source_bytes)
    fixture["derived_bytes"] = len(source_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")

    inputs = ReplayInputs(
        scenario_id="perimeter-demo",
        run_id="run-001",
        fixture_id=fixture["fixture_id"],
        manifest_path=manifest,
        source=source,
        watched_folder=watched,
        count=count,
        interval=20.0,
        record_dir=records,
    )
    return inputs, source, watched, records, digest


def _names(_run_id, _fixture_id, sequence):
    return f"copy-{sequence:03d}.mp4"


def test_copies_are_unique_complete_and_leave_original_unchanged(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"demo source bytes" * 100)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    watched = tmp_path / "watched"
    watched.mkdir()
    first, second = copy_once(source, watched), copy_once(source, watched)
    assert first != second
    assert first.suffix == second.suffix == ".mp4"
    assert first.read_bytes() == second.read_bytes() == source.read_bytes()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert set(watched.iterdir()) == {first, second}
    assert not list(watched.glob("*.part"))


def test_cli_has_explicit_nonwriting_serve_and_bounded_replay_modes(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    serve = parse_args(["serve", "--source", str(source)])
    assert serve.command == "serve"
    assert not hasattr(serve, "watch_dir")

    base = [
        "replay",
        "--scenario-id",
        "scenario",
        "--run-id",
        "run",
        "--fixture-id",
        "fixture",
        "--manifest",
        "manifest.json",
        "--source",
        str(source),
        "--watch-dir",
        str(tmp_path),
    ]
    with pytest.raises(SystemExit):
        parse_args(base)
    with pytest.raises(SystemExit):
        parse_args(base + ["--count", "0"])
    with pytest.raises(SystemExit):
        parse_args(base + ["--count", "21"])
    with pytest.raises(SystemExit):
        parse_args(base + ["--count", "1", "--interval", "2"])
    with pytest.raises(SystemExit):
        parse_args(
            [part if part != "scenario" else "." for part in base]
            + ["--count", "1"]
        )


def test_video_range_requests_and_no_directory_access(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"0123456789")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(source))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(
            Request(base + "/mq9-reaper.mp4", headers={"Range": "bytes=2-5"})
        ) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 2-5/10"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read() == b"2345"
        with urlopen(
            Request(base + "/mq9-reaper.mp4", headers={"Range": "bytes=-3"})
        ) as response:
            assert response.read() == b"789"
        with urlopen(Request(base + "/mq9-reaper.mp4", method="HEAD")) as response:
            assert response.status == 200
            assert response.read() == b""
        with urlopen(
            Request(
                base + "/mq9-reaper.mp4",
                headers={"Origin": "http://127.0.0.1:8000"},
            )
        ) as response:
            assert response.headers["Access-Control-Allow-Origin"] == (
                "http://127.0.0.1:8000"
            )
            assert response.headers["Vary"] == "Origin"
            assert response.headers["Access-Control-Allow-Private-Network"] is None
        with urlopen(
            Request(
                base + "/mq9-reaper.mp4",
                method="OPTIONS",
                headers={"Origin": "http://localhost:8000"},
            )
        ) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == (
                "http://localhost:8000"
            )
            assert response.headers["Access-Control-Allow-Private-Network"] is None
        with pytest.raises(HTTPError) as hostile_origin:
            urlopen(
                Request(
                    base + "/mq9-reaper.mp4",
                    headers={"Origin": "https://attacker.example"},
                )
            )
        assert hostile_origin.value.code == 403
        with pytest.raises(HTTPError) as hostile_host:
            urlopen(
                Request(
                    base + "/mq9-reaper.mp4",
                    headers={"Host": "attacker.example"},
                )
            )
        assert hostile_host.value.code == 403
        with pytest.raises(HTTPError) as invalid:
            urlopen(
                Request(base + "/mq9-reaper.mp4", headers={"Range": "bytes=20-30"})
            )
        assert invalid.value.code == 416
        with pytest.raises(HTTPError) as pathological_range:
            urlopen(
                Request(
                    base + "/mq9-reaper.mp4",
                    headers={"Range": "bytes=" + ("9" * 5_000) + "-"},
                )
            )
        assert pathological_range.value.code == 416
        with pytest.raises(HTTPError) as listing:
            urlopen(base + "/")
        assert listing.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_finite_replay_stops_at_exact_count_and_writes_relative_record(tmp_path):
    inputs, source, watched, records, digest = _replay_setup(tmp_path, count=3)
    sleeps = []

    assert (
        run_replay(
            inputs,
            sleep_fn=sleeps.append,
            basename_fn=_names,
        )
        == 0
    )

    assert sleeps == [20.0, 20.0]
    assert [path.name for path in sorted(watched.iterdir())] == [
        "copy-001.mp4",
        "copy-002.mp4",
        "copy-003.mp4",
    ]
    assert all(path.read_bytes() == source.read_bytes() for path in watched.iterdir())
    assert not list(watched.glob("*.part"))

    record_path = records / "run-001.json"
    record = load_replay_run_record(record_path)
    assert record.state is ReplayState.SUCCEEDED
    assert record.completed_count == record.requested_count == 3
    assert [copy.sequence_number for copy in record.copies] == [1, 2, 3]
    assert {copy.source_sha256 for copy in record.copies} == {digest}
    assert {copy.completed_copy_sha256 for copy in record.copies} == {digest}
    assert all("/" not in copy.destination_basename for copy in record.copies)
    retained = record_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in retained
    assert "LOCAL_ATOMIC_COPY_ONLY_NOT_DRIVE_SYNC" in retained


def test_run_record_is_reserved_before_copy_and_updated_after_each_copy(tmp_path):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=2)
    observations = []

    def observing_copy(source, folder, basename, expected):
        current = load_replay_run_record(records / "run-001.json")
        observations.append((current.state, current.completed_count, len(current.copies)))
        return atomic_copy(source, folder, basename, expected)

    assert (
        run_replay(
            inputs,
            sleep_fn=lambda _seconds: None,
            basename_fn=_names,
            copy_fn=observing_copy,
        )
        == 0
    )
    assert observations == [
        (ReplayState.RUNNING, 0, 0),
        (ReplayState.RUNNING, 1, 1),
    ]
    assert len(list(watched.glob("*.mp4"))) == 2


def test_existing_run_record_prevents_any_copy_or_overwrite(tmp_path, capsys):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=1)
    records.mkdir()
    record = records / "run-001.json"
    record.write_text("do not overwrite", encoding="utf-8")

    assert run_replay(inputs, sleep_fn=lambda _seconds: None) == 1
    assert record.read_text(encoding="utf-8") == "do not overwrite"
    assert list(watched.iterdir()) == []
    assert "RECORD_ALREADY_EXISTS" in capsys.readouterr().out


def test_manifest_hash_mismatch_fails_before_record_or_copy(tmp_path, capsys):
    inputs, source, watched, records, _digest = _replay_setup(tmp_path, count=1)
    source.write_bytes(source.read_bytes() + b"tampered")

    assert run_replay(inputs, sleep_fn=lambda _seconds: None) == 1
    assert list(watched.iterdir()) == []
    assert not records.exists()
    assert "SOURCE_SIZE_MISMATCH" in capsys.readouterr().out


def test_copy_failure_is_not_retried_and_is_retained(tmp_path):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=3)
    attempts = []

    def fail_once(*_args):
        attempts.append(1)
        raise ReplayFailure(ReplayFailureCode.COPY_IO_FAILED)

    assert run_replay(inputs, sleep_fn=lambda _seconds: None, copy_fn=fail_once) == 1
    assert attempts == [1]
    assert list(watched.iterdir()) == []
    record = load_replay_run_record(records / "run-001.json")
    assert record.state is ReplayState.FAILED
    assert record.failure_code is ReplayFailureCode.COPY_IO_FAILED
    assert record.completed_count == 0
    assert len(record.copies) == 1
    assert record.copies[0].state is ReplayState.FAILED


def test_interruption_finalizes_record_without_retry(tmp_path):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=2)
    attempts = []

    def interrupt(*_args):
        attempts.append(1)
        raise KeyboardInterrupt

    assert run_replay(inputs, sleep_fn=lambda _seconds: None, copy_fn=interrupt) == 130
    assert attempts == [1]
    assert list(watched.iterdir()) == []
    record = load_replay_run_record(records / "run-001.json")
    assert record.state is ReplayState.INTERRUPTED
    assert record.failure_code is ReplayFailureCode.INTERRUPTED
    assert record.copies[0].state is ReplayState.INTERRUPTED


def test_interruption_between_reserved_record_and_copy_is_finalized(tmp_path):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=1)

    def interrupt_before_basename(*_args):
        raise demo_feed.TerminationRequested

    assert run_replay(inputs, basename_fn=interrupt_before_basename) == 143
    assert list(watched.iterdir()) == []
    record = load_replay_run_record(records / "run-001.json")
    assert record.state is ReplayState.INTERRUPTED
    assert record.failure_code is ReplayFailureCode.INTERRUPTED
    assert record.completed_count == 0
    assert record.copies == ()


def test_post_copy_interruption_reconciles_published_file_into_record(tmp_path):
    inputs, _source, watched, records, digest = _replay_setup(tmp_path, count=1)
    moments = iter(
        [
            datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 7, 12, 0, 1, tzinfo=timezone.utc),
        ]
    )

    def interrupting_clock():
        try:
            return next(moments)
        except StopIteration:
            raise demo_feed.TerminationRequested

    assert (
        run_replay(inputs, clock=interrupting_clock, basename_fn=_names) == 143
    )
    assert [path.name for path in watched.iterdir()] == ["copy-001.mp4"]
    record = load_replay_run_record(records / "run-001.json")
    assert record.state is ReplayState.INTERRUPTED
    assert record.failure_code is ReplayFailureCode.INTERRUPTED
    assert record.completed_count == 1
    assert len(record.copies) == 1
    assert record.copies[0].state is ReplayState.SUCCEEDED
    assert record.copies[0].completed_copy_sha256 == digest


def test_publication_window_interruption_reconciles_verified_file(
    tmp_path, monkeypatch
):
    inputs, _source, watched, records, digest = _replay_setup(tmp_path, count=1)
    real_fsync_directory = demo_feed._fsync_directory
    calls = 0

    def interrupt_after_publication(directory):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise demo_feed.TerminationRequested
        return real_fsync_directory(directory)

    monkeypatch.setattr(demo_feed, "_fsync_directory", interrupt_after_publication)
    assert run_replay(inputs, basename_fn=_names) == 143
    assert [path.name for path in watched.iterdir()] == ["copy-001.mp4"]
    record = load_replay_run_record(records / "run-001.json")
    assert record.state is ReplayState.INTERRUPTED
    assert record.failure_code is ReplayFailureCode.INTERRUPTED
    assert record.completed_count == 1
    assert len(record.copies) == 1
    assert record.copies[0].state is ReplayState.SUCCEEDED
    assert record.copies[0].completed_copy_sha256 == digest


def test_interrupted_record_reservation_removes_incomplete_file(tmp_path, monkeypatch):
    path = tmp_path / "reserved.json"
    record = demo_feed._new_run_record(
        demo_feed.prepare_replay(_replay_setup(tmp_path, count=1)[0]),
        demo_feed.utc_now(),
    )

    def interrupt_dump(_record):
        raise KeyboardInterrupt

    monkeypatch.setattr(demo_feed, "dump_artifact", interrupt_dump)
    with pytest.raises(KeyboardInterrupt):
        demo_feed._reserve_record(path, record)
    assert not path.exists()


def test_atomic_copy_interruption_removes_part_file(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"0123456789")
    watched = tmp_path / "watched"
    watched.mkdir()
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    real_open = Path.open

    class InterruptingReader:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.reads = 0

        def __enter__(self):
            self.wrapped.__enter__()
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def read(self, size=-1):
            self.reads += 1
            if self.reads == 2:
                raise KeyboardInterrupt
            return self.wrapped.read(size)

    def interrupting_open(path, *args, **kwargs):
        opened = real_open(path, *args, **kwargs)
        if path == source and args and args[0] == "rb":
            return InterruptingReader(opened)
        return opened

    monkeypatch.setattr(demo_feed, "COPY_CHUNK_BYTES", 4)
    monkeypatch.setattr(Path, "open", interrupting_open)
    with pytest.raises(KeyboardInterrupt):
        atomic_copy(source, watched, "destination.mp4", expected)
    assert list(watched.iterdir()) == []


def test_atomic_publication_does_not_clobber_racing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable source")
    watched = tmp_path / "watched"
    watched.mkdir()
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = watched / "destination.mp4"
    real_link = os.link

    def racing_link(temporary, requested_destination):
        assert requested_destination == destination
        destination.write_bytes(b"racing writer")
        return real_link(temporary, requested_destination)

    monkeypatch.setattr(demo_feed.os, "link", racing_link)
    with pytest.raises(ReplayFailure) as failure:
        atomic_copy(source, watched, destination.name, expected)
    assert failure.value.code is ReplayFailureCode.DESTINATION_EXISTS
    assert destination.read_bytes() == b"racing writer"
    assert not list(watched.glob("*.part"))


def test_completed_copy_is_hashed_after_publication_and_retained_on_mismatch(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable source")
    watched = tmp_path / "watched"
    watched.mkdir()
    destination = watched / "destination.mp4"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    real_hash = demo_feed.sha256_file

    def changed_published_hash(path):
        if path == destination:
            return "0" * 64
        return real_hash(path)

    monkeypatch.setattr(demo_feed, "sha256_file", changed_published_hash)
    with pytest.raises(ReplayFailure) as failure:
        atomic_copy(source, watched, destination.name, expected)
    assert failure.value.code is ReplayFailureCode.COMPLETED_COPY_HASH_MISMATCH
    assert destination.read_bytes() == source.read_bytes()
    assert not list(watched.glob("*.part"))


def test_source_and_record_location_boundaries_prevent_uncontrolled_writes(tmp_path):
    inputs, source, watched, records, _digest = _replay_setup(tmp_path, count=1)
    invalid_count = ReplayInputs(**{**inputs.__dict__, "count": 21})
    assert run_replay(invalid_count, sleep_fn=lambda _seconds: None) == 1
    assert list(watched.iterdir()) == []
    assert not records.exists()

    source_inside = watched / source.name
    source_inside.write_bytes(source.read_bytes())
    inside_inputs = ReplayInputs(**{**inputs.__dict__, "source": source_inside})
    assert run_replay(inside_inputs, sleep_fn=lambda _seconds: None) == 1
    assert set(watched.iterdir()) == {source_inside}

    source_inside.unlink()
    records_inside = ReplayInputs(**{**inputs.__dict__, "record_dir": watched / "records"})
    assert run_replay(records_inside, sleep_fn=lambda _seconds: None) == 1
    assert list(watched.iterdir()) == []


def test_invalid_destination_basename_cannot_escape_watched_folder(tmp_path):
    inputs, _source, watched, records, _digest = _replay_setup(tmp_path, count=1)
    assert (
        run_replay(
            inputs,
            sleep_fn=lambda _seconds: None,
            basename_fn=lambda *_args: "../escaped.mp4",
        )
        == 1
    )
    assert not (tmp_path / "escaped.mp4").exists()
    assert list(watched.iterdir()) == []
    record = load_replay_run_record(records / "run-001.json")
    assert record.failure_code is ReplayFailureCode.INVALID_DESTINATION_BASENAME
