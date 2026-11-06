#!/usr/bin/env python3
"""Radar TECH history - coleta diaria de noticias de tecnologia/ciencia.

- Descobre noticias via RSS de 7 sites (custo zero, nao gasta credito do Firecrawl).
- Cruza com Google Trends (BR) e com a cobertura entre sites para achar o que esta em alta.
- Usa o Firecrawl SO para pegar texto completo + fotos/videos das melhores noticias,
  respeitando um orcamento diario (limite mensal dividido pelos dias restantes do mes).
- Se nao houver chave/credito, cai para extracao simples (sem custo).
Sem dependencias externas: so biblioteca padrao do Python 3.9+.
"""
import calendar
import html
import json
import math
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "data"
STATE = ROOT / "data"
OUT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (compatible; TechHistoryRadar/1.0)"
FC_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    TZ = timezone(timedelta(hours=-3))

STOP = set(
    """de da do das dos para por com sem sobre como mais menos que uma uns umas num numa pelo pela
    pelos pelas ao aos entre ate apos este esta isso esse essa estes estas seu sua seus suas ser foi
    sao tem ter vai vem novo nova novos novas the and for with from that this are was were will has
    have into over after about your you its new how what why who says say can could would not but more
    than just they their them out all one two ele ela eles elas quando onde qual quais ja nao sim mas
    tambem ainda apenas pode podem veja saiba confira""".split()
)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(s):
    return {t for t in re.findall(r"[a-z0-9]{2,}", norm(s)) if t not in STOP}


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_tags(s):
    s = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def local(tag):
    return tag.split("}")[-1]


# ----------------------------------------------------------------------------- RSS
def parse_feed(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        d = {"title": "", "link": "", "summary": "", "content": "", "date": None, "image": ""}
        for ch in el:
            t = local(ch.tag)
            txt = (ch.text or "").strip()
            if t in ("enclosure", "content", "thumbnail") and ch.attrib.get("url"):
                typ = ch.attrib.get("type", "")
                if (not typ or typ.startswith("image")) and not d["image"]:
                    d["image"] = ch.attrib["url"]
            elif t == "title":
                d["title"] = strip_tags(txt)
            elif t == "link":
                d["link"] = ch.attrib.get("href") or txt or d["link"]
            elif t in ("description", "summary"):
                d["summary"] = strip_tags(txt)
                m = re.search(r'<img[^>]+src=["\']([^"\']+)', txt)
                if m and not d["image"]:
                    d["image"] = m.group(1)
            elif t in ("encoded", "content"):
                d["content"] = txt
                m = re.search(r'<img[^>]+src=["\']([^"\']+)', txt)
                if m and not d["image"]:
                    d["image"] = m.group(1)
            elif t in ("pubDate", "published", "updated", "date"):
                d["date"] = d["date"] or parse_date(txt)
        if d["title"] and d["link"]:
            d["source"] = source
            items.append(d)
    return items


def discover_feed(site):
    """Recebe o link de um site e tenta achar o feed RSS dele."""
    raw = ""
    try:
        raw = http_get(site, 15).decode("utf-8", "ignore")
    except Exception as e:
        log(f"[discover] {site}: {e}")
    for m in re.finditer(r"<link[^>]+>", raw, re.I):
        tag = m.group(0)
        if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            h = re.search(r'href=["\']([^"\']+)', tag)
            if h and "comment" not in h.group(1).lower():
                return urllib.parse.urljoin(site, html.unescape(h.group(1)))
    base = site.rstrip("/")
    for p in ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml"):
        try:
            head = http_get(base + p, 10)[:300].lower()
        except Exception:
            continue
        if b"<rss" in head or b"<feed" in head or b"<?xml" in head:
            return base + p
    return ""


def fetch_sources():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CFG["max_age_hours"])
    allitems, status = [], []
    for s in CFG["sources"]:
        feed = s.get("feed") or discover_feed(s.get("site", ""))
        if not feed:
            log(f"[feed] {s['name']}: nao achei o feed RSS")
            status.append({"name": s["name"], "feed": "", "count": 0, "ok": False})
            continue
        try:
            items = parse_feed(http_get(feed), s["name"])
        except Exception as e:
            log(f"[feed] {s['name']} falhou: {e}")
            status.append({"name": s["name"], "feed": feed, "count": 0, "ok": False})
            continue
        items = [i for i in items if (i["date"] or datetime.now(timezone.utc)) >= cutoff]
        items = items[: CFG["per_source_limit"]]
        log(f"[feed] {s['name']}: {len(items)} itens")
        status.append({"name": s["name"], "feed": feed, "count": len(items), "ok": True})
        allitems += items
    return allitems, status


# ----------------------------------------------------------------------------- Trends
def parse_traffic(s):
    s = norm(s or "").replace("+", "").replace(".", "").replace(",", "").strip()
    m = re.match(r"(\d+)\s*(k|mil|m|mi)?", s)
    if not m:
        return 0
    n = int(m.group(1))
    return n * {"k": 1_000, "mil": 1_000, "m": 1_000_000, "mi": 1_000_000}.get(m.group(2), 1)


def fetch_trends():
    geo = CFG.get("trends_geo", "BR")
    try:
        root = ET.fromstring(http_get(f"https://trends.google.com/trending/rss?geo={geo}"))
    except Exception as e:
        log(f"[trends] falhou: {e}")
        return []
    out = []
    for it in root.iter():
        if local(it.tag) != "item":
            continue
        term, traffic = "", 0
        for ch in it:
            if local(ch.tag) == "title":
                term = (ch.text or "").strip()
            elif local(ch.tag) == "approx_traffic":
                traffic = parse_traffic(ch.text)
        if term:
            out.append({"term": term, "traffic": traffic, "tok": sorted(tokens(term))})
    log(f"[trends] {len(out)} termos")
    return out


# ----------------------------------------------------------------------------- Ranking
def similar(a, b):
    inter = len(a & b)
    return inter >= 2 and inter / max(1, min(len(a), len(b))) >= 0.4


def cluster(items):
    for i in items:
        i["tok"] = tokens(i["title"])
    clusters = []
    for it in items:
        for c in clusters:
            if any(similar(it["tok"], m["tok"]) for m in c):
                c.append(it)
                break
        else:
            clusters.append([it])
    return clusters


def rank(clusters, trends):
    order = {s["name"]: n for n, s in enumerate(CFG["sources"])}
    boosts = [norm(k) for k in CFG["boost_keywords"]]
    now = datetime.now(timezone.utc)
    stories = []
    for c in clusters:
        rep = sorted(c, key=lambda m: (not m["content"], not m["image"], order.get(m["source"], 99)))[0]
        srcs = sorted({m["source"] for m in c})
        age = (now - (rep["date"] or now)).total_seconds() / 3600
        text_tok = rep["tok"] | tokens(rep["summary"])
        score, why = 0.0, []
        if len(srcs) > 1:
            score += 3 * (len(srcs) - 1)
            why.append(f"{len(srcs)} sites cobrindo")
        hit = None
        for t in trends:
            if t["tok"] and set(t["tok"]) <= text_tok:
                hit = t
                break
        if hit:
            score += 5 + min(3, math.log10(hit["traffic"] + 1) / 2)
            why.append(f"Em alta no Google: {hit['term']}")
        score += 3 * max(0, 1 - age / CFG["max_age_hours"])
        blob = " " + norm(rep["title"] + " " + rep["summary"]) + " "
        n_boost = sum(1 for k in boosts if re.search(rf"\b{re.escape(k)}\b", blob))
        if n_boost:
            score += min(2, 0.7 * n_boost)
            why.append("Tema de alto interesse")
        stories.append({
            "id": re.sub(r"\W+", "", norm(rep["link"]))[-40:],
            "title": rep["title"], "source": rep["source"], "url": rep["link"],
            "published": rep["date"].isoformat() if rep["date"] else "",
            "summary": rep["summary"][:400], "score": round(score, 2), "why": why,
            "also_in": [{"source": m["source"], "url": m["link"]} for m in c if m is not rep],
            "image": rep["image"], "_rss_content": rep["content"],
        })
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories


# ----------------------------------------------------------------------------- Texto e midia
BAD_IMG = re.compile(r"(logo|avatar|icon|sprite|pixel|badge|banner-ads?|gravatar|\.svg|\.gif|1x1|placeholder)", re.I)
YT = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([\w-]{11})")


def clean_md(md):
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md[: CFG["text_char_limit"]]


def media_from(text, base, extra_img=""):
    imgs = []
    cand = ([extra_img] if extra_img else []) + re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)", text) \
        + re.findall(r'<img[^>]+src=["\']([^"\']+)', text)
    for u in cand:
        u = urllib.parse.urljoin(base, u)
        if u.startswith("http") and not BAD_IMG.search(u) and u not in imgs:
            imgs.append(u)
    vids = []
    for vid in YT.findall(text):
        u = f"https://www.youtube.com/watch?v={vid}"
        if u not in vids:
            vids.append(u)
    for u in re.findall(r"https?://[^\s\"'<>)]+\.mp4", text):
        if u not in vids:
            vids.append(u)
    return imgs[:12], vids[:6]


class OutOfCredits(Exception):
    pass


def firecrawl_scrape(url):
    body = json.dumps({"url": url, "formats": ["markdown"], "onlyMainContent": True, "timeout": 30000}).encode()
    for ver in ("v2", "v1"):
        req = urllib.request.Request(
            f"https://api.firecrawl.dev/{ver}/scrape", data=body,
            headers={"Authorization": f"Bearer {FC_KEY}", "Content-Type": "application/json", "User-Agent": UA},
        )
        try:
            with urllib.request.urlopen(req, timeout=70) as r:
                j = json.loads(r.read())
            return j.get("data") if j.get("success") else None
        except urllib.error.HTTPError as e:
            if e.code in (404, 410) and ver == "v2":
                continue
            if e.code in (402, 429):
                raise OutOfCredits(str(e.code))
            log(f"[firecrawl] HTTP {e.code} em {url}")
            return None
        except Exception as e:
            log(f"[firecrawl] erro em {url}: {e}")
            return None
    return None


def basic_extract(url):
    raw = http_get(url, 20).decode("utf-8", "ignore")
    tm = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', raw) \
        or re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = strip_tags(tm.group(1)) if tm else ""
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', raw)
    art = re.search(r"(?is)<article.*?</article>", raw)
    scope = art.group(0) if art else raw
    paras = [strip_tags(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", scope)]
    text = "\n\n".join(p for p in paras if len(p) > 50)
    imgs, vids = media_from(raw, url, og.group(1) if og else "")
    return text[: CFG["text_char_limit"]], imgs, vids, title


def enrich(stories, usage, cache):
    left_today = usage["daily_allowance"] - usage["used_today"]
    fc_on = bool(FC_KEY)
    for n, s in enumerate(stories):
        s["text"], s["text_source"], s["images"], s["videos"] = "", "none", [], []
        c = cache.get(s["url"])
        if c and c.get("text"):
            s.update({k: c[k] for k in ("text", "text_source", "images", "videos")})
            continue
        done = False
        if fc_on and n < CFG["fulltext_n"] and left_today > 0:
            try:
                d = firecrawl_scrape(s["url"])
            except OutOfCredits as e:
                log(f"[firecrawl] sem creditos ({e}); usando modo gratis")
                fc_on = False
                d = None
            if d and d.get("markdown"):
                usage["used"] += 1
                usage["used_today"] += 1
                left_today -= 1
                md = d["markdown"]
                og = (d.get("metadata") or {}).get("ogImage", "") or s["image"]
                s["images"], s["videos"] = media_from(md, s["url"], og)
                s["text"], s["text_source"] = clean_md(md), "firecrawl"
                done = True
        if not done:
            rss_txt = strip_tags(re.sub(r"</p>", "\n\n", s["_rss_content"]))
            if len(rss_txt) > 600:
                s["text"], s["text_source"] = rss_txt[: CFG["text_char_limit"]], "rss"
                s["images"], s["videos"] = media_from(s["_rss_content"], s["url"], s["image"])
            else:
                try:
                    t, imgs, vids, _ = basic_extract(s["url"])
                    s["text"], s["text_source"], s["images"], s["videos"] = t, ("basic" if t else "none"), imgs, vids
                except Exception as e:
                    log(f"[basic] falhou {s['url']}: {e}")
        if s["image"] and s["image"] not in s["images"]:
            s["images"].insert(0, s["image"])
        cache[s["url"]] = {
            "text": s["text"], "text_source": s["text_source"], "images": s["images"], "videos": s["videos"],
            "seen": datetime.now(timezone.utc).isoformat(),
        }
        s.pop("_rss_content", None)
    for s in stories:
        s.pop("_rss_content", None)


# ----------------------------------------------------------------------------- Links avulsos
def process_manual(usage, cache):
    """Noticias que o usuario colou como link (data/links.json). Tem prioridade no credito."""
    links = load(STATE / "links.json", [])
    out = []
    fc_on = bool(FC_KEY)
    for L in links:
        url = (L.get("url", "") if isinstance(L, dict) else str(L)).strip()
        if not url.startswith("http"):
            continue
        c = cache.get(url) or {}
        text, tsrc = c.get("text", ""), c.get("text_source", "none")
        imgs, vids, title = c.get("images", []), c.get("videos", []), c.get("title", "")
        if not (text and title):
            done = False
            if fc_on and usage["daily_allowance"] - usage["used_today"] > 0:
                try:
                    d = firecrawl_scrape(url)
                except OutOfCredits:
                    fc_on, d = False, None
                if d and d.get("markdown"):
                    usage["used"] += 1
                    usage["used_today"] += 1
                    md, meta = d["markdown"], d.get("metadata") or {}
                    imgs, vids = media_from(md, url, meta.get("ogImage", ""))
                    text, tsrc, title = clean_md(md), "firecrawl", (meta.get("title", "") or title)
                    done = True
            if not done:
                try:
                    text, imgs, vids, ptitle = basic_extract(url)
                    tsrc, title = ("basic" if text else "none"), (title or ptitle)
                except Exception as e:
                    log(f"[manual] falhou {url}: {e}")
            cache[url] = {"text": text, "text_source": tsrc, "images": imgs, "videos": vids,
                          "title": title, "seen": datetime.now(timezone.utc).isoformat()}
        host = urllib.parse.urlparse(url).netloc.replace("www.", "")
        title = title or host
        kw = keywords_of(title)
        out.append({
            "id": re.sub(r"\W+", "", norm(url))[-40:], "title": title, "source": host, "url": url,
            "published": (L.get("added", "") if isinstance(L, dict) else ""), "summary": (text or "")[:400],
            "score": 0, "why": ["Link adicionado por você"], "also_in": [], "image": imgs[0] if imgs else "",
            "text": text, "text_source": tsrc, "images": imgs, "videos": vids,
            "keywords": kw, "searches": suggest(" ".join(kw)), "manual": True,
        })
        log(f"[manual] {host}: {tsrc}")
    return out


# ----------------------------------------------------------------------------- Buscas (autocomplete)
def keywords_of(title):
    words = re.findall(r"[A-Za-zÀ-ÿ0-9][\w\-À-ÿ]*", title)
    caps = [w for w in words[1:] if w[0].isupper() or w.isdigit()]
    base = caps[:3] or [w for w in words if norm(w) not in STOP][:3]
    return base


def suggest(q):
    url = "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=pt-BR&q=" + urllib.parse.quote(q)
    try:
        data = json.loads(http_get(url, 10).decode("utf-8", "ignore"))
        return [x for x in data[1] if isinstance(x, str)][:6]
    except Exception as e:
        log(f"[suggest] falhou ({q}): {e}")
        return []


# ----------------------------------------------------------------------------- main
def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    now = datetime.now(TZ)
    month, today = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    usage = load(STATE / "usage.json", {})
    if usage.get("month") != month:
        usage = {"month": month, "used": 0, "day": today, "used_today": 0}
    if usage.get("day") != today:
        usage["day"], usage["used_today"] = today, 0
    limit = CFG["monthly_credit_limit"]
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day + 1
    start_of_day_left = limit - (usage["used"] - usage["used_today"])
    usage["daily_allowance"] = max(0, start_of_day_left // days_left)
    usage["month_limit"] = limit
    log(f"[budget] limite diario hoje: {usage['daily_allowance']} (restam {start_of_day_left} no mes, {days_left} dias)")

    cache = load(STATE / "cache.json", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    cache = {u: v for u, v in cache.items() if v.get("seen", "") >= cutoff}

    items, src_status = fetch_sources()
    if not items:
        log("Nenhuma noticia coletada; mantendo arquivo anterior.")
        return 1
    trends = fetch_trends()
    stories = rank(cluster(items), trends)[: CFG["top_n"]]
    manual = process_manual(usage, cache)
    enrich(stories, usage, cache)

    for n, s in enumerate(stories):
        s["keywords"] = keywords_of(s["title"])
        s["searches"] = suggest(" ".join(s["keywords"])) if n < CFG["suggest_n"] else []

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trends": [{"term": t["term"], "traffic": t["traffic"]} for t in trends[:15]],
        "usage": {k: usage[k] for k in ("month_limit", "used", "used_today", "daily_allowance")},
        "sources": src_status,
        "manual": manual,
        "stories": stories,
    }
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (STATE / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    (STATE / "cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log(f"[ok] {len(stories)} historias | creditos usados hoje {usage['used_today']} / mes {usage['used']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
