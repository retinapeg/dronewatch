"""Local demo video server and optional watched-folder copy loop. No app imports."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def copy_once(source: Path, watched_folder: Path) -> Path:
    """Publish a complete, uniquely named MP4; open the original read-only."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = watched_folder / f"mq9-demo-{stamp}-{uuid.uuid4().hex[:10]}.mp4"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".dronewatch-", suffix=".part", dir=watched_folder
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def make_handler(source: Path):
    class VideoHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Repeated video range requests should not obscure copy-loop output.
            pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Range")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()

        def do_HEAD(self):
            self.serve_video(head_only=True)

        def do_GET(self):
            self.serve_video()

        def serve_video(self, head_only=False):
            if urlsplit(self.path).path != "/mq9-reaper.mp4":
                self.send_error(404)
                return
            try:
                video = source.open("rb")
            except OSError:
                self.send_error(503, "Demo source video unavailable")
                return
            with video:
                size = os.fstat(video.fileno()).st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get("Range")
                if requested:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
                    valid = bool(match and (match[1] or match[2]))
                    if valid:
                        if match[1]:
                            start = int(match[1])
                            end = min(int(match[2]), size - 1) if match[2] else size - 1
                        else:
                            start = max(0, size - int(match[2]))
                        valid = 0 <= start <= end < size
                    if not valid:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                self.send_response(status)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head_only:
                    return
                video.seek(start)
                remaining = end - start + 1
                try:
                    while remaining:
                        chunk = video.read(min(128 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return VideoHandler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() / "Downloads/mq9-reaper.mp4")
    parser.add_argument(
        "--watch-dir", type=Path, default=os.environ.get("DRONEWATCH_DRIVE_FOLDER"),
        help="Existing local Google Drive folder already watched by Viso. No copies without this setting.",
    )
    parser.add_argument("--interval", type=float, default=25, help="Copy interval in seconds, between 20 and 30 (default 25).")
    parser.add_argument("--port", type=int, default=8001, help="Local-only video server port (default 8001).")
    parser.add_argument("--copy-only", action="store_true", help="Only copy files; use an already-running video server.")
    args = parser.parse_args(argv)
    args.source = args.source.expanduser().resolve()
    if not args.source.is_file():
        parser.error(f"Source MP4 does not exist: {args.source}")
    if not 20 <= args.interval <= 30:
        parser.error("--interval must be between 20 and 30 seconds")
    if args.watch_dir:
        args.watch_dir = args.watch_dir.expanduser().resolve()
        if not args.watch_dir.is_dir():
            parser.error(f"Watched folder must already exist: {args.watch_dir}")
    if args.copy_only and not args.watch_dir:
        parser.error("--copy-only requires --watch-dir or DRONEWATCH_DRIVE_FOLDER")
    return args


def main(argv=None):
    args = parse_args(argv)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    server = None
    worker = None
    try:
        if not args.copy_only:
            server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.source))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            print(f"DEMO SENSOR FEED: http://127.0.0.1:{args.port}/mq9-reaper.mp4", flush=True)
        print(f"Source (read-only): {args.source}", flush=True)
        print("Press Ctrl+C to stop cleanly.", flush=True)
        if not args.watch_dir:
            print("Copy loop OFF. Supply --watch-dir '/path/to/Google Drive/watched-folder' to enable.", flush=True)
            stop.wait()
        else:
            print(f"Copy loop ON: {args.watch_dir} / every {args.interval:g}s", flush=True)
            print("Each MP4 has a new name. Viso must already watch this synced folder; processing latency depends on Drive/Viso.", flush=True)
            while not stop.is_set():
                try:
                    destination = copy_once(args.source, args.watch_dir)
                    print(f"COPIED {destination.name}", flush=True)
                except OSError as error:
                    print(f"COPY FAILED: {error}. Retrying in {args.interval:g}s.", flush=True)
                stop.wait(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=2)
        print("Demo harness stopped. Original video and existing copied files are unchanged.", flush=True)


if __name__ == "__main__":
    main()
