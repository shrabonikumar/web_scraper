"""Polite web scraper: checks robots.txt first, reports what % of a site may be
scraped, then extracts tables and structured data from an allowed page."""
import gzip
import ipaddress
import json
import random
import socket
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from flask import Flask, jsonify, request, send_from_directory
from protego import Protego

UA = "AssignmentScraper/1.0 (student project)"
app = Flask(__name__, static_folder="static", static_url_path="/static")
http = requests.Session()
http.headers["User-Agent"] = UA


def normalise(url):
    """Return (full_url, origin). Rejects non-http(s) and private/internal hosts."""
    url = (url or "").strip()
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Enter a valid http or https URL.")
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Private or internal addresses are not allowed.")
    except socket.gaierror:
        raise ValueError("Could not resolve that host name.")
    return url, f"{p.scheme}://{p.netloc}"


def load_robots(origin):
    """Fetch and parse robots.txt following RFC 9309 status handling."""
    try:
        r = http.get(origin + "/robots.txt", timeout=8)
    except requests.RequestException:
        return Protego.parse("User-agent: *\nDisallow: /"), "unreachable"
    if r.status_code in (401, 403) or r.status_code >= 500:
        return Protego.parse("User-agent: *\nDisallow: /"), f"error {r.status_code}"
    if r.status_code >= 400:  # no robots.txt: everything is allowed
        return Protego.parse(""), "not found"
    return Protego.parse(r.text), "found"


def sitemap_urls(start, cap=5000):
    """Collect page URLs from sitemaps, following sitemap indexes (max 15 files)."""
    urls, queue, seen = [], list(start), set()
    while queue and len(urls) < cap and len(seen) < 15:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = http.get(sm, timeout=10)
            r.raise_for_status()
            data = gzip.decompress(r.content) if r.content[:2] == b"\x1f\x8b" else r.content
            root = ET.fromstring(data)
        except Exception:
            continue
        locs = [e.text.strip() for e in root.iter()
                if (e.tag == "loc" or e.tag.endswith("}loc")) and e.text]
        if root.tag.endswith("sitemapindex"):
            queue += locs
        else:
            urls += locs
    return urls[:cap]


def homepage_links(origin, rp):
    """Fallback when there is no sitemap: same-site links found on the homepage."""
    home = origin + "/"
    if not rp.can_fetch(home, UA):
        return [home]
    try:
        r = http.get(home, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
    except requests.RequestException:
        return [home]
    host, found = urlparse(origin).netloc, {home}
    for a in soup.find_all("a", href=True):
        u = urljoin(r.url, a["href"]).split("#")[0]
        q = urlparse(u)
        if q.scheme in ("http", "https") and q.netloc == host:
            found.add(u)
    return list(found)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/check")
def check():
    d = request.get_json(force=True, silent=True) or {}
    try:
        url, origin = normalise(d.get("url"))
        n = max(5, min(int(d.get("sample", 100)), 500))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400

    rp, status = load_robots(origin)
    host = urlparse(origin).netloc
    declared = list(rp.sitemaps) or [origin + "/sitemap.xml"]
    urls = [u for u in sitemap_urls(declared) if urlparse(u).netloc == host]
    source, warning = "sitemap", None
    if not urls:
        source = "homepage links"
        urls = homepage_links(origin, rp)
        warning = ("No sitemap.xml found, so the sample comes from homepage links only. "
                   "The percentage is less accurate.")

    sample = random.sample(urls, min(n, len(urls)))
    results = [[u, rp.can_fetch(u, UA)] for u in sample]
    allowed = sum(ok for _, ok in results)
    pct = round(100 * allowed / len(results), 1) if results else 0
    verdict = "blocked" if allowed == 0 else "full" if allowed == len(results) else "partial"
    return jsonify(
        origin=origin, robots_url=origin + "/robots.txt", robots_status=status,
        crawl_delay=rp.crawl_delay(UA), source=source, warning=warning,
        urls_found=len(urls), sampled=len(results), allowed=allowed, percent=pct,
        verdict=verdict, target_allowed=rp.can_fetch(url, UA), target=url,
        results=results,
    )


@app.post("/api/scrape")
def scrape():
    d = request.get_json(force=True, silent=True) or {}
    try:
        url, origin = normalise(d.get("url"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    rp, _ = load_robots(origin)  # enforced server-side, not just in the UI
    if not rp.can_fetch(url, UA):
        return jsonify(error="robots.txt does not allow scraping this URL."), 403
    delay = rp.crawl_delay(UA)
    if delay:
        time.sleep(min(delay, 10))
    try:
        r = http.get(url, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        return jsonify(error=f"Could not fetch the page: {e}"), 502

    want = {x for x in (d.get("extract") or ["tables"]) if x in ("tables", "text", "images")} or {"tables"}
    soup = BeautifulSoup(r.text, "html.parser")
    tables = []
    for t in (soup.find_all("table")[:20] if "tables" in want else []):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                for tr in t.find_all("tr") if tr.find_parent("table") is t]
        rows = [x for x in rows if x][:500]
        if not rows:
            continue
        first = t.find("tr")
        if first is not None and first.find("th"):
            headers, rows = rows[0], rows[1:]
        else:
            headers = [f"Column {i + 1}" for i in range(max(len(x) for x in rows))]
        cap = t.find("caption")
        tables.append({"caption": cap.get_text(" ", strip=True) if cap else "",
                       "headers": headers, "rows": rows})

    structured = []
    for s in (soup.find_all("script", type="application/ld+json") if "tables" in want else []):
        try:
            structured.append(json.loads(s.string or ""))
        except ValueError:
            pass

    images = []
    if "images" in want:
        robots_cache, seen = {origin: rp}, set()  # images may live on other hosts (CDNs)

        def image_allowed(u):
            q = urlparse(u)
            o = f"{q.scheme}://{q.netloc}"
            if o not in robots_cache:
                if len(robots_cache) >= 6:
                    return False
                try:
                    normalise(o)
                    robots_cache[o] = load_robots(o)[0]
                except ValueError:
                    return False
            return robots_cache[o].can_fetch(u, UA)

        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src or src.startswith("data:"):
                continue
            u = urljoin(r.url, src)
            if urlparse(u).scheme not in ("http", "https") or u in seen:
                continue
            seen.add(u)
            images.append({"url": u, "alt": img.get("alt", ""), "allowed": image_allowed(u)})
            if len(images) >= 200:
                break

    text = ""
    if "text" in want:
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        lines = (ln.strip() for ln in soup.get_text("\n").splitlines())
        text = "\n".join(ln for ln in lines if ln)[:200000]

    return jsonify(url=url, extract=sorted(want), tables=tables,
                   structured_data=structured, images=images, text=text)


if __name__ == "__main__":
    app.run(debug=True)