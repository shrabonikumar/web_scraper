# Polite Web Scraper

A Flask web app with an HTML front end that **checks a website's robots.txt before scraping**. It reports whether scraping is allowed and, if so, **what percentage of the site** may be scraped. Only then does it extract tables, text and images from a page you choose.

## Features

- **Permission check first.** Reads `robots.txt` and gives a verdict: allowed, partly allowed, or not allowed.
- **Percentage allowed.** Samples pages from the site's `sitemap.xml`, tests each against the robots.txt rules, and reports `allowed ÷ sampled × 100`.
- **Visual result.** One square per sampled page (green = allowed, red = blocked). Hover a square to see its URL.
- **User-chosen sample size.** 25, 50, 100, 200 or 500 pages.
- **Sitemap fallback.** If there is no sitemap, it samples same-site links from the homepage and shows a warning that the percentage is less accurate.
- **Extraction options** (any combination):
  - Tables and structured data (HTML `<table>` elements and JSON-LD blocks)
  - All page text
  - All images (URL, alt text, thumbnail preview)
- **Downloads.** CSV per table, TXT for text, CSV for the image list, and one JSON file with everything.
- **Respectful behaviour.** Honors `Crawl-delay`, identifies itself with a User-Agent, and enforces robots.txt on the server.

## Project structure

```
webscraper/
├── app.py              # Flask backend (robots check, sitemap sampling, scraping)
├── requirements.txt    # Python dependencies
├── static/
│   └── index.html      # HTML/CSS/JS front end
└── README.md
```

## Setup

Requires Python 3.9 or newer.

```bash
cd webscraper
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## How to use

1. **Check permission.** Enter a website URL (for example `https://example.com`), choose how many pages to test, and click **Check robots.txt**.
2. Read the result: verdict, percentage, the square map, crawl delay, and examples of blocked pages.
3. **Scrape the page.** The URL you entered appears in the second box (you can change it to any page on the same site). Tick what to extract and click **Scrape page**.
4. Use the download buttons to save the results.

The scrape section is hidden when the site is fully blocked and your URL is blocked too. Even if you reach it, the server refuses any URL that robots.txt disallows.

## How the percentage is calculated

1. Fetch `https://<site>/robots.txt` and parse it with [Protego](https://github.com/scrapy/protego), which follows RFC 9309 (including `*` and `$` wildcards).
2. Collect page URLs from the sitemaps declared in robots.txt, or `/sitemap.xml` if none are declared. Sitemap index files are followed (up to 15 sitemap files, 5,000 URLs).
3. Keep only URLs on the same host, then randomly pick the chosen sample size.
4. Test every sampled URL with `can_fetch`.
5. `percent = allowed URLs ÷ sampled URLs × 100`.

Verdict:

| Result | Meaning |
|---|---|
| Allowed | 100% of sampled pages can be fetched |
| Partly allowed | Between 0% and 100% |
| Not allowed | 0% |

Handling of robots.txt responses (per RFC 9309):

| robots.txt response | Treated as |
|---|---|
| 200 | Rules are parsed and applied |
| 404 or other 4xx (except 401/403) | No restrictions, everything allowed |
| 401, 403, 5xx, or unreachable | Everything blocked |

## API

| Endpoint | Body (JSON) | Returns |
|---|---|---|
| `POST /api/check` | `url`, `sample` (5–500) | verdict, percent, counts, crawl delay, warning, per-URL results |
| `POST /api/scrape` | `url`, `extract` (`["tables","text","images"]`) | tables, structured data, text, images |

Errors return `{"error": "..."}` with status 400 (bad input), 403 (blocked by robots.txt) or 502 (page could not be fetched).

## Safeguards

- robots.txt is re-checked on the server before every scrape, so it cannot be bypassed from the UI.
- Images are checked against the robots.txt of the host they live on (CDNs included, up to 6 hosts per page). Blocked images are not previewed.
- Private, loopback and internal IP addresses are rejected.
- Sitemap XML is parsed with `defusedxml`.
- Crawl delay is honored (capped at 10 seconds).

## Limits

| Item | Limit |
|---|---|
| Tables per page | 20 (500 rows each) |
| Images per page | 200 |
| Text length | 200,000 characters |
| Request timeout | 8–10 seconds |

## Known limitations

- Only raw HTML is fetched, so content built by JavaScript (for example tables loaded after the page opens) is not seen.
- The percentage is an estimate from a random sample, so it can vary slightly between runs, especially with small samples.
- The tool lists and previews images but does not download the image files.
- Redirects are followed without re-checking the destination address. Run this locally only and do not expose it publicly.
- robots.txt is not the whole story. A site's terms of service may still restrict scraping.

## Configuration

Change the `UA` constant at the top of `app.py` to set your own User-Agent. Some sites (Wikimedia, for example) expect contact details in it:

```python
UA = "AssignmentScraper/1.0 (your.email@example.com)"
```

## Suggested test sites

| Site | What it shows |
|---|---|
| `https://www.scrapethissite.com/pages/forms/` | Full flow with a real HTML table |
| `https://en.wikipedia.org/wiki/List_of_countries_by_population_(United_Nations)` | Partial percentage, many tables, images on a CDN |
| `https://books.toscrape.com` | No sitemap, so the fallback warning appears |
| `https://www.amazon.com` | Restrictive rules or a blocked result |

Check each site's `/robots.txt` in your browser first, since these files change over time.

## Built with

Python, Flask, Requests, Beautiful Soup, Protego, defusedxml, and plain HTML/CSS/JavaScript.