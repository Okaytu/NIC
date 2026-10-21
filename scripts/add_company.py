"""Manually add ONE company to ONE NIC business code, from a
stockanalysis.com page you found yourself -- for codes the automated
discovery pipeline (discover.py) genuinely can't find a listed company
for (e.g. "Growing of Bajra and Jowar and other millets": no listed
company specializes narrowly enough in that one crop for any search,
however broad, to ever surface it).

Reuses exactly the same scraper (sources/stockanalysis.py) and the same
hard rule (a company id/name is never used under more than one NIC code)
as the rest of the pipeline does, so a manually-added company is
indistinguishable in companies.json/financials.json from an
auto-discovered one -- it "looks like the others" on the site.

Usage:
  python3 scripts/add_company.py --code 011101 --path quote/nse/RALLIS \
      --name "Rallis India Ltd" [--ticker RALLIS] [--country India] [--dry-run]

--path is the same stockanalysis.com URL segment the rest of the project
uses everywhere else: whatever comes right after stockanalysis.com/ and
right before /statistics/ on that company's page. Find a company's real
page on stockanalysis.com first, copy that segment.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover import (  # noqa: E402
    COMPANIES_PATH, FINANCIALS_PATH, H, HEADERS, clean_activity, load_all_used_ids, slugify,
)
from sources import stockanalysis  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="NIC code, e.g. 011101")
    ap.add_argument("--path", required=True, help="stockanalysis.com path segment, e.g. quote/nse/TCS")
    ap.add_argument("--name", required=True, help="Company name")
    ap.add_argument("--ticker", default="", help="Ticker (defaults to the last path segment)")
    ap.add_argument("--country", default="", help="Country (defaults to India for quote/nse|bom paths, else blank)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.path.strip().strip("/")
    code = args.code.strip()
    name = args.name.strip()
    if not path or not code or not name:
        print("ERROR: --code, --path and --name must all be non-empty", file=sys.stderr)
        sys.exit(1)

    ticker = args.ticker.strip() or path.rstrip("/").rsplit("/", 1)[-1]
    country = args.country.strip() or ("India" if path.startswith(("quote/nse/", "quote/bom/")) else "")

    import csv
    rows = list(csv.DictReader(open(os.path.join(H, "data", "NIC_2025_Business_Master.csv"), encoding="utf-8-sig")))
    row = next((r for r in rows if r["NIC Code"] == code), None)
    if row is None:
        print(f"ERROR: NIC code {code} not found in data/NIC_2025_Business_Master.csv", file=sys.stderr)
        sys.exit(1)
    S = row["Section"]
    activity = clean_activity(row["Business Activity"])
    print(f"NIC {code} ({S}): {activity}")

    map_path = os.path.join(H, "data", f"map_{S}.json")
    m = json.load(open(map_path, encoding="utf-8"))
    existing = m.get("biz", {}).get(code, [])
    if len(existing) >= 5:
        print(f"ERROR: {code} already has 5 companies ({existing}) -- remove one first", file=sys.stderr)
        sys.exit(1)

    companies = json.load(open(COMPANIES_PATH, encoding="utf-8"))
    financials = json.load(open(FINANCIALS_PATH, encoding="utf-8"))
    used_ids = load_all_used_ids()
    used_names = {c["n"].lower() for c in companies.values()}

    cid = slugify(name)
    base_cid = cid
    n = 2
    while cid in companies and companies[cid]["n"].lower() != name.lower():
        cid = f"{base_cid}{n}"
        n += 1
    if cid in used_ids:
        print(f"ERROR: company id '{cid}' is already used under another NIC code -- a company can't be used twice", file=sys.stderr)
        sys.exit(1)
    if name.lower() in used_names:
        print(f"ERROR: a company named '{name}' is already mapped elsewhere", file=sys.stderr)
        sys.exit(1)

    cand = {"name": name, "tk": ticker, "ctry": country, "path": path}
    session = requests.Session()
    print(f"fetching https://stockanalysis.com/{path}/statistics/ ...")
    data, err = stockanalysis.fetch(session, cand, HEADERS, max_retries=3, sleep_fn=__import__("time").sleep)
    if not data:
        print(f"ERROR: could not verify this company -- {err}\n"
              f"Check the --path is exactly right (copy it from the company's real stockanalysis.com URL).", file=sys.stderr)
        sys.exit(1)
    print(f"OK: fetched financials for {name} ({ticker})")

    if args.dry_run:
        print("--dry-run: nothing written. Would add:", cid, "->", code)
        return

    companies[cid] = {"n": name, "tk": ticker, "ctry": country, "path": path}
    financials[cid] = dict(data, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            error=None, sources=["manual+stockanalysis"])
    m.setdefault("biz", {})[code] = existing + [cid]
    existing_note = m.setdefault("bnote", {}).get(code, "")
    added_note = f"'{name}' added manually via scripts/add_company.py on {datetime.now(timezone.utc):%Y-%m-%d}."
    m["bnote"][code] = (existing_note + " " + added_note).strip() if existing_note else added_note

    json.dump(companies, open(COMPANIES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(financials, open(FINANCIALS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(m, open(map_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"done: added {cid} ({name}) to {code}")


if __name__ == "__main__":
    main()
