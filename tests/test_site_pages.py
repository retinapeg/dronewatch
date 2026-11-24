"""The hosted static demo (site/) is built from the operator view and cannot drift from it.

A visitor to the hosted page has no server behind it, so every request the page
makes has to be answered by a recorded file or by the page's own shim.
"""
import importlib.util
import json
import math
from pathlib import Path
import re

import pytest

from dronewatch.api import preview

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
spec = importlib.util.spec_from_file_location("build_site_pages", ROOT / "scripts" / "build_site_pages.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)

SOURCE = (ROOT / "preview.html").read_text(encoding="utf-8")
# A root-relative path in a string, a template or a CSS url(): something only a server could answer.
SERVER_PATH = re.compile(r"""(?:["'`]|url\()(/[A-Za-z][\w./-]*)""")
# A file the page reaches relative to itself.
OWN_FILE = re.compile(r"""(?:["'`]|url\()((?:\.\./)?(?:api|assets)/)""")


def test_committed_pages_are_exactly_what_the_generator_writes():
    for path, content in site.pages().items():
        assert path.read_text(encoding="utf-8") == content, (
            f"{path.relative_to(ROOT)} is out of date: run python scripts/build_site_pages.py"
        )


def test_every_server_path_left_in_the_hosted_page_is_answered_by_the_shim():
    page = site.build(SOURCE, "")
    answered = set(re.findall(r"u\.startsWith\('([^']+)'\)", site.SHIM))
    assert answered, "the shim should name the server paths it answers"
    unanswered = set(SERVER_PATH.findall(page)) - answered
    # Clip addresses are only recognised by this prefix. The hosted page has no clips, so none is ever loaded.
    assert unanswered == {"/api/camera/media/"}


def test_links_to_server_only_pages_are_replaced():
    page = site.build(SOURCE, "")
    links = re.findall(r"""<a\b[^>]*\bhref=["']([^"']+)["']""", page)
    assert links, "the page should still have its links"
    # The links between the two demos stay on this page, which needs no server. Every other link
    # would lead to a page only the server has, and goes to the repository instead.
    same_page = [link for link in links if link.startswith("?demo=")]
    assert sorted(same_page) == ["?demo=cameras", "?demo=viso"]
    assert all(link.startswith("https://github.com/retinapeg/dronewatch") for link in links if link not in same_page)


def test_a_page_one_folder_down_reaches_its_files_one_folder_up():
    root, nested = site.build(SOURCE, ""), site.build(SOURCE, "../")
    assert set(OWN_FILE.findall(root)) == {"api/", "assets/"}
    assert set(OWN_FILE.findall(nested)) == {"../api/", "../assets/"}
    assert len(OWN_FILE.findall(nested)) == len(OWN_FILE.findall(root))


def test_an_edit_that_no_longer_matches_the_operator_view_stops_the_build():
    changed = SOURCE.replace("SIMULATION · NOT LIVE</span>", "SIM</span>")
    with pytest.raises(SystemExit, match="exactly one match"):
        site.build(changed, "")


def test_every_choice_on_the_page_has_a_recorded_replay():
    scenarios = re.search(r'<select id="scenario"[^>]*>(.*?)</select>', SOURCE, re.S).group(1)
    assert tuple(re.findall(r'<option value="([^"]+)"', scenarios)) == preview.OPERATOR_SCENARIOS
    counts = re.search(r'id="count-seg"[^>]*>(.*?)</div>', SOURCE, re.S).group(1)
    assert tuple(int(n) for n in re.findall(r'data-n="(\d+)"', counts)) == preview.CONTACT_CHOICES
    for name in preview.OPERATOR_SCENARIOS:
        for count in preview.CONTACT_CHOICES:
            for mode in preview.SENSOR_LOSS_MODES:
                assert (SITE / "api" / f"tracks__{name}__42__{count}__{mode}.json").is_file(), (name, count, mode)


def test_every_lost_contact_in_a_recorded_replay_has_its_recorded_path_cloud():
    recorded = {path.name for path in (SITE / "api" / "paths").iterdir()}
    needed = set()
    for replay in sorted((SITE / "api").glob("tracks__*.json")):
        name, seed, count, mode = replay.stem.split("__")[1:]
        for frame in json.loads(replay.read_text(encoding="utf-8"))["frames"]:
            for track in frame["tracks"]:
                if track.get("fresh") != "U":
                    # The shim asks for one cloud per two seconds of replay time.
                    needed.add(f"{name}__{seed}__{count}__{mode}__{track['id']}__{math.floor(frame['t'] / 2)}.json")
    assert needed, "the recorded replays should contain lost contacts"
    assert needed - recorded == set()


def test_recorded_status_files_use_the_servers_own_wording():
    viso = json.loads((SITE / "api" / "viso_status.json").read_text(encoding="utf-8"))
    # The page shows this state as "VISO · OFFLINE"; any other spelling is printed raw.
    assert viso["state"] == preview.VisoStatus.NOT_CONFIGURED
    assert viso["configured"] is False
    camera = json.loads((SITE / "api" / "camera_status.json").read_text(encoding="utf-8"))
    assert camera["results"] == [] and "media" not in camera
