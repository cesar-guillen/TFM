#!/usr/bin/env python3
"""Turn thedfirreport.com articles into clean PDFs for pipeline testing.

Browser "print to PDF" mangles these articles (navigation furniture, cookie
banners, images sliced across pages, headings flattened). This pulls the post
HTML straight from the site's WordPress REST API instead — so the structure the
author wrote is preserved exactly — and renders it with WeasyPrint under a print
stylesheet whose heading sizes are clearly separated, which is what lets
pymupdf4llm's legacy engine recover real heading levels downstream.

  python3 data/fetch_dfir_report.py --list --latest 20
  python3 data/fetch_dfir_report.py --latest 5
  python3 data/fetch_dfir_report.py --url https://thedfirreport.com/2026/08/24/bengalseo-part-1-anatomy-of-the-operation/
  python3 data/fetch_dfir_report.py --search akira --no-images

Needs: pip install weasyprint (plus requests/beautifulsoup4, already present).
Writes into data/dfir_reports/ (gitignored), kept separate from data/uploads/
so fetched articles never mix with the app's own uploads or the eval corpus.
"""

import argparse
import html
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from weasyprint import HTML, default_url_fetcher

API = "https://thedfirreport.com/wp-json/wp/v2/posts"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Heading sizes are deliberately far apart: the PDF->Markdown step infers
# heading level from font size, so a tight ramp collapses the hierarchy.
CSS = """
@page {
  size: A4; margin: 20mm 17mm 18mm 17mm;
  @bottom-center { content: counter(page); font: 8pt "DejaVu Sans"; color: #888; }
}
body { font: 10.5pt/1.5 "DejaVu Serif", Georgia, serif; color: #16191d; }
h1 { font: bold 26pt "DejaVu Sans", sans-serif; line-height: 1.2;
     margin: 0 0 4pt; color: #0f1216; }
h2 { font: bold 17pt "DejaVu Sans", sans-serif; margin: 22pt 0 7pt;
     padding-bottom: 3pt; border-bottom: 1.2pt solid #c9ced6; color: #0f1216;
     break-after: avoid; }
h3 { font: bold 13.5pt "DejaVu Sans", sans-serif; margin: 15pt 0 5pt;
     color: #1d2430; break-after: avoid; }
h4 { font: bold 11.5pt "DejaVu Sans", sans-serif; margin: 12pt 0 4pt;
     color: #303845; break-after: avoid; }
h5, h6 { font: bold 10.5pt "DejaVu Sans", sans-serif; margin: 10pt 0 3pt;
         break-after: avoid; }
p { margin: 0 0 8pt; orphans: 2; widows: 2; }
ul, ol { margin: 0 0 8pt; padding-left: 16pt; }
li { margin-bottom: 3pt; }
a { color: inherit; text-decoration: none; }
.meta { font: 9pt "DejaVu Sans", sans-serif; color: #5b6472;
        margin: 0 0 16pt; padding-bottom: 8pt; border-bottom: 2pt solid #16191d; }
.meta a { color: #5b6472; }
pre { font: 8.5pt/1.35 "DejaVu Sans Mono", monospace; background: #f4f5f7;
      border-left: 2.5pt solid #b9c0ca; padding: 6pt 8pt; margin: 0 0 9pt;
      white-space: pre-wrap; word-wrap: break-word; }
code { font: 9pt "DejaVu Sans Mono", monospace; background: #f1f2f4;
       padding: 0 2pt; word-wrap: break-word; }
pre code { background: none; padding: 0; font-size: inherit; }
blockquote { margin: 0 0 9pt; padding-left: 10pt; border-left: 2pt solid #c9ced6;
             color: #444c58; }
table { border-collapse: collapse; width: 100%; margin: 0 0 10pt;
        font: 8.5pt/1.35 "DejaVu Sans", sans-serif; }
th, td { border: 0.6pt solid #c2c8d0; padding: 3.5pt 5pt;
         text-align: left; vertical-align: top; word-wrap: break-word; }
th { background: #eceef1; font-weight: bold; }
tr { break-inside: avoid; }
img { max-width: 100%; height: auto; }
figure { margin: 0 0 10pt; break-inside: avoid; }
figcaption { font: italic 8.5pt "DejaVu Sans", sans-serif; color: #5b6472;
             margin-top: 3pt; }
hr { border: none; border-top: 0.6pt solid #c9ced6; margin: 12pt 0; }
"""

# WordPress furniture that is not part of the report body.
DROP_SELECTORS = (
    "script, style, iframe, noscript, form, button, "
    ".sharedaddy, .jp-relatedposts, .wp-block-buttons, .wp-block-button, "
    ".addtoany_share_save_container, .sd-sharing, .wp-block-embed__wrapper, "
    "#jp-post-flair, .post-navigation, .comments-area"
)


def api_get(session, **params):
    params.setdefault("_fields", "id,date,link,slug,title,content")
    r = session.get(API, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def find_posts(session, args):
    if args.url:
        posts = []
        for url in args.url:
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            hits = api_get(session, slug=slug)
            if not hits:
                print(f"  ! no post found for slug {slug!r}", file=sys.stderr)
            posts.extend(hits)
        return posts
    if args.search:
        return api_get(session, search=args.search, per_page=args.latest)
    return api_get(session, per_page=args.latest, orderby="date", order="desc")


def clean_html(raw, keep_images, keep_links):
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.select(DROP_SELECTORS):
        node.decompose()
    if not keep_links:
        # pymupdf4llm turns PDF link annotations back into [text](url), and a
        # single CyberChef permalink can be thousands of characters — enough to
        # get hard-sliced into six junk chunks. The text is what matters here.
        for a in soup.find_all("a"):
            a.attrs.pop("href", None)
    for img in soup.find_all("img"):
        if not keep_images:
            img.decompose()
            continue
        # WordPress lazy-loading leaves the real URL in a data attribute.
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src and img.get("srcset"):
            src = img["srcset"].split(",")[0].strip().split(" ")[0]
        if not src or src.startswith("data:"):
            img.decompose()
            continue
        img.attrs = {"src": src, "alt": img.get("alt", "")}
    if not keep_images:
        for fig in soup.find_all("figure"):
            if not fig.get_text(strip=True):
                fig.decompose()
    return str(soup)


def slugify(text, limit=70):
    text = unicodedata.normalize("NFKD", html.unescape(text))
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:limit].rstrip("-") or "untitled"


def make_fetcher(session):
    """Fetch remote images through the same session (plain urllib gets 403s)."""

    def fetcher(url):
        if url.startswith(("http://", "https://")):
            r = session.get(url, timeout=60)
            r.raise_for_status()
            return {
                "string": r.content,
                "mime_type": r.headers.get("content-type", "").split(";")[0] or None,
                "redirected_url": r.url,
            }
        return default_url_fetcher(url)

    return fetcher


def render(session, post, out_dir, keep_images, keep_links):
    title = html.unescape(post["title"]["rendered"])
    date = post["date"][:10]
    body = clean_html(post["content"]["rendered"], keep_images, keep_links)
    doc = (
        f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p class='meta'>The DFIR Report &nbsp;&middot;&nbsp; {date}"
        f" &nbsp;&middot;&nbsp; {html.escape(post['link'])}</p>"
        f"{body}</body></html>"
    )
    path = out_dir / f"dfir-{date}-{slugify(title)}.pdf"
    HTML(
        string=doc,
        base_url=post["link"],
        url_fetcher=make_fetcher(session),
    ).write_pdf(path)
    return path, title


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", nargs="+", help="article URL(s) to convert")
    ap.add_argument("--latest", type=int, default=5, metavar="N",
                    help="convert the N most recent posts (default 5)")
    ap.add_argument("--search", help="convert posts matching a search term")
    ap.add_argument("--list", action="store_true",
                    help="list matching posts, convert nothing")
    ap.add_argument("--no-images", dest="images", action="store_false",
                    help="drop images: much faster and smaller, and the text "
                         "pipeline ignores them anyway")
    ap.add_argument("--keep-links", dest="links", action="store_true",
                    help="keep hyperlink targets; off by default because long "
                         "permalinks survive into the extracted markdown as noise")
    ap.add_argument("--out", type=Path, default=Path("data/dfir_reports"),
                    help="output directory (default data/dfir_reports)")
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = UA

    posts = find_posts(session, args)
    if not posts:
        print("No posts matched.", file=sys.stderr)
        return 1

    if args.list:
        for p in posts:
            print(f"{p['date'][:10]}  {html.unescape(p['title']['rendered'])}")
            print(f"            {p['link']}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for p in posts:
        try:
            path, title = render(session, p, args.out, args.images, args.links)
        except Exception as exc:  # one bad post must not kill the batch
            print(f"  ! {p['link']}: {exc}", file=sys.stderr)
            continue
        kb = path.stat().st_size / 1024
        print(f"{path}  ({kb:.0f} KB)  {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
