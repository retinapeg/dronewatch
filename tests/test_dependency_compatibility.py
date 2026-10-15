"""Exercise the ASGI test stack in a fresh interpreter with strict warnings."""
import subprocess
import sys


def test_testclient_import_lifespan_and_request_without_deprecations():
    # Imports must happen in a fresh interpreter: prior tests can populate the
    # module cache and hide Starlette's deprecated AnyIO import.
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-W", "error::DeprecationWarning", "-c", """
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient

events = []

@asynccontextmanager
async def lifespan(app):
    events.append('started')
    yield
    events.append('stopped')

app = FastAPI(lifespan=lifespan)

@app.get('/probe')
def probe():
    return {'state': events.copy()}

with TestClient(app) as client:
    response = client.get('/probe')
    assert response.status_code == 200
    assert response.json() == {'state': ['started']}
assert events == ['started', 'stopped']
"""],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
