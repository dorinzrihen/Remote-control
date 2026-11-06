#!/usr/bin/env python3
"""Write a stable screenshot page. Never open a window or periodically reload."""

import argparse
from html import escape
from pathlib import Path
import tempfile


CAPTURES = {
    "regular": ("Regular · 100% cool white", "Read-only sample"),
    "night": ("Night · 20% warm white", "Read-only sample"),
    "follow": ("Follow timetable", "Read-only sample"),
    "manage": ("Manage bulbs", "Read-only sample"),
    "connected": ("Connected · earlier build", "Live Mac"),
    "timetable": ("Edit timetable · earlier build", "Live Mac"),
    "setup": ("Old setup — being removed", "Live Mac"),
    "advanced": ("Old advanced setup — being removed", "Read-only sample"),
}


def write_gallery(output: Path) -> None:
    """Render existing actual screenshots, without fabricating missing captures.

    setup/connected/timetable are live-Mac captures; the other captures use
    read-only sample data. The page deliberately has no automatic reload.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def screenshot(key):
        title, source = CAPTURES[key]
        name = f"bulbs-{key}.png"
        path = output / name
        note = '<span class="limitation">LIMITATION · no Follow marker</span>' if key == "follow" else ""
        caption = f'<figcaption><strong>{escape(title)}</strong>{note}<small>{source}</small></figcaption>'
        if not path.is_file():
            content = f'<div class="missing">Awaiting actual capture: {name}</div>'
        else:
            stat = path.stat()
            url = f"{name}?v={stat.st_mtime_ns}-{stat.st_size}"
            content = (f'<a href="{url}" data-enlarge aria-label="Enlarge {escape(title)}">'
                       f'<img src="{url}" alt="Actual Android screenshot: {escape(title)}" '
                       'width="1080" height="2400" decoding="async"></a>')
        return f'<figure data-capture="{key}">{caption}{content}</figure>'

    modes = ''.join(screenshot(key) for key in ("regular", "night", "follow"))
    body = f'''
<header><h1>Bulbs — screenshots</h1></header>
<main>
<section class="screens three" id="modes" aria-label="Regular, Night, and Follow screenshots">{modes}</section>
<p class="tiny">Follow currently looks like Night: the highlight shows observed bulb output, not whether Follow was selected.</p>
<section class="management" aria-label="Manage bulbs screenshot">
{screenshot("manage")}
<aside><h2>Manage bulbs</h2><p><b>Blink</b> → identify a bulb</p><p><b>Hold Remove</b> → remove a saved bulb</p><p><b>Find new bulbs</b> → Room → Add</p><p class="tiny">Firmware and last-observed age, when available. No existing-room rename control.</p></aside>
</section>
<section class="screens two" aria-label="Connected and timetable screenshots">{screenshot("connected")}{screenshot("timetable")}</section>
<details id="old-setup"><summary>Old setup / Advanced — being removed</summary>
<p class="tiny">Your choice: anyone on Wi-Fi controls lights and schedule. No passwords or pairing codes. Removal is in progress; these are old captures.</p>
<section class="screens two">{screenshot("setup")}{screenshot("advanced")}</section>
<div class="old-notes"><p><b>Why a code?</b> Assistant-added choice, not requested or technically required.</p><p><b>Manager password</b> (v1.7: “Butler token”): the assistant generated it on the Mac without giving you a usable transfer flow. The code was its chosen way to give that password to the phone. Both are being removed.</p><p><b>Butler Lights</b> selected the manager, not a light. A sole manager was selected automatically.</p><p><b>Advanced:</b> old manual Mac-address / manager-password fallback.</p></div>
</details>
</main>
<footer>Actual emulator screenshots · Live Mac = real manager status · Read-only sample = no hardware commands
'''
    if (output / "UniRemote-Preview.apk").is_file():
        body += '<a href="UniRemote-Preview.apk" download>Download test APK</a>'
    body += '''</footer>
<dialog id="lightbox" aria-label="Enlarged screenshot"><button id="close" type="button">Close</button><img id="large" alt="" width="1080" height="2400"></dialog>
'''
    page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Bulbs — screenshots</title><style>' + STYLE + '</style></head><body>'
            + body + '<script>' + SCRIPT + '</script></body></html>\n')
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output,
                                     prefix=".gallery-", suffix=".html", delete=False) as temporary:
        temporary.write(page)
        temp_path = Path(temporary.name)
    temp_path.replace(output / "index.html")


STYLE = r'''
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#15191f;color:#edf0f5;font:14px/1.45 system-ui,sans-serif;margin:0}header,main,footer{max-width:1070px;margin:auto}header{padding:10px 16px}h1{font-size:17px;margin:0;font-weight:600}h2{font-size:17px;margin:0 0 14px}main{padding:0 16px 20px}.screens{display:grid;gap:16px;align-items:start}.three{grid-template-columns:repeat(3,minmax(0,1fr))}.two{grid-template-columns:repeat(2,minmax(0,1fr));max-width:700px;margin:24px auto}figure{margin:0;min-width:0}figcaption{height:71px;padding:8px 0;display:flex;flex-direction:column;align-items:flex-start;gap:3px;font-size:13px}figcaption small{color:#a7b2c2;font-size:10px}.limitation{color:#f6cb8c;font-size:10px}figure a{display:block;width:100%;max-width:330px;border:1px solid #3a424d;border-radius:9px;overflow:hidden;cursor:zoom-in}figure img{display:block;width:100%;height:auto}.tiny{font-size:12px;color:#b4bfce;margin:12px 0}.management{display:grid;grid-template-columns:330px 1fr;gap:32px;padding:20px 0;margin-top:24px;border-top:1px solid #343b46}.management aside{padding-top:71px}.management aside p{margin:10px 0}.management b{color:#a5e2ce}details{border-top:1px solid #343b46;padding:16px 0;margin-top:22px}summary{cursor:pointer;color:#c8d2df;font-size:13px}.old-notes{font-size:12px;color:#b4bfce;max-width:700px;margin:auto}.missing{min-height:250px;border:1px dashed #778293;padding:30px;color:#c9a972}footer{padding:15px 16px;color:#8f9dad;font-size:10px;border-top:1px solid #343b46}footer a{float:right;color:#a5e2ce}dialog{background:#15191f;border:1px solid #647085;border-radius:10px;padding:0;max-width:96vw;max-height:94vh}dialog::backdrop{background:#000c}dialog img{display:block;width:min(540px,88vw);height:auto}dialog button{position:sticky;top:8px;left:8px;padding:6px 12px;border-radius:7px;border:1px solid #a0adbc;background:#1d2633;color:white;cursor:pointer}@media(max-width:650px){.three{gap:7px}figcaption{font-size:10px;height:78px}.limitation,figcaption small{font-size:8px}.management{grid-template-columns:minmax(0,1fr);gap:8px}.management figure{max-width:330px;margin:auto}.management aside{padding-top:8px}.two{gap:10px}}
'''

SCRIPT = r'''
(() => {
  const key = 'bulbs-stable-screenshots';
  const box = document.getElementById('lightbox');
  const large = document.getElementById('large');
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(key) || '{}'); } catch (_) {}
  (saved.details || []).forEach(id => { const d = document.getElementById(id); if (d) d.open = true; });
  document.querySelectorAll('[data-enlarge]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    large.src = link.querySelector('img').src;
    large.alt = link.querySelector('img').alt;
    box.showModal();
  }));
  document.getElementById('close').addEventListener('click', () => box.close());
  box.addEventListener('click', event => { if (event.target === box) box.close(); });
  function persist() {
    try { sessionStorage.setItem(key, JSON.stringify({y: window.scrollY,
      details: [...document.querySelectorAll('details[open]')].map(d => d.id)})); } catch (_) {}
  }
  window.addEventListener('pagehide', persist);
  window.addEventListener('load', () => window.scrollTo(0, saved.y || 0));
  // No timers, fetching, or reloads: the page stays still while being reviewed.
})();
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".local/preview/live"))
    args = parser.parse_args()
    write_gallery(args.output)
    print("Screenshots:", args.output / "index.html")


if __name__ == "__main__":
    main()
