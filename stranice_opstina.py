#!/usr/bin/env python3
"""
Posebna stranica za svaku opštinu (za Google i za pregled linka na mrežama), na ćirilici (podrazumevano, kao
glavni sajt) i latinici: _site/opstina/<slug>/index.html i _site/opstina/<slug>/lat/index.html, sa rezultatima
svih listi, mapom sela i tabelom naselja, plus slika za pregled linka (og.png), spisak svih opština
(_site/opstina/index.html i _site/opstina/lat/index.html), sitemap.xml i robots.txt.

Sadržaj se uzima iz same objavljene stranice (otvori se u pregledaču, kao u prerender.py), pa su brojevi isti
kao na sajtu; ćirilična verzija se preslovljava istom funkcijom kao na sajtu (locNode). Interaktivni prikaz
ostaje na glavnom sajtu (#opstina/<slug>).

    python stranice_opstina.py [_site]

Ako nešto ne uspe, objava ide dalje bez ovih stranica.
"""
import functools
import html as H
import http.server
import json
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

# podaci za jednu opštinu, iz stranice (na trenutnom pismu); naselja: grupisano po r.nsl kao tabela „Po naseljima“
JS_OP = r"""i => {
  const o=OP[i],a=OP_AGG[i],rows=BY_OP[i];
  const g=new Map();for(const r of rows){const k=r.nsl||"";if(!g.has(k))g.set(k,[]);g.get(k).push(r)}
  // popis 2022 (STAN, kao u tabeli „Po naseljima“): za „X и Y“ zbir naselja
  const sp=STAN[o.full]||{},popOf=k=>{const ps=k?k.split(/, | и /).map(n=>sp[n]):[];return ps.length&&ps.every(Boolean)?ps.reduce((s,p)=>s+p[0],0):null};
  const popAll=Object.values(sp).reduce((s,p)=>s+p[0],0);
  // manje stanovnika nego upisanih: ime naselja u odluci pokriva i deo grada (npr. Љубић u Čačku), broj se ne prikazuje
  const nas=[...g].map(([k,rs])=>{const x=agg(rs),pp=popOf(k);return {name:k?T(k):"(naselje nije utvrđeno)",n:rs.length,up:x.up,pop:pp&&pp>=x.up?pp:null,
    turn:x.turn,win:x.va?x.win:-1,sh:x.va?x.v[x.win]/x.va:null}}).sort((p,q)=>q.up-p.up);
  const c=cmp23([i],a);
  // opis za pretragu: brojke na početku (Google prikaže ~155 znakova), pa 2023. i popis
  const bareT=T(o.full.replace(/^(Градска општина|Град|Општина) /,"")),Ls=k=>`${LISTS[a.rank[k]].short} ${P(a.v[a.rank[k]]/a.va)}`;
  const d0=a.va?`${bareT}, izbori 2026: ${Ls(0)}, ${Ls(1)}. Izlaznost ${P(a.turn)}${c?` (2023: ${P(c.t0)})`:""}.${popAll?` Popis 2022: ${N(popAll)} stanovnika.`:""} Poređenje sa 2023. i rezultati po selima.`:"";
  const desc=script==="cyr"?cyr(d0):d0;
  // kratko, za vrh stranice (ceo zbirni tekst je na dnu)
  const kratko=a.va?`${Ls(0)}, ${Ls(1)}. Izlaznost ${P(a.turn)}${c?` (2023: ${P(c.t0)})`:""}.`:"";
  // zbirni tekst: ista funkcija kao u interaktivnom prikazu (opSum u izbori2026.html)
  const bareC=o.full.replace(/^(Градска општина|Град|Општина) /,""),bare=lat(bareC); // „Чачак“ bez „Град“
  const sum=opSum(i);
  return {slug:opSlug(i),name:T(o.name),full:T(o.full),bare,bareC,okrug:T(OK[o.ok].name),status:statusLine(a),sum,sumC:cyr(sum),
    rows:listRows(a),nas:nas.map(e=>({...e,lst:e.win>=0?LISTS[e.win].short:"",c:e.win>=0?LISTS[e.win].c:"",
      shs:e.sh==null?"–":P(e.sh),ts:e.turn==null?"–":P(e.turn),ups:N(e.up),pops:e.pop?N(e.pop):"–"})),
    pop:popAll?N(popAll):"",desc,kratko,ab:ABROAD(i),c23:c?{t0:P(c.t0),t1:P(c.t1),v0:P(c.v0),v1:P(c.v1),nt0:N(c.n.t0),nt1:N(c.n.t1),nv0:N(c.n.v0),nv1:N(c.n.v1)}:null,
    top:a.va?a.rank.slice(0,4).map(k=>({n:cyr(LISTS[k].short),c:LISTS[k].c,p:a.v[k]/a.va,ps:P(a.v[k]/a.va)})):[],
    turn:a.turn==null?"–":P(a.turn),nd:a.nd,n:a.n,win:a.win>=0?LISTS[a.win].short:"",
    winp:a.win>=0&&a.va?P(a.v[a.win]/a.va):""};
}"""
# ćirilična verzija: telo stranice kroz preslovljavanje sa sajta (preskače .keep, script i style)
JS_CYR = r"""h => {const d=document.createElement('div');d.innerHTML=h;const s=script;script='cyr';locNode(d);script=s;return d.innerHTML}"""


# meni kao na glavnom sajtu: kartice vode na glavni sajt na istom pismu; Ћир/Lat prebacuju između dve verzije
# ove stranice (i pamte izbor kao na glavnom sajtu), EN otvara istu stranu na glavnom sajtu na engleskom
TABS = [("pregled", "Pregled"), ("mapa", "Mapa"), ("liste", "Liste"), ("okruzi", "Okruzi"), ("opstine", "Opštine"),
        ("mesta", "Biračka mesta"), ("statistika", "Statistika")]
MENU_CSS = """nav a{border-bottom:3px solid transparent;padding:14px 12px 11px;white-space:nowrap;color:var(--muted);font-weight:600;text-decoration:none}
nav a[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)} nav a:hover{color:var(--ink)}
.seg a{background:var(--surface);padding:5px 10px;color:var(--muted);font-weight:600;text-decoration:none}
.seg a[aria-pressed="true"]{background:var(--accent);color:var(--surface)} .brand{text-decoration:none;color:inherit}
@media (max-width:720px){nav a{padding:10px 12px 9px}}"""
SAVE = """onclick="try{localStorage.setItem('izbori2026.jezik','%s')}catch(e){}\""""


def head_js(s):
    # posetilac koji je izabrao drugo pismo (ovde ili na glavnom sajtu) odmah dobija svoju verziju
    other, to = ("lat", "lat/") if s == "cyr" else ("cyr", "../")
    return f'<script>try{{if(localStorage.getItem("izbori2026.jezik")==="{other}")location.replace("{to}"+location.hash)}}catch(e){{}}</script>'


def header(app_hash, s):
    nav = "".join(f'<a role="tab" data-jl href="/?jezik={s}#{k}"' + (' aria-selected="true"' if k == "opstine" else "") + f">{n}</a>" for k, n in TABS)
    cy = '<a aria-pressed="true" href="#">Ћир</a>' if s == "cyr" else f'<a href="../" {SAVE % "cyr"}>Ћир</a>'
    la = f'<a href="lat/" {SAVE % "lat"}>Lat</a>' if s == "cyr" else '<a aria-pressed="true" href="#">Lat</a>'
    lang = f'{cy}{la}<a href="/?jezik=en{app_hash}">EN</a>'
    # ako je pismo već sačuvano, linkovi na glavni sajt bez ?jezik= (ostaje izbor posetioca)
    return (f'<header class="top"><div class="top-in"><a class="brand" data-jl href="/?jezik={s}">Izbori 2026</a>'
            f'<nav id="tabs" aria-label="Pregledi">{nav}</nav><div class="seg keep" id="lang" role="group">{lang}</div></div></header>'
            '<script>try{if(localStorage.getItem("izbori2026.jezik"))document.querySelectorAll("a[data-jl]").forEach(a=>a.href=a.getAttribute("href").replace(/\\?jezik=(lat|cyr)/,""))}catch(e){}</script>')


def alt_links(path):
    # ista stranica na oba pisma (Google prikazuje onu na pismu pretrage)
    return (f'<link rel="alternate" hreflang="sr-Cyrl" href="{BASE}{path}"><link rel="alternate" hreflang="sr-Latn" href="{BASE}{path}lat/">'
            f'<link rel="alternate" hreflang="x-default" href="{BASE}{path}">')


def page(op, s, css, fonts, snap, map_svg, legend, okr_links):
    # op: podaci na pismu stranice; latinični tekst šablona u ćiriličnoj verziji preslovljava JS_CYR (u main)
    e = H.escape
    path = f"/opstina/{op['slug']}/"
    url = BASE + path + ("lat/" if s == "lat" else "")
    if s == "cyr":
        title = f"Резултати избора 2026: {op['bareC']} ({op['bare']}) – по бирачким местима и селима"
        desc = op["desc"] or \
            f"Парламентарни избори 2026, {op['full']} ({op['okrug']}): резултати по насељима и бирачким местима."
    else:
        title = f"Rezultati izbora 2026: {op['bare']} ({op['bareC']}) – po biračkim mestima i selima"
        desc = op["desc"] or \
            f"Parlamentarni izbori 2026, {op['full']} ({op['okrug']}): rezultati po naseljima i biračkim mestima."
    ab = op["ab"]  # inostranstvo: države umesto naselja, bez popisa
    unit = "Država" if ab else "Naselje"
    nas_rows = "".join(
        f'<tr><td class="ttl" data-l="{unit}"><b>{e(x["name"])}</b></td><td class="num" data-l="Biračkih mesta">{x["n"]}</td>'
        + ("" if ab else f'<td class="num" data-l="Stanovnika (2022)">{x["pops"]}</td>') +
        f'<td class="num" data-l="Upisano">{x["ups"]}</td><td class="num" data-l="Izlaznost">{x["ts"]}</td>'
        f'<td data-l="Prva lista">' + (f'<span class="sw" style="background:{x["c"]}"></span>{e(x["lst"])} {x["shs"]}' if x["lst"] else "–")
        + "</td></tr>" for x in op["nas"])
    c = op["c23"]
    cmp = (f'<div class="block"><h2>Poređenje sa izborima 2023.</h2><div class="tw"><table class="cards"><thead><tr><th></th>'
           f'<th class="num">2023.</th><th class="num">2026.</th></tr></thead><tbody>'
           f'<tr><td class="ttl" data-l=""><b>Izlaznost</b></td><td class="num" data-l="2023.">{c["t0"]} ({c["nt0"]})</td><td class="num" data-l="2026.">{c["t1"]} ({c["nt1"]})</td></tr>'
           f'<tr><td class="ttl" data-l=""><b>Lista Aleksandra Vučića</b></td><td class="num" data-l="2023.">{c["v0"]} ({c["nv0"]})</td><td class="num" data-l="2026.">{c["v1"]} ({c["nv1"]})</td></tr>'
           '</tbody></table></div><p class="note">U zagradi je broj glasalih, odnosno glasova za listu. Izvor za 2023: RIK, rezultati po biračkim mestima. '
           f'Više u delu <a data-jl href="/?jezik={s}#opstina/{op["slug"]}/p2023">Poređenje sa 2023.</a></p></div>') if c else ""
    pop = f" Po popisu 2022. ima {op['pop']} stanovnika." if op["pop"] else ""
    # strukturisani podaci za Google: skup podataka (izbori 2026, poređenje sa 2023, popis 2022)
    ld = json.dumps({"@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc, "url": url,
                     "inLanguage": "sr-Cyrl" if s == "cyr" else "sr-Latn",
                     "keywords": [f"izbori 2026 {op['bare']}", f"rezultati izbora {op['bare']}", "rezultati po selima", "biračka mesta",
                                  "izbori 2023", "popis stanovništva 2022"],
                     "temporalCoverage": "2023/2026", "spatialCoverage": {"@type": "Place", "name": f"{op['full']}, Srbija"},
                     "variableMeasured": ["izlaznost", "glasovi po izbornim listama", "izlaznost i rezultati 2023.", "broj stanovnika (popis 2022)"],
                     "isBasedOn": ["https://www.rik.parlament.gov.rs/542645/rezultati/", "https://www.stat.gov.rs/"],
                     "isPartOf": {"@type": "WebSite", "name": "izbori26.rs", "url": BASE + "/"},
                     "creator": {"@type": "Organization", "name": "izbori26.rs", "url": BASE + "/"}},
                    ensure_ascii=False).replace("<", "\\u003c")
    app_hash = f"#opstina/{op['slug']}"
    app = f"/?jezik={s}{app_hash}"
    home = "/opstina/" + ("lat/" if s == "lat" else "")
    body = f"""<body>
{header(app_hash, s)}
<main class="stp">
<h1>Rezultati izbora 2026: {e(op['full'])}</h1>
<p class="lead">{e(op['kratko']) or e(op['full'] + ', ' + op['okrug'] + '.')}</p>
<p class="note">{e(op['full'])}, {e(op['okrug'])}.{pop} {op['status']}</p>
<div class="cta"><a class="btn" data-jl href="{app}">Mapa sela, biračka mesta i poređenje sa 2023. →</a><a class="btn ghost" data-jl href="/?jezik={s}#pregled">Gde ja glasam?</a></div>
<div class="block"><h2>Rezultati svih listi</h2><p class="note">Udeo u važećim glasovima, na biračkim mestima sa unetim rezultatom.</p>
<div class="dlg" style="padding:0;max-height:none;overflow:visible">{op['rows']}</div></div>
{cmp}
{f'<div class="block"><h2>Mapa: gradovi u Evropi, ko je prvi</h2><div class="lgd maplgd">{legend}</div><div class="mapwrap">{map_svg}</div><p class="note">Krug je grad sa biračkim mestima, veličina prati broj glasalih. Granice: <span class="keep">Natural Earth</span>.</p></div>' if map_svg and ab else
  f'<div class="block"><h2>Mapa sela: ko je prvi</h2><div class="lgd maplgd">{legend}</div><div class="mapwrap">{map_svg}</div><p class="note">Bleđa boja znači tesniju pobedu. Granice: © <span class="keep">OpenStreetMap</span> saradnici (<span class="keep">ODbL</span>).</p></div>' if map_svg else ""}
{'<div class="block"><h2>Rezultati po državama</h2><p class="note">Biračka mesta sabrana po državi, poređano po broju upisanih birača.</p>' if ab else
 '<div class="block"><h2>Rezultati po naseljima i popis 2022.</h2><p class="note">Biračka mesta sabrana po naselju, poređano po broju upisanih birača. Broj stanovnika: popis 2022. (RZS).</p>'}
<div class="tw"><table class="cards"><thead><tr><th>{unit}</th><th class="num">Biračkih mesta</th>{'' if ab else '<th class="num">Stanovnika (2022)</th>'}<th class="num">Upisano</th><th class="num">Izlaznost</th><th>Prva lista</th></tr></thead><tbody>{nas_rows}</tbody></table></div></div>
{f'<div class="block"><h2>Ukratko</h2><p>{e(op["sum"])}</p></div>' if op['sum'] else ''}
<div class="cta"><a class="btn" data-jl href="{app}">Otvori {e(op['name'])} na sajtu →</a><a class="btn ghost" href="{home}">Sve opštine</a></div>
{okr_links}
<p class="note">Izvor: Republička izborna komisija, rezultati po biračkim mestima (unos do {e(snap)}). Privremeni, nezvanični prikaz. <a data-jl href="/?jezik={s}#metodologija">O sajtu i metodologija</a></p>
</main></body>"""
    return f"""<!doctype html>
<html lang="sr-{'Cyrl' if s == 'cyr' else 'Latn'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{head_js(s)}
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">{alt_links(path)}
<script type="application/ld+json">{ld}</script>
<meta property="og:type" content="article"><meta property="og:site_name" content="izbori26.rs"><meta property="og:locale" content="sr_RS">
<meta property="og:url" content="{url}"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{BASE}{path}og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#16294d"><link rel="icon" type="image/png" href="/ikona.png"><link rel="apple-touch-icon" href="/ikona.png">
{fonts}
<style>{css}
.stp{{max-width:1120px;margin:0 auto;padding:0 14px 30px}} .stp .cta{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}
.stp .mapsvg{{max-width:560px}} .stp .mapwrap{{justify-content:center}} .stp h1{{margin-top:18px}} .stp a.btn{{text-decoration:none}}
{MENU_CSS}
</style></head>
""", body + "</html>"


def okr_block(op, sib, s, anchor):
    sfx = "lat/" if s == "lat" else ""
    links = " · ".join(f'<a href="/opstina/{o["slug"]}/{sfx}">{H.escape(o["name"])}</a>' for o in sib)
    return (f'<div class="block"><h2>Ostale opštine: {H.escape(op["okrug"])}</h2><p>{links}</p>'
            f'<p class="note"><a href="/opstina/{sfx}#{anchor}">Sve opštine po okruzima</a></p></div>') if sib else ""


def index_page(groups, s, css, fonts):
    # groups: [(okrug na latinici, okrug na pismu stranice, [op na pismu stranice])]
    sfx = "lat/" if s == "lat" else ""
    lst = "".join(f'<div class="block" id="{slug(k)}"><h2>{H.escape(kn)}</h2><p>' + " · ".join(
        f'<a href="/opstina/{o["slug"]}/{sfx}">{H.escape(o["name"])}</a>' for o in v) + "</p></div>" for k, kn, v in groups)
    if s == "cyr":
        title, desc = ("Резултати избора 2026 по општинама – izbori26.rs",
                       "Резултати парламентарних избора 2026. за сваку општину у Србији: листе, излазност, поређење са 2023, попис 2022, мапа села и резултати по насељима.")
    else:
        title, desc = ("Rezultati izbora 2026 po opštinama – izbori26.rs",
                       "Rezultati parlamentarnih izbora 2026. za svaku opštinu u Srbiji: liste, izlaznost, poređenje sa 2023, popis 2022, mapa sela i rezultati po naseljima.")
    headp = f"""<!doctype html><html lang="sr-{'Cyrl' if s == 'cyr' else 'Latn'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{head_js(s)}<title>{title}</title><meta name="description" content="{desc}">
<link rel="canonical" href="{BASE}/opstina/{sfx}">{alt_links("/opstina/")}<meta property="og:image" content="{BASE}/og.png"><link rel="icon" type="image/png" href="/ikona.png">
{fonts}<style>{css}
.stp{{max-width:1120px;margin:0 auto;padding:0 14px 30px}} .stp p a{{white-space:nowrap}}
{MENU_CSS}</style></head>
"""
    body = f"""<body>{header("#opstine", s)}
<main class="stp"><h1>Rezultati izbora 2026 po opštinama</h1><p class="lead">Izaberi opštinu za rezultate svih listi, mapu sela i rezultate po naseljima.</p>{lst}</main></body>"""
    return headp, body + "</html>"


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
    ops = []  # (latinica, ćirilica)
    card_dir = SITE / "opstina"
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
            for i in range(n):
                pg.evaluate("script='lat'")
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
                pg.evaluate("script='cyr'")  # isti podaci, nazivi iz podataka na ćirilici
                opc = pg.evaluate(JS_OP, i)
                d = card_dir / op["slug"]
                d.mkdir(parents=True, exist_ok=True)
                op["_map"], op["_lgd"] = map_svg, legend
                # slika za pregled linka (ćirilica, kao podrazumevana stranica): naziv, prve liste i mapa sela
                pg.evaluate("""([op,svg])=>{let c=document.getElementById('ogcard');if(c)c.remove();c=document.createElement('div');c.id='ogcard';
                  c.style.cssText='position:fixed;left:0;top:0;width:1200px;height:630px;background:#fff;color:#101826;z-index:9999;display:flex;font-family:"Source Sans 3",Arial,sans-serif;box-sizing:border-box;padding:48px 52px;gap:36px';
                  const bars=op.top.map(t=>`<div style="margin:14px 0"><div style="display:flex;justify-content:space-between;font-size:30px"><span>${t.n}</span><b>${t.ps}</b></div><div style="height:16px;background:#e3e7ee;border-radius:3px;margin-top:6px"><div style="width:${Math.max(1,t.p*100)}%;height:100%;background:${t.c};border-radius:3px"></div></div></div>`).join('');
                  c.innerHTML=`<div style="flex:1 1 55%;display:flex;flex-direction:column"><div style="font:700 26px Literata,Georgia,serif;color:#16294d">Избори 2026 · резултати</div>
                    <div style="font:700 64px/1.05 Literata,Georgia,serif;margin:14px 0 4px">${op.name}</div><div style="font-size:26px;color:#566175">${op.okrug} · излазност ${op.turn}</div>
                    <div style="margin-top:22px">${bars}</div><div class="keep" style="margin-top:auto;font-size:26px;color:#16294d;font-weight:700">izbori26.rs</div></div>
                    <div style="flex:1 1 45%;display:flex;align-items:center;justify-content:center">${svg}</div>`;
                  const s=c.querySelector('svg');if(s){s.style.maxWidth='100%';s.style.maxHeight='530px';s.style.width='100%';s.style.height='auto'}
                  document.body.appendChild(c)}""", [opc, map_svg])
                pg.locator("#ogcard").screenshot(path=str(d / "og.png"))
                pg.evaluate("document.getElementById('ogcard').remove()")
                ops.append((op, opc))

            # stranice; na dnu linkovi na ostale opštine iz istog okruga (lakše obilaženje za Google i posetioce)
            by = {}
            for pair in ops:
                by.setdefault(pair[0]["okrug"], []).append(pair)
            for v in by.values():
                v.sort(key=lambda x: x[0]["name"])
            for opl, opc in ops:
                sib = [x for x in by[opl["okrug"]] if x[0] is not opl]
                d = card_dir / opl["slug"]
                for s, o, sb in (("lat", opl, [x[0] for x in sib]), ("cyr", opc, [x[1] for x in sib])):
                    hd, body = page(o, s, css, fonts, snap, opl["_map"], opl["_lgd"], okr_block(o, sb, s, slug(opl["okrug"])))
                    if s == "cyr":
                        body = "<body>" + pg.evaluate(JS_CYR, body[6:-len("</body></html>")]) + "</body></html>"
                    out = d / "lat" if s == "lat" else d
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "index.html").write_text(hd + body, encoding="utf-8")

            # spisak svih opština, po okruzima (sidro #<okrug> za linkove sa stranica opština)
            for s, j in (("lat", 0), ("cyr", 1)):
                groups = [(k, v[0][j]["okrug"], [x[j] for x in v]) for k, v in by.items()]
                hd, body = index_page(groups, s, css, fonts)
                if s == "cyr":
                    body = "<body>" + pg.evaluate(JS_CYR, body[6:-len("</body></html>")]) + "</body></html>"
                out = card_dir / "lat" if s == "lat" else card_dir
                out.mkdir(parents=True, exist_ok=True)
                (out / "index.html").write_text(hd + body, encoding="utf-8")
            b.close()
    finally:
        srv.shutdown()

    today = date.today().isoformat()
    paths = ["/opstina/"] + [f"/opstina/{o['slug']}/" for o, _ in ops]
    urls = [f"{BASE}/"] + [BASE + x + sfx for x in paths for sfx in ("", "lat/")]
    (SITE / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    print(f"Stranice opština: {len(ops)} (ćirilica i latinica), sitemap {len(urls)} adresa")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # objava ide dalje i bez ovih stranica
        print("Stranice opština nisu napravljene:", e, file=sys.stderr)
