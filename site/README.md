# Hosted static demo

This folder is what GitHub Pages serves. There is no server behind it.

- `index.html` and `preview/index.html` are the operator view (`preview.html`), built by
  `scripts/build_site_pages.py`. The build adds a small `fetch()` shim at the top of `<head>`, makes the
  asset paths relative, and replaces the links to server-only pages. Do not edit these two files by hand:
  a test fails if they differ from what the build writes.
- `api/tracks__*.json` is the tracker's recorded output (`GET /api/preview/tracks`) for every scenario,
  contact count and sensor mode at seed 42, written by calling the real
  `dronewatch.api.preview.get_tracks` once per combination.
- `api/paths/*.json` is the recorded Monte Carlo containment cloud (`GET /api/preview/paths`) for every
  lost contact in those replays, one per two seconds of replay time.
- `api/viso_status.json` and `api/camera_status.json` are what the server reports with no Viso Now
  connection and no camera clips.

Nothing is computed in the browser that the Python tracker did not compute first.

Not available here: camera clips and Viso Now results. The camera window says so. The camera turning to
groups of lost contacts is still shown, with lock brackets on the contacts it has picked up, because that
is part of the recorded replay. Run the server (see the top-level README) for the footage and the verdict.

The camera-network mode (`?demo=cameras`) is complete here: every camera, sight line, fix and the
early-warning counter come from the recorded replay.

## Rebuilding

```bash
python3 scripts/build_site_pages.py     # after any change to preview.html
python3 scripts/build_site.py           # after a tracker change: re-record the replays
rm -r site/api/paths                    # the next script keeps any cloud that already exists
python3 scripts/build_site_paths.py     # then re-record the path clouds
```

`python3 scripts/build_site_pages.py --check` exits with an error if the two pages are out of date.
`tests/test_site_pages.py` and `tests/site.test.cjs` check the pages, the shim and that every choice a
visitor can make has a recorded file behind it.
