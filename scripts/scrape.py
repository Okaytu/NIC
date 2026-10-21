#!/usr/bin/env python3
"""Refresh data/financials.json from multiple sources, in priority order:
  1. Finnhub API       (scripts/sources/finnhub.py)      -- structured, needs FINNHUB_API_KEY
  2. stockanalysis.com  (scripts/sources/stockanalysis.py) -- global coverage, scraped
  3. screener.in        (scripts/sources/screener.py)      -- India-only fallback, scraped

For each company, every source is tried in order and results are merged
field-by-field (first source to supply a field wins); a source only needs
to succeed partially to contribute. A company fails only if every source
returns nothing. Never crashes the whole run on one company; failures are
logged per-id in financials.json's "error" field and the previous good
numbers are kept.

Usage:
  python3 scrape.py                 # refresh everything older than --max-age-days
  python3 scrape.py --only id1,id2  # refresh just these company ids
  python3 scrape.py --limit 50      # refresh at most 50 (oldest-first) -- good for a test run
  python3 scrape.py --force         # ignore the cache, refresh everything
"""
import argparse, json, os, random, sys, time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("pip install requests beautifulsoup4")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import finnhub, stockanalysis, screener

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_PATH = os.path.join(H, "data", "companies.json")
FINANCIALS_PATH = os.path.join(H, "data", "financials.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
DELAY_RANGE = (1.2, 2.4)

CANONICAL_FIELDS = ["cur", "rev", "ebitda", "ni", "ebm", "npm", "roce", "roe", "netcash", "pe", "ev", "mc"]

SOURCES = [
    ("finnhub", finnhub.fetch),
    ("stockanalysis", stockanalysis.fetch),
    ("screener.in", screener.fetch),
]


def log(*a):
    print(*a, flush=True)


def fetch_one(session, ident):
    merged = {}
    used_sources = []
    errors = []
    for name, fn in SOURCES:
        missing = [f for f in CANONICAL_FIELDS if f not in merged]
        if not missing:
            break
        data, err = fn(session, ident, HEADERS, sleep_fn=time.sleep)
        if data:
            added = False
            for k, v in data.items():
                if k not in merged and v is not None:
                    merged[k] = v
                    added = True
            if added:
                used_sources.append(name)
        if err:
            errors.append(f"{name}: {err}")
    if not merged:
        return None, "; ".join(errors) or "all sources failed", []
    return merged, None, used_sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company ids to refresh")
    ap.add_argument("--limit", type=int, help="refresh at most this many (oldest-fetched first)")
    ap.add_argument("--max-age-days", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    companies = json.load(open(COMPANIES_PATH, encoding="utf-8"))
    financials = json.load(open(FINANCIALS_PATH, encoding="utf-8"))

    ids = list(companies)
    if args.only:
        wanted = set(args.only.split(","))
        ids = [i for i in ids if i in wanted]
    elif not args.force:
        now = datetime.now(timezone.utc)
        def age_days(i):
            ts = financials.get(i, {}).get("fetched_at")
            if not ts:
                return 9999
            try:
                return (now - datetime.fromisoformat(ts)).total_seconds() / 86400
            except ValueError:
                return 9999
        ids = [i for i in ids if age_days(i) >= args.max_age_days]
        ids.sort(key=age_days, reverse=True)

    if args.limit:
        ids = ids[: args.limit]

    has_key = bool(os.environ.get("FINNHUB_API_KEY"))
    log(f"refreshing {len(ids)} of {len(companies)} companies "
        f"(max_age_days={args.max_age_days}, force={args.force}, finnhub={'on' if has_key else 'off'})")

    session = requests.Session()
    ok = fail = 0
    source_counts = {}
    for n, cid in enumerate(ids, 1):
        ident = companies[cid]
        result, err, used = fetch_one(session, ident)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prev = financials.get(cid, {})
        if result is not None:
            merged = dict(prev)
            merged.update(result)
            merged["fetched_at"] = now_iso
            merged["error"] = None
            merged["sources"] = used
            financials[cid] = merged
            ok += 1
            for s in used:
                source_counts[s] = source_counts.get(s, 0) + 1
            log(f"[{n}/{len(ids)}] OK   {cid} ({ident['n']}) via {'+'.join(used)}")
        else:
            prev["error"] = err
            prev["error_at"] = now_iso
            financials[cid] = prev
            fail += 1
            log(f"[{n}/{len(ids)}] FAIL {cid} ({ident['n']}): {err}")
        json.dump(financials, open(FINANCIALS_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        time.sleep(random.uniform(*DELAY_RANGE))

    log(f"done: {ok} ok, {fail} failed")
    log("source usage: " + ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items())))
    if fail:
        log("Failures keep the last good numbers in financials.json; nothing is wiped.")


if __name__ == "__main__":
    main()
