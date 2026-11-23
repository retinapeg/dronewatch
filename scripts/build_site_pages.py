#!/usr/bin/env python3
"""Build the hosted static pages (site/index.html, site/preview/index.html) from preview.html.

The hosted demo has no server, so the page is the operator view with:
  * a fetch() shim that serves the recorded replays under site/api/,
  * relative asset paths, and
  * links and wording that do not point at server-only pages.

Every edit below must match preview.html exactly once. If the operator view
changes so that an edit no longer matches, this script fails rather than
publishing a page that has drifted from the real one.

    python scripts/build_site_pages.py            # write both pages
    python scripts/build_site_pages.py --check    # exit 1 if the committed pages are stale
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/retinapeg/dronewatch"

SHIM = """<script>
/* Static demo (GitHub Pages): no server. The tracker ran once in Python over seed-42 synthetic
   observations for every scenario, contact count and sensor-loss mode; each replay is a recorded
   JSON file under api/. fetch() is redirected there, so the page's own code is unchanged. */
(function(){
  const real=window.fetch.bind(window);
  const json=(text)=>new Response(text,{status:200,headers:{'Content-Type':'application/json'}});
  // The two status files never change while the page is open, so each is fetched once however often it is polled.
  const kept={};
  const once=(path)=>{
    if(!kept[path]) kept[path]=real(path).then(r=>{if(!r.ok) throw new Error(r.status);return r.text();}).catch(e=>{delete kept[path];throw e;});
    return kept[path].then(json);
  };
  window.fetch=function(url,opts){
    const u=String(url);
    if(u.startsWith('/api/preview/tracks')){
      const q=new URL(u,location.origin).searchParams;
      return real(`{base}api/tracks__${q.get('name')||'operator_demo'}__${q.get('seed')||'42'}__${q.get('count')||'6'}__${q.get('mode')||'normal'}.json`,opts);
    }
    if(u.startsWith('/api/preview/paths')){
      const q=new URL(u,location.origin).searchParams, b=Math.floor(parseFloat(q.get('t')||'0')/2);
      return real(`{base}api/paths/${q.get('name')}__${q.get('seed')}__${q.get('count')}__${q.get('mode')}__${q.get('track')}__${b}.json`,opts);
    }
    if(u.startsWith('/api/preview/viso/status')) return once('{base}api/viso_status.json');
    if(u.startsWith('/api/camera/status')) return once('{base}api/camera_status.json');
    if(u.startsWith('/api/preview/viso/evidence')) return Promise.resolve(json(JSON.stringify({results:[],uncorrelated_results:[],pending_count:0,static_demo:true})));
    return real(url,opts);
  };
})();
</script>

"""

# (text in preview.html, replacement in the hosted page). "{base}" is "" at the
# site root and "../" one level down.
EDITS: list[tuple[str, str]] = [
    ("<head>\n", "<head>\n" + SHIM),
    (".airframe-image{background-image:url('/assets/drone-types.png')",
     ".airframe-image{background-image:url('{base}assets/drone-types.png')"),
    ("art.src='/assets/drone-types.png';", "art.src='{base}assets/drone-types.png';"),
    ('SIMULATION · NOT LIVE</span>', 'SIMULATION · NOT LIVE · RECORDED REPLAYS</span>'),
    ('<a class="camera-link" href="/camera" title="Camera clips and Viso Now results">CAMERA RESULTS ↗</a>',
     f'<a class="camera-link" href="{REPOSITORY}#operator-preview" target="_blank" rel="noopener" '
     'title="The camera check runs with the server; see the repository">CAMERA CHECK ↗</a>'),
    ('<a class="diag" href="/preview/diagnostics">Diagnostics</a>',
     f'<a class="diag" href="{REPOSITORY}" target="_blank" rel="noopener">Source ↗</a>'),
    ('No camera clip is linked to this replay. The map still shows where the camera is cued.',
     'Camera clips and Viso Now results need the Python server. This hosted demo replays the tracker only.'),
    ('<a class="ev-more" href="/camera">All camera results ↗</a>',
     f'<a class="ev-more" href="{REPOSITORY}#operator-preview" target="_blank" rel="noopener">How the camera check works ↗</a>'),
]


def build(source: str, base: str) -> str:
    page = source
    for old, new in EDITS:
        if page.count(old) != 1:
            raise SystemExit(f"build_site_pages: expected exactly one match in preview.html for: {old[:70]!r}")
        page = page.replace(old, new.replace("{base}", base))
    return page


def pages() -> dict[Path, str]:
    source = (ROOT / "preview.html").read_text(encoding="utf-8")
    return {
        ROOT / "site" / "index.html": build(source, ""),
        ROOT / "site" / "preview" / "index.html": build(source, "../"),
    }


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (sys.argv[1:] if argv is None else argv)
    stale = []
    for path, content in pages().items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale: " + ", ".join(map(str, stale)) + " — run python scripts/build_site_pages.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
