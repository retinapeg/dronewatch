import hashlib
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dronewatch.demo_feed import copy_once, make_handler, parse_args


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


def test_no_watched_folder_is_assumed_and_interval_is_bounded(tmp_path, monkeypatch):
    monkeypatch.delenv("DRONEWATCH_DRIVE_FOLDER", raising=False)
    source = tmp_path / "source.mp4"
    source.touch()
    assert parse_args(["--source", str(source)]).watch_dir is None
    with pytest.raises(SystemExit):
        parse_args(["--source", str(source), "--interval", "2"])


def test_video_range_requests_and_no_directory_access(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"0123456789")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(source))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(Request(base + "/mq9-reaper.mp4", headers={"Range": "bytes=2-5"})) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 2-5/10"
            assert response.read() == b"2345"
        with pytest.raises(HTTPError) as invalid:
            urlopen(Request(base + "/mq9-reaper.mp4", headers={"Range": "bytes=20-30"}))
        assert invalid.value.code == 416
        with pytest.raises(HTTPError) as listing:
            urlopen(base + "/")
        assert listing.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
