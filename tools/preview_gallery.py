#!/usr/bin/env python3
"""Write the screenshot review page; never open a browser or control hardware.

Call write_gallery(output) after capturing the live setup/connected/timetable
screens and copying the read-only fixture screens into the same directory.
Missing captures are explicitly marked, never replaced with mockups.
"""

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import tempfile


CAPTURES = {
    "setup": ("Old setup · being removed", "Live Mac"),
    "connected": ("Connected · default view", "Live Mac"),
    "advanced": ("Old advanced setup · being removed", "Read-only fixture"),
    "manage": ("Manage bulbs · expanded", "Read-only fixture"),
    "regular": ("Regular", "Read-only fixture"),
    "night": ("Night", "Read-only fixture"),
    "follow": ("Follow timetable", "Read-only fixture"),
    "timetable": ("Edit timetable · expanded", "Live Mac"),
}


def write_gallery(output: Path) -> None:
    """Create output/index.html from actual captures already in output.

    Provenance contract: setup, connected, timetable are live-Mac captures;
    advanced, manage, regular, night, follow are read-only fixture captures.
    This function does not capture, copy, modify, or fabricate screenshots.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assets = [f"bulbs-{key}.png" for key in CAPTURES] + ["UniRemote-Preview.apk"]
    stamps = {}
    for name in assets:
        path = output / name
        if path.is_file():
            stat = path.stat()
            stamps[name] = f"{stat.st_mtime_ns}-{stat.st_size}"

    def screenshot(key):
        name = f"bulbs-{key}.png"
        title, source = CAPTURES[key]
        pill = "live" if source == "Live Mac" else "fixture"
        caption = f'<figcaption>{escape(title)}<span class="pill {pill}">{source}</span></figcaption>'
        if name not in stamps:
            image = f'<div class="missing" role="status">Awaiting actual capture<small>{name}</small></div>'
        else:
            url = f"{name}?v={stamps[name]}"
            image = (f'<a class="capture" href="{url}" data-enlarge aria-label="Enlarge {escape(title)}">'
                     f'<img src="{url}" alt="Actual Android app screenshot: {escape(title)}" '
                     'width="900" height="2000" decoding="async">'
                     '<span class="zoom-hint">＋ Enlarge</span></a>')
        return f'<figure>{caption}{image}</figure>'

    body = '''
<header><div class="brand"><span class="brand-icon" aria-hidden="true">U</span><h1>UniRemote Preview</h1></div>
<div class="header-actions"><span class="pill neutral">Actual app captures</span><a class="download" href="UniRemote-Preview.apk" download>↓ Preview APK</a></div></header>
<nav aria-label="Screenshot sections">
<button type="button" data-tab="modes" aria-controls="modes">01 <span>Regular / Night / Follow</span></button>
<button type="button" data-tab="connection" aria-controls="connection">02 <span>Advanced</span></button>
<button type="button" data-tab="manage" aria-controls="manage">03 <span>Manage bulbs</span></button>
<button type="button" data-tab="timetable" aria-controls="timetable">04 <span>Timetable</span></button>
<button type="button" data-tab="setup" aria-controls="setup">05 <span>Old setup</span></button>
</nav>
<main>
<section id="setup" class="panel" aria-label="Setup">
<div class="section-heading"><h2>Old setup — being removed</h2><span class="pill warning">Earlier build</span></div>
<div class="small-warning">Your choice: anyone on Wi-Fi controls lights and schedule. No passwords or pairing codes. Change in progress.</div>
<div class="grid two">
<article class="card">SETUP_IMAGE
<div class="notes"><h3><span class="number">1</span> Why a pairing code?</h3>
<p><strong>Assistant-added choice, not requested.</strong> Six digits weren’t technically required. The old flow used them to give the phone the manager password. Both are being removed.</p>
<div class="password-card"><h4>Old manager password <small>v1.7: “Butler token”</small></h4><p>The assistant generated this secret on the Mac, but never gave you a usable way to transfer it. Your Wi-Fi-only policy needs neither this password nor a code.</p></div></div></article>
<article class="card">CONNECTED_IMAGE
<div class="notes"><h3><span class="number">2</span> What is “Butler Lights”?</h3>
<p>A <strong>manager selector</strong>, not a light control. One manager was selected automatically — no tap needed.</p>
<div class="callout"><span class="button-label">Butler Lights</span><span>→ Select the Mac</span></div></div></article>
</div></section>
<section id="connection" class="panel" aria-label="Connection">
<div class="section-heading"><h2>Advanced connection</h2><span class="pill warning">Old setup — being removed</span></div>
<div class="grid two"><article class="card">DEFAULT_IMAGE<div class="notes"><h3>Default · collapsed</h3><div class="callout"><span class="button-label">Advanced connection</span><span>→ Old manual fallback</span></div></div></article>
<article class="card">ADVANCED_IMAGE<div class="notes"><div class="callout"><span class="button-label">Manager URL</span><span>Mac address</span><span class="button-label">Token</span><span>Old manager password</span></div><p class="small-warning">Password / pairing removal is in progress. This is not the new Wi-Fi-only flow.</p></div></article></div></section>
<section id="manage" class="panel" aria-label="Manage bulbs">
<div class="section-heading"><h2>Add, identify, or remove bulbs.</h2></div>
<div class="grid feature"><article class="card">MANAGE_IMAGE</article><aside class="card guide"><h3>Inside “Manage bulbs”</h3>
<div class="feature-row"><span class="button-label">Saved bulbs</span><p>Firmware + last-observed age, when available.</p></div>
<div class="feature-row"><span class="button-label">Blink</span><p>Identify a bulb.</p></div>
<div class="feature-row"><span class="button-label">Hold Remove</span><p>Remove a saved bulb from the manager.</p></div>
<div class="feature-row"><span class="button-label">Find new bulbs</span><p>Discover → enter Room → Add to room.</p></div>
<div class="small-warning">No existing-room rename control is implemented.</div></aside></div></section>
<section id="modes" class="panel" aria-label="Light modes">
<div class="section-heading"><h2>Regular. Night. Follow.</h2><span class="pill fixture">Read-only fixture screens</span></div>
<div class="grid three">
<article class="card"><div class="mode-label">Regular <span>100% · cool white</span></div>REGULAR_IMAGE</article>
<article class="card"><div class="mode-label">Night <span>20% · warm white</span></div>NIGHT_IMAGE</article>
<article class="card"><div class="mode-label">Follow <span>Uses the schedule</span></div><div class="limitation"><span class="pill warning">LIMITATION</span><span>Looks like Night · no Follow marker</span></div>FOLLOW_IMAGE<div class="notes compact"><p>Highlight reflects <strong>observed bulb output</strong>, not Follow state. Android does not remember whether Follow was selected.</p></div></article>
</div></section>
<section id="timetable" class="panel" aria-label="Timetable">
<div class="section-heading"><h2>The schedule stays out of the way.</h2></div>
<div class="grid feature"><article class="card">TIMETABLE_IMAGE</article><aside class="card guide"><h3><span class="button-label">Edit timetable</span></h3><p>Expands night/day times, timezone, and polling interval.</p><div class="callout"><span class="button-label">Save timetable</span><span>→ Apply changes</span></div><p class="muted">Off bulbs stay off.</p></aside></div></section>
</main>
<footer><span>Preview installs beside the regular app · Unpublished</span><span>Live Mac = real manager status · Fixture = sample data, no hardware commands</span></footer>
<dialog id="lightbox" aria-label="Enlarged actual screenshot"><div class="lightbox-bar"><span id="lightbox-label"></span><button type="button" id="close-lightbox" aria-label="Close enlarged screenshot">✕ Close</button></div><img id="lightbox-image" alt="" width="900" height="2000"></dialog>
'''
    for marker, key in {
        "SETUP_IMAGE": "setup", "CONNECTED_IMAGE": "connected", "DEFAULT_IMAGE": "connected",
        "ADVANCED_IMAGE": "advanced", "MANAGE_IMAGE": "manage", "REGULAR_IMAGE": "regular",
        "NIGHT_IMAGE": "night", "FOLLOW_IMAGE": "follow", "TIMETABLE_IMAGE": "timetable",
    }.items():
        body = body.replace(marker, screenshot(key))
    if "UniRemote-Preview.apk" not in stamps:
        body = body.replace('<a class="download" href="UniRemote-Preview.apk" download>↓ Preview APK</a>',
                            '<span class="download muted">Preview APK pending</span>')
    revision = sha256((json.dumps(stamps, sort_keys=True) + body + STYLE + SCRIPT).encode()).hexdigest()[:20]
    page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="gallery-revision" content="{revision}">'
            '<title>UniRemote Preview</title><style>' + STYLE + '</style></head><body>'
            + body + '<script>' + SCRIPT + '</script></body></html>\n')
    # Atomic replacement prevents the open browser reading a half-written page.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output,
                                     prefix=".gallery-", suffix=".html", delete=False) as temporary:
        temporary.write(page)
        temp_path = Path(temporary.name)
    temp_path.replace(output / "index.html")


STYLE = r'''
:root{color-scheme:dark;--bg:#10141c;--card:#181f2b;--line:#2b3545;--text:#eff3fa;--muted:#a6b4c8;--mint:#95e5c7;--gold:#edc68b}
*{box-sizing:border-box}html{scroll-padding-top:90px}body{margin:0;background:radial-gradient(ellipse at 10% 0%,#1c2a35 0,transparent 45%),var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}button,a{-webkit-tap-highlight-color:transparent}button{font:inherit}a{color:inherit}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--mint);outline-offset:4px}
header,nav,main,footer{max-width:1120px;margin:auto}header{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:26px 24px 20px}.brand,.header-actions{display:flex;gap:12px;align-items:center}.brand-icon{display:grid;place-items:center;width:34px;height:34px;background:var(--mint);color:#102720;border-radius:11px;font-size:23px;font-weight:800}h1{font-size:23px;letter-spacing:-.7px;margin:0}h2{font-size:20px;letter-spacing:-.5px;margin:0}h3{font-size:15px;margin:0 0 8px}p{margin:5px 0;color:#ced7e4}.muted{color:var(--muted)}.pill{display:inline-flex;white-space:nowrap;border-radius:30px;padding:3px 8px;font-size:10px;font-weight:700;letter-spacing:.2px}.live{background:#183c35;color:#9ce6cd}.fixture{background:#30304b;color:#c4bafa}.neutral{color:var(--muted);border:1px solid var(--line)}.warning{background:#5a3c19;color:#ffdb99}.download{text-decoration:none;padding:8px 13px;border:1px solid #476d63;border-radius:9px;color:var(--mint);font-size:13px;font-weight:650}
nav{position:sticky;top:0;z-index:3;display:flex;gap:6px;padding:10px 24px;background:#10141cf2;backdrop-filter:blur(12px);border-bottom:1px solid var(--line);overflow:auto}nav button{white-space:nowrap;border:0;background:transparent;color:#73859d;padding:8px 13px;border-radius:9px;cursor:pointer;font-size:11px}nav button span{font-size:13px;margin-left:5px}nav button[aria-current="page"]{background:#253a38;color:var(--mint)}main{padding:22px 24px 32px}.panel[hidden]{display:none}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 16px}.sync{font-size:11px;color:var(--muted)}.pairing-strip{display:flex;align-items:center;gap:16px;padding:10px 15px;margin:0 0 18px;background:#1a2731;border:1px solid #2a3c47;border-radius:12px;color:#dce9f3}.pairing-strip b{color:var(--mint)}.pairing-strip i{margin-left:auto;font-size:12px;font-style:normal;color:var(--muted)}.grid{display:grid;gap:18px;align-items:start}.two{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:repeat(3,minmax(0,1fr))}.feature{grid-template-columns:minmax(300px,390px) minmax(250px,1fr)}.card{overflow:hidden;min-width:0;background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:0 9px 22px #0002}.notes,.guide{padding:17px 20px}.notes{border-top:1px solid var(--line)}figure{margin:0;padding:14px 14px 18px}figcaption{display:flex;justify-content:space-between;gap:6px;align-items:center;font-size:12px;font-weight:650;margin-bottom:13px}.capture{display:block;position:relative;width:100%;max-width:320px;margin:auto;border:1px solid #374359;border-radius:13px;overflow:hidden;cursor:zoom-in;background:#0c1017}.capture img{display:block;width:100%;height:auto}.zoom-hint{position:absolute;right:8px;bottom:8px;background:#10141cdd;border:1px solid #637189;color:white;border-radius:20px;padding:3px 8px;font-size:10px;opacity:0;transition:opacity .15s}.capture:hover .zoom-hint,.capture:focus .zoom-hint{opacity:1}.number{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:7px;background:#2c4440;color:var(--mint);margin-right:5px;font-size:12px}.callout{display:flex;align-items:center;flex-wrap:wrap;gap:9px;font-size:12px;color:var(--muted);margin-top:12px}.button-label{display:inline-block;padding:5px 10px;border:1px solid #536078;background:#111824;color:#e2eaf5;border-radius:7px;font-size:12px;font-weight:600}.feature-row{padding:14px 0;border-bottom:1px solid var(--line)}.feature-row p{font-size:13px;margin-top:7px}.small-warning{margin-top:17px;color:var(--gold);font-size:12px}.limitation{display:flex;align-items:center;gap:7px;padding:10px 12px;background:#342b21;color:#f0d9b5;font-size:11px;border-bottom:1px solid #5a452c}summary{padding:18px;font-weight:600;cursor:pointer}summary span{display:block;margin:6px 0 0 17px;color:#bdb6e3;font-weight:400;font-size:11px}.missing{width:100%;max-width:320px;min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;margin:auto;border:1px dashed #56647b;border-radius:13px;background:#101722;color:var(--muted);font-size:13px}.missing small{margin-top:8px;color:#8290a6}footer{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;padding:18px 24px 28px;border-top:1px solid var(--line);color:#8c9bb0;font-size:11px}
dialog{padding:0;background:#131a24;color:var(--text);border:1px solid #56647b;border-radius:14px;max-width:96vw;max-height:94vh;overscroll-behavior:contain}dialog::backdrop{background:#05080ddc;backdrop-filter:blur(6px)}.lightbox-bar{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:10px 14px;background:#131a24f5;z-index:1;font-size:12px}.lightbox-bar button{border:1px solid #56647b;border-radius:7px;padding:5px 10px;background:#253143;color:white;cursor:pointer}dialog img{display:block;width:min(540px,88vw);height:auto}
.mode-label{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;font-weight:700;border-bottom:1px solid var(--line)}.mode-label span{font-size:11px;font-weight:400;color:var(--muted)}.compact{padding:10px 14px;font-size:12px}.permission-flow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0;font-size:11px}.permission-flow span{padding:5px 8px;border:1px solid #456259;border-radius:7px;color:var(--mint)}.permission-flow b{color:var(--muted)}.password-card{margin-top:13px;padding:11px 12px;background:#111b25;border-left:2px solid var(--mint);border-radius:5px}.password-card h4{margin:0 0 4px;font-size:12px}.password-card small{display:block;color:var(--muted);font-weight:400}.password-card p{font-size:12px}
@media(min-width:1000px){.two figure{padding-left:30px;padding-right:30px}}@media(max-width:750px){header{padding:18px 16px}.header-actions .neutral{display:none}h1{font-size:20px}nav{padding:8px 12px}nav button{padding:8px}nav button span{margin-left:2px}main{padding:18px 14px}.two,.three,.feature{grid-template-columns:1fr}.section-heading{align-items:flex-start}h2{font-size:18px}.sync{display:none}.pairing-strip{gap:10px;flex-wrap:wrap}.pairing-strip i{margin-left:0}.grid{gap:15px}.capture{max-width:320px}footer{padding:18px 16px}}
'''


SCRIPT = r'''
(() => {
  const key = 'uniremote-preview-gallery-v2';
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(key) || '{}'); } catch (_) {}
  const panels = [...document.querySelectorAll('.panel')];
  let active = panels.some(p => p.id === saved.tab) ? saved.tab : 'modes';
  const box = document.getElementById('lightbox');
  const large = document.getElementById('lightbox-image');
  let enlarged = null;
  function persist() {
    const state = {tab: active, y: window.scrollY,
      details: [...document.querySelectorAll('details[open]')].map(d => d.id),
      enlarged, imageY: box.scrollTop};
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch (_) {}
  }
  function select(id) {
    active = id;
    panels.forEach(p => { p.hidden = p.id !== id; });
    document.querySelectorAll('[data-tab]').forEach(b => {
      if (b.dataset.tab === id) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
  }
  select(active);
  (saved.details || []).forEach(id => {
    const detail = document.getElementById(id);
    if (detail && detail.tagName === 'DETAILS') detail.open = true;
  });
  document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
    select(b.dataset.tab); window.scrollTo(0, 0); persist();
  }));
  function enlarge(link) {
    const image = link.querySelector('img');
    large.src = image.src; large.alt = image.alt;
    document.getElementById('lightbox-label').textContent = image.alt.replace('Actual Android app screenshot: ', '');
    enlarged = new URL(link.href).pathname.split('/').pop();
    if (!box.open) box.showModal();
    persist();
  }
  document.querySelectorAll('[data-enlarge]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); enlarge(link);
  }));
  document.getElementById('close-lightbox').addEventListener('click', () => box.close());
  box.addEventListener('close', () => { enlarged = null; persist(); });
  box.addEventListener('click', event => { if (event.target === box) box.close(); });
  document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', persist));
  window.addEventListener('pagehide', persist);
  window.addEventListener('beforeunload', persist);
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  window.addEventListener('load', () => {
    window.scrollTo(0, saved.y || 0);
    if (saved.enlarged) {
      const link = [...document.querySelectorAll('[data-enlarge]')].find(a =>
        new URL(a.href).pathname.split('/').pop() === saved.enlarged);
      if (link) { enlarge(link); box.scrollTop = saved.imageY || 0; }
    }
  });
  const revision = document.querySelector('meta[name="gallery-revision"]').content;
  let checking = false;
  async function refresh() {
    if (checking) return;
    if (location.protocol === 'file:') { persist(); location.reload(); return; }
    checking = true;
    try {
      const response = await fetch(location.href, {cache: 'no-store'});
      if (!response.ok) return;
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = html.querySelector('meta[name="gallery-revision"]');
      if (next && next.content !== revision) { persist(); location.reload(); }
    } catch (_) { /* Keep the existing gallery visible if the local server is down. */ }
    finally { checking = false; }
  }
  window.setInterval(refresh, 8000);
})();
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/preview/live"))
    args = parser.parse_args()
    write_gallery(args.output)
    print("Review page:", args.output / "index.html")


if __name__ == "__main__":
    main()
