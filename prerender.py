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
            part = pg.evaluate("""() => ({
                pregled: document.querySelector('#pregled').innerHTML,
                tabs: document.querySelector('#tabs').innerHTML,
                foot: document.querySelector('footer').innerHTML,
                title: document.title})""")
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
    (SITE / "index.html").write_text(html, encoding="utf-8", newline="")
    print(f"Pregled upisan u index.html ({len(part['pregled']) / 1e3:.0f} kB HTML-a)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # objava ide dalje i bez gotovog Pregleda
        print("Pregled nije upisan:", e, file=sys.stderr)
