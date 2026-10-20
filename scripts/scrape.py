#!/usr/bin/env python3
"""Refresh data/financials.json by scraping each company's stockanalysis.com
statistics page. This is the piece that replaces asking Claude to WebFetch every
company by hand: it runs for free inside the GitHub Actions runner (which has
normal internet access), on a schedule, with no per-call cost.

Usage:
  python3 scrape.py                 # refresh everything older than --max-age-days
  python3 scrape.py --only id1,id2  # refresh just these company ids
  python3 scrape.py --limit 50      # refresh at most 50 (oldest-first) -- good for a test run
  python3 scrape.py --force         # ignore the cache, refresh everything

Never crashes the whole run on one company: failures are logged per-id in
financials.json's "error" field and the previous good numbers are kept.
"""
import argparse, json, os, random, re, sys, time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("pip install requests beautifulsoup4")
from bs4 import BeautifulSoup

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_PATH = os.path.join(H, "data", "companies.json")
FINANCIALS_PATH = os.path.join(H, "data", "financials.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 20
MAX_RETRIES = 3
DELAY_RANGE = (1.2, 2.4)   # seconds between requests -- be polite, reduce block risk

# Each target field: list of candidate row-label substrings to match, in priority order.
FIELD_PATTERNS = {
    "mc":      [r"market\s*cap"],
    "pe":      [r"\bpe\s*ratio\b", r"price\s*/?\s*earnings", r"p\s*/\s*e\b"],
    "ev":      [r"ev\s*/\s*ebitda"],
    "rev":     [r"^revenue\s*(\(|$)"],
    "ebitda":  [r"^ebitda\s*(\(|$)"],
    "ni":      [r"^net\s*income\s*(\(|$)", r"^earnings\s*(\(|$)"],
    "ebm":     [r"ebitda\s*margin"],
    "npm":     [r"profit\s*margin", r"net\s*margin"],
    "roe":     [r"return\s*on\s*equity", r"\broe\b"],
    "roce":    [r"return\s*on\s*capital\s*employed", r"\broce\b",
                r"return\s*on\s*invested\s*capital", r"\broic\b"],
    "netcash": [r"net\s*cash\s*\(?\s*debt\s*\)?", r"net\s*debt", r"net\s*cash\b"],
}


def log(*a):
    print(*a, flush=True)


def parse_number(text):
    """'$53.85B' -> 53.85 (billions); '18.50%' -> 18.50; '22.37x' -> 22.37;
    '(1.23)' -> -1.23; 'NaN'/'-'/'n/a'/'' -> None. Values already in whole
    currency units (no suffix) are assumed to be in billions already, matching
    the rest of this pipeline's convention."""
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("$", "").replace("%", "").replace("x", "")
    if t in ("", "-", "NaN", "n/a", "N/A", "NA", "--"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    mult = 1.0
    if t and t[-1] in "TBMK":
        mult = {"T": 1000.0, "B": 1.0, "M": 0.001, "K": 0.000001}[t[-1]]
        t = t[:-1]
    try:
        v = float(t) * mult
    except ValueError:
        return None
    return -v if neg else v


def extract_table_rows(soup):
    """Every <tr> with >=2 cells, first cell = label, second = most-recent (ttm/current)
    value. stockanalysis.com's tables put the latest period in the first data column."""
    rows = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        value = cells[1].get_text(" ", strip=True)
        if label and label not in rows:  # keep first occurrence (summary table before history table)
            rows[label] = value
    return rows


def match_field(rows, patterns):
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for label, value in rows.items():
            if rx.search(label):
                v = parse_number(value)
                if v is not None:
                    return v
    return None


def fetch_one(session, cid, ident):
    url = f"https://stockanalysis.com/{ident['path']}/statistics/"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(2 * attempt)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.get_text() if soup.title else ""
            if "just a moment" in title.lower() or "attention required" in title.lower():
                last_err = "blocked (challenge page)"
                time.sleep(3 * attempt)
                continue
            rows = extract_table_rows(soup)
            if not rows:
                last_err = "no tables found on page"
                time.sleep(2 * attempt)
                continue
            out = {}
            for field, patterns in FIELD_PATTERNS.items():
                out[field] = match_field(rows, patterns)
            # currency: best-effort from a $ or ₹ sign near market cap/revenue rows, else keep existing
            cur = None
            for label in rows:
                if "₹" in rows.get(label, ""):
                    cur = "INR"; break
                if "$" in rows.get(label, ""):
                    cur = "USD"; break
            if cur:
                out["cur"] = cur
            return out, None
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(2 * attempt)
    return None, last_err or "unknown error"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated company ids to refresh")
    ap.add_argument("--limit", type=int, help="refresh at most this many (oldest-fetched first)")
    ap.add_argument("--max-age-days", type=int, default=6,
                     help="skip companies whose financials were fetched more recently than this")
    ap.add_argument("--force", action="store_true", help="ignore the cache / max-age-days")
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

    log(f"refreshing {len(ids)} of {len(companies)} companies "
        f"(max_age_days={args.max_age_days}, force={args.force})")

    session = requests.Session()
    ok = fail = 0
    for n, cid in enumerate(ids, 1):
        ident = companies[cid]
        result, err = fetch_one(session, cid, ident)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prev = financials.get(cid, {})
        if result is not None:
            merged = dict(prev)
            merged.update(result)
            merged["fetched_at"] = now_iso
            merged["error"] = None
            financials[cid] = merged
            ok += 1
            log(f"[{n}/{len(ids)}] OK   {cid} ({ident['n']})")
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
    if fail:
        log("Failures keep the last good numbers in financials.json; nothing is wiped.")


if __name__ == "__main__":
    main()
