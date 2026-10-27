#!/usr/bin/env python3
"""
Gotov HTML Pregleda u objavljenoj stranici: otvori _site/index.html u pregledaču (ćirilica, podrazumevano),
uzme prikazan Pregled, meni i podnožje i upiše ih u _site/index.html. Posetilac tako vidi rezultate odmah,
pre nego što se izvrši kod; kod posle toga ponovo iscrta stranu (isti sadržaj, pa i drugo pismo ako je izabrano).

    python prerender.py [_site]

Ako pregledač nije dostupan ili nešto ne uspe, stranica ostaje kakva je (objava se ne prekida).
Na GitHub Actions koristi već instaliran Google Chrome (channel="chrome"); lokalno Playwright Chromium.
"""
import functools
import http.server
import re
import sys
import threading
from pathlib import Path

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve()


def main():
    from playwright.sync_api import sync_playwright
    html = (SITE / "index.html").read_text(encoding="utf-8")
    class Tih(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Tih, directory=str(SITE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(channel="chrome")
            except Exception:
                b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 390, "height": 844})  # širina telefona: oni od ovoga imaju najviše koristi
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html#pregled")
            pg.wait_for_function("document.querySelectorAll('#resTbl tbody tr').length>0", timeout=60000)
            if errs:
                raise RuntimeError(errs[0])
            grab = """() => ({
                pregled: document.querySelector('#pregled').innerHTML,
                tabs: document.querySelector('#tabs').innerHTML,
                foot: document.querySelector('footer').innerHTML,
                title: document.title})"""
            part = pg.evaluate(grab)
            # ista strana na latinici i engleskom: ko je izabrao to pismo, odmah vidi svoju verziju
            other = {}
            for s in ("lat", "en"):
                pg.evaluate(f"setScript('{s}')")
                pg.wait_for_timeout(300)
                other[s] = pg.evaluate(grab)
            b.close()
    finally:
        srv.shutdown()

    def put(h, pattern, inner):
        new, n = re.subn(pattern, lambda m: m.group(1) + inner + m.group(2), h, count=1, flags=re.S)
        if n != 1:
            raise RuntimeError("nije nađeno: " + pattern[:40])
        return new
    html = put(html, r'(<section id="pregled"[^>]*>).*?(</section>)', part["pregled"])
    html = put(html, r'(<nav[^>]*id="tabs"[^>]*>).*?(</nav>)', part["tabs"])
    html = put(html, r'(<footer>).*?(</footer>)', part["foot"])
    html = put(html, r'(<title>).*?(</title>)', part["title"].replace("&", "&amp;").replace("<", "&lt;"))
    # šabloni za latinicu i engleski + zamena odmah posle Pregleda, odnosno podnožja (pre glavnog koda),
    # po ?jezik= u adresi ili izboru sačuvanom u pregledaču
    pick = ('var q=new URLSearchParams(location.search).get("jezik"),s=["cyr","lat","en"].indexOf(q)>=0?q:localStorage.getItem("izbori2026.jezik");'
            'if(s!=="lat"&&s!=="en")return;var g=function(k){var t=document.getElementById("pre-"+s+"-"+k);return t?t.innerHTML:null};')
    tpl = "".join(f'<template id="pre-{s}-{k}">{v[k]}</template>' for s, v in other.items() for k in ("pregled", "tabs"))
    tpl += "".join(f'<template id="pre-{s}-title">{v["title"].replace("&", "&amp;").replace("<", "&lt;")}</template>' for s, v in other.items())
    swap1 = ('<script>(function(){try{' + pick +
             'var x=g("pregled");if(x!=null)document.getElementById("pregled").innerHTML=x;x=g("tabs");if(x!=null)document.getElementById("tabs").innerHTML=x;'
             'x=g("title");if(x!=null)document.title=x;document.documentElement.lang=s==="en"?"en":"sr-Latn";'
             'document.querySelectorAll("#lang button").forEach(function(b){b.setAttribute("aria-pressed",b.dataset.s===s)})'
             '}catch(e){}})()</script>')
    html = put(html, r'(<section id="pregled"[^>]*>.*?</section>)()', "\n" + tpl + swap1)
    tplf = "".join(f'<template id="pre-{s}-foot">{v["foot"]}</template>' for s, v in other.items())
    swap2 = '<script>(function(){try{' + pick + 'var x=g("foot");if(x!=null)document.querySelector("footer").innerHTML=x}catch(e){}})()</script>'
    html = put(html, r'(<footer>.*?</footer>)()', "\n" + tplf + swap2)
    (SITE / "index.html").write_text(html, encoding="utf-8", newline="")
    print(f"Pregled upisan u index.html ({len(part['pregled']) / 1e3:.0f} kB HTML-a, i na latinici i engleskom)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # objava ide dalje i bez gotovog Pregleda
        print("Pregled nije upisan:", e, file=sys.stderr)
