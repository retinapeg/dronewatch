"""Regression for a real-browser smoke-test failure: unrelated source traffic."""
import asyncio
from contextlib import suppress

from dronewatch.realtime import EventHub, stream_events


def test_other_source_traffic_does_not_starve_heartbeat():
    async def exercise():
        class Request:
            async def is_disconnected(self):
                return False

        class Runtime:
            def snapshot(self, mode):
                return {"mode": mode}

        hub = EventHub()
        stream = stream_events(
            Request(), hub, lambda: {"latest": None, "events": []},
            lambda start, end: [], Runtime(), "VISO_LIVE", heartbeat=0.01,
        )
        assert "event: snapshot" in await stream.__anext__()

        async def other_camera():
            while True:
                hub.publish("console", {"mode": "BENCHMARK_REPLAY"})
                await asyncio.sleep(0.001)

        producer = asyncio.create_task(other_camera())
        try:
            message = await asyncio.wait_for(stream.__anext__(), timeout=0.2)
            assert "event: heartbeat" in message
        finally:
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
            await stream.aclose()

    asyncio.run(exercise())
