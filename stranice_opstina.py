#!/usr/bin/env python3
"""
Posebna stranica za svaku opštinu (za Google i za pregled linka na mrežama): _site/opstina/<slug>/index.html
sa rezultatima svih listi, mapom sela i tabelom naselja (latinica), plus slika za pregled linka (og.png),
spisak svih opština (_site/opstina/index.html), sitemap.xml i robots.txt.

Sadržaj se uzima iz same objavljene stranice (otvori se u pregledaču, kao u prerender.py), pa su brojevi isti
kao na sajtu. Interaktivni prikaz ostaje na glavnom sajtu (#opstina/<slug>).

    python stranice_opstina.py [_site]

Ako nešto ne uspe, objava ide dalje bez ovih stranica.
"""
import functools
import html as H
import http.server
import re
import sys
import threading
from datetime import date
from pathlib import Path

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "_site").resolve()
BASE = "https://izbori26.rs"
LAT = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"})


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().translate(LAT)).strip("-")

# podaci za jednu opštinu, iz stranice (latinica); naselja: grupisano po r.nsl kao tabela „Po naseljima“
JS_OP = r"""i => {
  const o=OP[i],a=OP_AGG[i],rows=BY_OP[i];
  const g=new Map();for(const r of rows){const k=r.nsl||"";if(!g.has(k))g.set(k,[]);g.get(k).push(r)}
  const nas=[...g].map(([k,rs])=>{const x=agg(rs);return {name:k?T(k):"(naselje nije utvrđeno)",n:rs.length,up:x.up,
    turn:x.turn,win:x.va?x.win:-1,sh:x.va?x.v[x.win]/x.va:null}}).sort((p,q)=>q.up-p.up);
  // sažetak u rečenicama (jedinstven tekst za svaku opštinu); bez promene padeža naziva („u gradu Čačak“)
  const bareC=o.full.replace(/^(Градска општина|Град|Општина) /,""),bare=T(bareC); // „Чачак“ bez „Град“
  const loc=/^Градска општина /.test(o.full)?"u gradskoj opštini "+bare:/^Град /.test(o.full)?"u gradu "+bare:
    /Иностранство/.test(o.full)?"u inostranstvu":/Заводи/.test(o.full)?"u zavodima za izvršenje krivičnih sankcija":"u opštini "+bare;
  let sum="";
  if(a.va){
    const r=a.rank,Lq=k=>`„${LISTS[k].short}“ (${P(a.v[k]/a.va)})`;
    sum=`Na parlamentarnim izborima 25. oktobra 2026. ${loc} najviše glasova dobila je lista ${Lq(r[0])}`+(a.v[r[1]]?`, ispred liste ${Lq(r[1])}`:"")+(a.v[r[2]]?`, a treća je ${Lq(r[2])}`:"")+
      `. Izlaznost je bila ${P(a.turn)} (glasalo je ${N(a.gl)} od ${N(a.upd)} upisanih birača)`;
    const c=cmp23([i],a);
    if(c){const d=c.t1-c.t0;sum+=Math.abs(d)>=.005?`, što je ${PP(Math.abs(d))} ${d>0?"više":"manje"} nego na izborima 2023. (${P(c.t0)})`:", približno kao na izborima 2023.";
      sum+=`. Lista Aleksandra Vučića dobila je ${P(c.v1)} glasova, prema ${P(c.v0)} na izborima 2023`}
    sum+=".";
    const w=new Map();for(const e of nas)if(e.name&&e.win>=0&&e.name!=="(naselje nije utvrđeno)")w.set(e.win,(w.get(e.win)||0)+1);
    const nn=[...w.values()].reduce((s,x)=>s+x,0),ws=[...w].sort((x,y)=>y[1]-x[1]);
    if(nn>1&&!/Иностранство|Заводи/.test(o.full))sum+=` Od ${N(nn)} naselja, lista „${LISTS[ws[0][0]].short}“ je bila prva u ${N(ws[0][1])}`+(ws[1]?`, a „${LISTS[ws[1][0]].short}“ u ${N(ws[1][1])}`:"")+".";
    if(a.nd<a.n)sum+=` Rezultati su privremeni: obrađeno je ${N(a.nd)} od ${N(a.n)} biračkih mesta.`;
  }
  return {slug:opSlug(i),name:T(o.name),full:T(o.full),bare,bareC,nameC:o.name,fullC:o.full,okrug:T(OK[o.ok].name),status:statusLine(a),sum,sumC:cyr(sum),
    rows:listRows(a),nas:nas.map(e=>({...e,lst:e.win>=0?LISTS[e.win].short:"",c:e.win>=0?LISTS[e.win].c:"",
      shs:e.sh==null?"–":P(e.sh),ts:e.turn==null?"–":P(e.turn),ups:N(e.up)})),
    top:a.va?a.rank.slice(0,4).map(k=>({n:LISTS[k].short,c:LISTS[k].c,p:a.v[k]/a.va,ps:P(a.v[k]/a.va)})):[],
    turn:a.turn==null?"–":P(a.turn),nd:a.nd,n:a.n,win:a.win>=0?LISTS[a.win].short:"",
    winp:a.win>=0&&a.va?P(a.v[a.win]/a.va):""};
}"""


def page(op, css, fonts, snap, map_svg, legend, okr_links):
    e = H.escape
    url = f"{BASE}/opstina/{op['slug']}/"
    title = f"Rezultati izbora 2026: {op['bare']} ({op['bareC']}) – po biračkim mestima i selima"
    desc = (op["sum"].split(". Izlaznost")[0] + ". Mapa sela, rezultati po naseljima i biračkim mestima.") if op["sum"] else \
        f"Parlamentarni izbori 2026, {op['full']} ({op['okrug']}): rezultati po naseljima i biračkim mestima."
    nas_rows = "".join(
        f'<tr><td class="ttl" data-l="Naselje"><b>{e(x["name"])}</b></td><td class="num" data-l="Biračkih mesta">{x["n"]}</td>'
        f'<td class="num" data-l="Upisano">{x["ups"]}</td><td class="num" data-l="Izlaznost">{x["ts"]}</td>'
        f'<td data-l="Prva lista">' + (f'<span class="sw" style="background:{x["c"]}"></span>{e(x["lst"])} {x["shs"]}' if x["lst"] else "–")
        + "</td></tr>" for x in op["nas"])
    app = f"/#opstina/{op['slug']}"
    return f"""<!doctype html>
<html lang="sr-Latn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article"><meta property="og:site_name" content="izbori26.rs"><meta property="og:locale" content="sr_RS">
<meta property="og:url" content="{url}"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{url}og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#16294d"><link rel="icon" type="image/png" href="/ikona.png"><link rel="apple-touch-icon" href="/ikona.png">
{fonts}
<style>{css}
.stp{{max-width:1120px;margin:0 auto;padding:0 14px 30px}} .stp .cta{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}
.stp .mapsvg{{max-width:560px}} .stp h1{{margin-top:18px}} .stp a.btn,.top .bar a{{text-decoration:none}} .top .bar a:not(.brand){{color:var(--ink)}}
</style></head>
<body>
<header class="top"><div class="bar" style="max-width:1120px;margin:0 auto;padding:10px 14px;display:flex;gap:18px;align-items:center;flex-wrap:wrap">
<a class="brand" href="/">Izbori 2026</a><a href="/">Pregled</a><a href="/opstina/">Sve opštine</a><a href="/#mapa">Mapa</a><a href="{app}">Interaktivni prikaz</a></div></header>
<main class="stp">
<h1>Rezultati izbora 2026: {e(op['full'])} <span lang="sr-Cyrl" class="muted" style="font-weight:400;font-size:.6em;white-space:nowrap">{e(op['fullC'])}</span></h1>
<p class="lead">{e(op['sum']) or e(op['full'] + ', ' + op['okrug'] + '.')}</p>
{f'<p lang="sr-Cyrl" class="note">{e(op["sumC"])}</p>' if op['sum'] else ''}
<p class="note">{e(op['full'])}, {e(op['okrug'])}. {op['status']}</p>
<div class="cta"><a class="btn" href="{app}">Mapa sela, biračka mesta i poređenje sa 2023. →</a><a class="btn ghost" href="/#pregled">Gde ja glasam?</a></div>
<div class="block"><h2>Rezultati svih listi</h2><p class="note">Udeo u važećim glasovima, na biračkim mestima sa unetim rezultatom.</p>
<div class="dlg" style="padding:0;max-height:none;overflow:visible">{op['rows']}</div></div>
{f'<div class="block"><h2>Mapa sela: ko je prvi</h2><div class="lgd maplgd">{legend}</div><div class="mapwrap">{map_svg}</div><p class="note">Bleđa boja znači tesniju pobedu. Granice: © OpenStreetMap saradnici (ODbL).</p></div>' if map_svg else ""}
<div class="block"><h2>Rezultati po naseljima</h2><p class="note">Biračka mesta sabrana po naselju, poređano po broju upisanih birača.</p>
<div class="tw"><table class="cards"><thead><tr><th>Naselje</th><th class="num">Biračkih mesta</th><th class="num">Upisano</th><th class="num">Izlaznost</th><th>Prva lista</th></tr></thead><tbody>{nas_rows}</tbody></table></div></div>
<div class="cta"><a class="btn" href="{app}">Otvori {e(op['name'])} na sajtu →</a><a class="btn ghost" href="/opstina/">Sve opštine</a></div>
{okr_links}
<p class="note">Izvor: Republička izborna komisija, rezultati po biračkim mestima (unos do {e(snap)}). Privremeni, nezvanični prikaz. <a href="/#metodologija">O sajtu i metodologija</a> · Ćirilica i engleski na <a href="/">glavnom sajtu</a>.</p>
</main></body></html>"""


def main():
    from playwright.sync_api import sync_playwright
    idx = (SITE / "index.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r"<style>(.*?)</style>", idx, re.S))
    fonts = "\n".join(re.findall(r'<link rel="(?:preconnect|stylesheet)"[^>]*fonts\.g[^>]*>', idx))

    class Tih(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Tih, directory=str(SITE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ops = []
    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.launch(channel="chrome")
            except Exception:
                b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html#pregled")
            pg.wait_for_function("typeof OP!=='undefined'&&cur==='pregled'", timeout=60000)
            pg.evaluate("setScript('lat')")
            pg.evaluate("loadLazy('prethodni')")  # poređenje sa 2023. za sažetak
            snap = pg.evaluate("fmtSnap()")
            n = pg.evaluate("OP.length")
            card_dir = SITE / "opstina"
            for i in range(n):
                op = pg.evaluate(JS_OP, i)
                if not op["n"]:
                    continue
                pg.evaluate(f"go('opstina/{op['slug']}')")
                try:  # mapa sela (nema je za inostranstvo, zatvore i deo opština na Kosovu)
                    pg.wait_for_selector("#opMap svg", timeout=3000)
                except Exception:
                    pass
                map_svg = pg.evaluate("(()=>{const s=document.querySelector('#opMap .mapsvg');return s?s.outerHTML:''})()")
                legend = pg.evaluate("(()=>{const l=document.querySelector('#opMap .maplgd');return l?l.innerHTML:''})()")
                d = card_dir / op["slug"]
                d.mkdir(parents=True, exist_ok=True)
                op["_map"], op["_lgd"] = map_svg, legend
                # slika za pregled linka: naziv, prve liste i mapa sela
                pg.evaluate("""([op,svg])=>{let c=document.getElementById('ogcard');if(c)c.remove();c=document.createElement('div');c.id='ogcard';
                  c.style.cssText='position:fixed;left:0;top:0;width:1200px;height:630px;background:#fff;color:#101826;z-index:9999;display:flex;font-family:"Source Sans 3",Arial,sans-serif;box-sizing:border-box;padding:48px 52px;gap:36px';
                  const bars=op.top.map(t=>`<div style="margin:14px 0"><div style="display:flex;justify-content:space-between;font-size:30px"><span>${t.n}</span><b>${t.ps}</b></div><div style="height:16px;background:#e3e7ee;border-radius:3px;margin-top:6px"><div style="width:${Math.max(1,t.p*100)}%;height:100%;background:${t.c};border-radius:3px"></div></div></div>`).join('');
                  c.innerHTML=`<div style="flex:1 1 55%;display:flex;flex-direction:column"><div style="font:700 26px Literata,Georgia,serif;color:#16294d">Izbori 2026 · rezultati</div>
                    <div style="font:700 64px/1.05 Literata,Georgia,serif;margin:14px 0 4px">${op.name}</div><div style="font-size:26px;color:#566175">${op.okrug} · izlaznost ${op.turn}</div>
                    <div style="margin-top:22px">${bars}</div><div style="margin-top:auto;font-size:26px;color:#16294d;font-weight:700">izbori26.rs</div></div>
                    <div style="flex:1 1 45%;display:flex;align-items:center;justify-content:center">${svg}</div>`;
                  const s=c.querySelector('svg');if(s){s.style.maxWidth='100%';s.style.maxHeight='530px';s.style.width='100%';s.style.height='auto'}
                  document.body.appendChild(c)}""", [op, map_svg])
                pg.locator("#ogcard").screenshot(path=str(d / "og.png"))
                ops.append(op)
            b.close()
    finally:
        srv.shutdown()

    # stranice; na dnu linkovi na ostale opštine iz istog okruga (lakše obilaženje za Google i posetioce)
    by = {}
    for op in ops:
        by.setdefault(op["okrug"], []).append(op)
    for op in ops:
        sib = sorted((o for o in by[op["okrug"]] if o is not op), key=lambda o: o["name"])
        links = " · ".join(f'<a href="/opstina/{o["slug"]}/">{H.escape(o["name"])}</a>' for o in sib)
        okr = (f'<div class="block"><h2>Ostale opštine: {H.escape(op["okrug"])}</h2><p>{links}</p>'
               f'<p class="note"><a href="/opstina/#{slug(op["okrug"])}">Sve opštine po okruzima</a></p></div>') if sib else ""
        (card_dir / op["slug"] / "index.html").write_text(page(op, css, fonts, snap, op["_map"], op["_lgd"], okr), encoding="utf-8")

    # spisak svih opština, po okruzima (sidro #<okrug> za linkove sa stranica opština)
    lst = "".join(f'<div class="block" id="{slug(k)}"><h2>{H.escape(k)}</h2><p>' + " · ".join(
        f'<a href="/opstina/{o["slug"]}/">{H.escape(o["name"])}</a>' for o in sorted(v, key=lambda o: o["name"])) + "</p></div>"
        for k, v in by.items())
    (SITE / "opstina" / "index.html").write_text(f"""<!doctype html><html lang="sr-Latn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rezultati izbora 2026 po opštinama – izbori26.rs</title><meta name="description" content="Rezultati parlamentarnih izbora 2026. za svaku opštinu u Srbiji: liste, izlaznost, mapa sela i rezultati po naseljima.">
<link rel="canonical" href="{BASE}/opstina/"><meta property="og:image" content="{BASE}/og.png"><link rel="icon" type="image/png" href="/ikona.png">
{fonts}<style>{css}
.stp{{max-width:1120px;margin:0 auto;padding:0 14px 30px}} .stp p a{{white-space:nowrap}} .top .bar a{{text-decoration:none}} .top .bar a:not(.brand){{color:var(--ink)}}</style></head>
<body><header class="top"><div class="bar" style="max-width:1120px;margin:0 auto;padding:10px 14px;display:flex;gap:18px;align-items:center"><a class="brand" href="/">Izbori 2026</a><a href="/">Pregled</a><a href="/#mapa">Mapa</a></div></header>
<main class="stp"><h1>Rezultati izbora 2026 po opštinama</h1><p class="lead">Izaberi opštinu za rezultate svih listi, mapu sela i rezultate po naseljima.</p>{lst}</main></body></html>""", encoding="utf-8")
    today = date.today().isoformat()
    urls = [f"{BASE}/", f"{BASE}/opstina/"] + [f"{BASE}/opstina/{o['slug']}/" for o in ops]
    (SITE / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    print(f"Stranice opština: {len(ops)}, sitemap {len(urls)} adresa")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # objava ide dalje i bez ovih stranica
        print("Stranice opština nisu napravljene:", e, file=sys.stderr)
