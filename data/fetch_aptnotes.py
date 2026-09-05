#!/usr/bin/env python3
"""Download APT reports from the APTnotes archive (github.com/aptnotes/data).

The repo itself only holds an index; the PDFs sit behind Box shared links, and
the official aptnotes/tools scripts no longer work against Box's current
download flow. This resolves each shared link to its file id, then hits Box's
shared-file download endpoint with the session cookie it hands out.

  python3 data/fetch_aptnotes.py --year 2023 2024 --limit 10
  python3 data/fetch_aptnotes.py --match 'ransomware|intrusion' --out data/uploads
  python3 data/fetch_aptnotes.py --list --year 2024

Stdlib only. Re-runs skip files already on disk, so it resumes after a Ctrl-C.
"""

import argparse
import csv
import hashlib
import http.cookiejar
import io
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

INDEX_URL = "https://raw.githubusercontent.com/aptnotes/data/master/APTnotes.csv"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
FILE_ID_RE = re.compile(r"f_\d{6,}")


def build_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    return opener


def fetch(opener, url, referer=None, timeout=90):
    req = urllib.request.Request(url)
    if referer:
        req.add_header("Referer", referer)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def load_index(opener, cache: Path):
    if not cache.exists():
        print(f"fetching index -> {cache}", file=sys.stderr)
        body, _ = fetch(opener, INDEX_URL)
        cache.write_bytes(body)
    text = cache.read_text(encoding="utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def safe_name(filename: str) -> str:
    keep = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return (keep or "report")[:150] + ".pdf"


def download(opener, share_url: str, dest: Path) -> str:
    """Returns the sha1 of the downloaded file, or raises."""
    page, _ = fetch(opener, share_url)
    match = FILE_ID_RE.search(page.decode("utf-8", "replace"))
    if not match:
        raise RuntimeError("no file id on the share page (link dead or rate-limited)")
    shared_name = share_url.rstrip("/").rsplit("/", 1)[-1]
    dl = "https://app.box.com/index.php?" + urllib.parse.urlencode(
        {
            "rm": "box_download_shared_file",
            "shared_name": shared_name,
            "file_id": match.group(0),
        }
    )
    body, ctype = fetch(opener, dl, referer=share_url)
    if not body.startswith(b"%PDF") and "pdf" not in ctype.lower():
        raise RuntimeError(f"not a PDF (content-type {ctype!r}, {len(body)} bytes)")
    dest.write_bytes(body)
    return hashlib.sha1(body).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("data/aptnotes"),
                    help="output directory (default: data/aptnotes)")
    ap.add_argument("--year", nargs="+", help="restrict to these years")
    ap.add_argument("--source", nargs="+", help="restrict to these sources (substring, case-insensitive)")
    ap.add_argument("--match", help="regex over the report title")
    ap.add_argument("--limit", type=int, help="stop after N reports")
    ap.add_argument("--list", action="store_true", help="print matches and exit, download nothing")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between downloads (default 1.5)")
    args = ap.parse_args()

    opener = build_opener()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = load_index(opener, args.out / "APTnotes.csv")

    title_re = re.compile(args.match, re.I) if args.match else None
    sources = [s.lower() for s in (args.source or [])]

    picked = []
    for row in rows:
        if args.year and row["Year"] not in args.year:
            continue
        if sources and not any(s in row["Source"].lower() for s in sources):
            continue
        if title_re and not title_re.search(row["Title"]):
            continue
        picked.append(row)
    if args.limit:
        picked = picked[: args.limit]

    print(f"{len(picked)} of {len(rows)} reports match", file=sys.stderr)
    if args.list:
        for row in picked:
            print(f"{row['Date']}  {row['Source'][:24]:<24}  {row['Title']}")
        return 0

    ok = skipped = failed = 0
    for i, row in enumerate(picked, 1):
        dest = args.out / safe_name(row["Filename"])
        if dest.exists():
            skipped += 1
            continue
        label = f"[{i}/{len(picked)}] {row['Title'][:64]}"
        try:
            digest = download(opener, row["Link"], dest)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{label}\n    FAILED: {exc}", file=sys.stderr)
            failed += 1
            continue
        expected = (row.get("SHA-1") or "").strip().lower()
        mark = "" if not expected else (" sha1 ok" if digest == expected else " SHA1 MISMATCH")
        print(f"{label}\n    -> {dest} ({dest.stat().st_size // 1024} KB){mark}")
        ok += 1
        time.sleep(args.delay)

    print(f"\ndownloaded {ok}, skipped {skipped} already present, {failed} failed",
          file=sys.stderr)
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
