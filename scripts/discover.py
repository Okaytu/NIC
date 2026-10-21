#!/usr/bin/env python3
"""Find candidate listed companies for NIC business codes that currently
have zero mapped companies, using structured (low-noise) sources only:

  1. Wikipedia search + infobox "traded_as" extraction
  2. SEC EDGAR full-text search (10-K filings) + the official ticker list

A name alone is not enough to trust: every candidate is *verified* by
actually fetching its stockanalysis.com statistics page (reusing
scripts/sources/stockanalysis.py). A candidate that verifies -- the page
exists and returns real numbers -- is high-confidence and gets merged
straight into data/map_<S>.json and data/companies.json (financials come
free from the same fetch). A candidate that's found but doesn't verify
(no resolvable ticker, or the page 404s) is recorded in
data/discovery_queue.json for manual review instead of being merged.

Deliberately NOT included in v1: general web search (DuckDuckGo/etc).
Structured sources (Wikipedia infoboxes, EDGAR) are precise enough to
verify automatically; free-text web search is noisy enough that it needs
a human in the loop, which defeats the point of a confidence-scored
auto-add. Candidate codes it can't fill stay honestly unfilled, same as
the existing "no listed company found" notes elsewhere in this project.

Usage:
  python3 discover.py --limit 20       # process 20 empty codes (default)
  python3 discover.py --section C      # only within section C
  python3 discover.py --dry-run        # find & verify, but never write
"""
import argparse, csv, json, os, re, sys, time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("pip install requests beautifulsoup4")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import stockanalysis

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(H, "data", "NIC_2025_Business_Master.csv")
COMPANIES_PATH = os.path.join(H, "data", "companies.json")
FINANCIALS_PATH = os.path.join(H, "data", "financials.json")
QUEUE_PATH = os.path.join(H, "data", "discovery_queue.json")

# Wikipedia's own User-Agent policy (meta.wikimedia.org/wiki/User-Agent_policy)
# asks non-browser clients to identify themselves plainly as "tool/version
# (contact)" rather than spoof a browser string -- a spoofed browser UA
# combined with rapid, delay-free API calls from a shared GitHub Actions IP
# range is exactly the pattern anonymous-abuse rate limiting targets. Live
# testing confirmed this: every single Wikipedia API call in a run came back
# HTTP 429, immediately, even the very first one -- not a volume problem on
# our side, but the runner's shared IP already being rate-limited.
UA = "NIC-business-company-map/1.0 (https://github.com/Okaytu/NIC)"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
# SEC asks non-browser clients to identify themselves with a real contact.
SEC_HEADERS = {"User-Agent": "NIC-company-map research tool contact@example.invalid"}


def get_with_retry(session, url, headers, params, max_retries=4, sleep_fn=time.sleep):
    """GET with backoff on 429/503. Honors Retry-After when the server sends
    one; otherwise backs off 3s, 8s, 20s. Returns the Response, or None if
    every attempt failed -- callers treat None exactly like an old
    non-200 response (skip, don't crash)."""
    delay_schedule = [3, 8, 20, 45]
    for attempt in range(max_retries):
        try:
            r = session.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException:
            return None
        if r.status_code not in (429, 503):
            return r
        wait = delay_schedule[min(attempt, len(delay_schedule) - 1)]
        retry_after = r.headers.get("Retry-After")
        if retry_after:
            try:
                wait = max(wait, min(float(retry_after), 60))
            except ValueError:
                pass
        if attempt < max_retries - 1:
            sleep_fn(wait)
    return r  # return the last (still-failing) response rather than None

WIKI_EXCHANGE_TO_PATH = {
    # NYSE/NASDAQ are handled as a special case in wiki_candidates() (path
    # is just stocks/<ticker>, no quote/<exchange>/ prefix) -- listed here
    # only so the regex that finds {{EXCHANGE|TICKER}} infobox templates
    # recognizes them too.
    "NYSE": None, "NASDAQ": None,
    "LSE": "quote/lon/{t}", "LON": "quote/lon/{t}",
    "BSE": "quote/bom/{t}", "NSE": "quote/nse/{t}",
    "TYO": "quote/tyo/{t}", "TSE": "quote/tyo/{t}",
    "HKG": "quote/hkg/{t}", "SEHK": "quote/hkg/{t}",
    "ASX": "quote/asx/{t}", "TSX": "quote/tsx/{t}",
    "SIX": "quote/swx/{t}", "SWX": "quote/swx/{t}",
    "FWB": "quote/etr/{t}", "ETR": "quote/etr/{t}",
    "EPA": "quote/epa/{t}", "AMS": "quote/ams/{t}",
}
WIKI_COUNTRY = {
    "LSE": "UK", "LON": "UK", "BSE": "India", "NSE": "India",
    "TYO": "Japan", "TSE": "Japan", "HKG": "China", "SEHK": "China",
    "ASX": "Australia", "TSX": "Canada", "SIX": "Switzerland", "SWX": "Switzerland",
    "FWB": "Germany", "ETR": "Germany", "EPA": "France", "AMS": "Netherlands",
}


def log(*a):
    print(*a, flush=True)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "", name.lower())
    return s[:20] or "co"


def load_all_used_ids():
    """Every company id already placed under any NIC code, across every
    section -- the one hard rule this whole project is built on: a company
    may not be used twice."""
    used = set()
    for mpath in sorted(__import__("glob").glob(os.path.join(H, "data", "map_*.json"))):
        m = json.load(open(mpath, encoding="utf-8"))
        for ids in m.get("biz", {}).values():
            used.update(ids)
    return used


def find_empty_codes(section_filter=None):
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    out = []
    import glob
    for mpath in sorted(glob.glob(os.path.join(H, "data", "map_*.json"))):
        S = os.path.basename(mpath)[4]
        if section_filter and S != section_filter:
            continue
        m = json.load(open(mpath, encoding="utf-8"))
        for r in rows:
            if r["Section"] != S:
                continue
            code = r["NIC Code"]
            if not m.get("biz", {}).get(code):
                out.append((S, code, r["Business Activity"]))
    return out


# ---------------------------------------------------------------- Wikipedia

def wiki_search(session, query, limit=4):
    r = get_with_retry(session, "https://en.wikipedia.org/w/api.php", HEADERS, {
        "action": "query", "list": "search", "srsearch": query + " company",
        "format": "json", "srlimit": limit,
    })
    if r is None or r.status_code != 200:
        return []
    try:
        return [hit["title"] for hit in r.json().get("query", {}).get("search", [])]
    except ValueError:
        return []


_EXCHANGE_ALT = "NYSE|NASDAQ|LSE|LON|BSE|NSE|TYO|TSE|HKG|SEHK|ASX|TSX|SIX|SWX|FWB|ETR|EPA|AMS"
# Live-tested finding: most current Wikipedia infoboxes render the
# "Traded as" field as plain text ("Nasdaq: PLUG"), not the older
# {{NASDAQ|PLUG}} template style this originally assumed -- confirmed by
# checking en.wikipedia.org/wiki/Plug_Power directly. Both forms are
# matched here since older articles may still use the template form.
_TEMPLATE_RE = re.compile(r"\{\{\s*(" + _EXCHANGE_ALT + r")\s*\|\s*([A-Za-z0-9.]{1,10})\s*\}\}", re.I)
_PLAINTEXT_RE = re.compile(r"\b(" + _EXCHANGE_ALT + r")\s*:\s*([A-Za-z0-9.]{1,10})\b", re.I)


def wiki_fetch_wikitexts(session, titles):
    """Fetches section-0 wikitext for several titles in ONE API call
    (action=query/prop=revisions, pipe-joined titles) instead of one
    action=parse call per title. Cuts request count ~4x and, more
    importantly, is the batching MediaWiki itself expects clients to use
    rather than hammering it with individual per-page requests. Returns
    {title: wikitext}; a title that's missing, a redirect with no content,
    or fails to fetch simply maps to ""."""
    if not titles:
        return {}
    r = get_with_retry(session, "https://en.wikipedia.org/w/api.php", HEADERS, {
        "action": "query", "titles": "|".join(titles), "prop": "revisions",
        "rvprop": "content", "rvslots": "main", "rvsection": 0,
        "format": "json", "formatversion": 2,
    })
    out = {t: "" for t in titles}
    if r is None or r.status_code != 200:
        return out
    try:
        pages = r.json().get("query", {}).get("pages", [])
    except ValueError:
        return out
    for p in pages:
        if p.get("missing") or not p.get("revisions"):
            continue
        content = p["revisions"][0].get("slots", {}).get("main", {}).get("content", "")
        out[p.get("title", "")] = content
    return out


def wiki_infobox_ticker(wikitext):
    """Returns a list of (exchange, ticker) pairs found in a 'traded_as'
    style infobox field, matching both {{NSE|TCS}} template style and
    plain "NSE: TCS" text style. Pure text processing -- no network -- so
    it can be reused directly against a batched wiki_fetch_wikitexts()
    result."""
    if not wikitext:
        return []
    # Narrow to just the traded_as parameter's value when we can find it
    # (avoids picking up an unrelated exchange mention elsewhere in the
    # infobox); fall back to the whole section if that fails.
    m = re.search(r"\|\s*traded_as\s*=\s*(.*?)\n\s*\|", wikitext, re.S | re.I)
    scope = m.group(1) if m else wikitext
    pairs = _TEMPLATE_RE.findall(scope) + _PLAINTEXT_RE.findall(scope)
    seen, out = set(), []
    for ex, tk in pairs:
        key = (ex.upper(), tk.upper())
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def wiki_candidates(session, query):
    titles = wiki_search(session, query)
    wikitexts = wiki_fetch_wikitexts(session, titles)
    out = []
    for title in titles:
        for exchange, ticker in wiki_infobox_ticker(wikitexts.get(title, "")):
            if exchange == "NYSE" or exchange == "NASDAQ":
                path = f"stocks/{ticker.lower()}"
                country = "USA"
            else:
                tmpl = WIKI_EXCHANGE_TO_PATH.get(exchange)
                if not tmpl:
                    continue
                path = tmpl.format(t=ticker)
                country = WIKI_COUNTRY.get(exchange, "")
            out.append({"name": title, "tk": ticker, "ctry": country, "path": path, "source": "wikipedia"})
    return out


# -------------------------------------------------------------------- EDGAR

_EDGAR_TICKERS = None

def edgar_ticker_lookup(session):
    global _EDGAR_TICKERS
    if _EDGAR_TICKERS is not None:
        return _EDGAR_TICKERS
    r = get_with_retry(session, "https://www.sec.gov/files/company_tickers.json", SEC_HEADERS, {})
    try:
        _EDGAR_TICKERS = {row["title"].upper(): row["ticker"] for row in r.json().values()} if r is not None and r.status_code == 200 else {}
    except ValueError:
        _EDGAR_TICKERS = {}
    return _EDGAR_TICKERS


def edgar_candidates(session, query, limit=4):
    r = get_with_retry(session, "https://efts.sec.gov/LATEST/search-index", SEC_HEADERS, {
        "q": f'"{query}"', "forms": "10-K",
    })
    if r is None or r.status_code != 200:
        return []
    try:
        hits = r.json().get("hits", {}).get("hits", [])[:limit]
    except ValueError:
        return []
    tickers = edgar_ticker_lookup(session)
    out = []
    for h in hits:
        names = h.get("_source", {}).get("display_names", [])
        if not names:
            continue
        # EDGAR's display_names look like "Apple Inc.  (AAPL)  (CIK 0000320193)"
        # -- two trailing parenthetical annotations, not one. The old regex
        # only stripped "(CIK ...)", leaving "Apple Inc.  (AAPL)" behind,
        # which never matches the plain "APPLE INC." key in SEC's own
        # ticker list -- so every real EDGAR hit was silently dropped.
        # Strip every trailing "(...)" group, however many there are.
        name = re.sub(r"(\s*\([^)]*\))+$", "", names[0]).strip()
        tk = tickers.get(name.upper())
        if tk:
            out.append({"name": name, "tk": tk, "ctry": "USA", "path": f"stocks/{tk.lower()}", "source": "edgar"})
    return out


# ---------------------------------------------------------------- pipeline

def verify(session, candidate):
    data, err = stockanalysis.fetch(session, candidate, HEADERS, max_retries=2, sleep_fn=time.sleep)
    return (data, None) if data else (None, err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--section")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    companies = json.load(open(COMPANIES_PATH, encoding="utf-8"))
    financials = json.load(open(FINANCIALS_PATH, encoding="utf-8"))
    queue = json.load(open(QUEUE_PATH, encoding="utf-8")) if os.path.exists(QUEUE_PATH) else {}
    used_ids = load_all_used_ids()
    used_names = {c["n"].lower() for c in companies.values()}

    empty = find_empty_codes(args.section)
    log(f"{len(empty)} NIC codes have zero mapped companies; processing up to {args.limit}")
    empty = empty[: args.limit]

    session = requests.Session()
    map_cache = {}  # section -> loaded map json, written back at the end
    added_total = queued_total = 0

    for i, (S, code, activity) in enumerate(empty):
        if i:
            time.sleep(1.5)  # pace requests across codes, on top of get_with_retry's own backoff
        log(f"\n--- {S}/{code}: {activity}")
        candidates = wiki_candidates(session, activity) + edgar_candidates(session, activity)
        # de-dupe by (ctry, tk)
        seen = set()
        uniq = []
        for c in candidates:
            key = (c["ctry"], c["tk"])
            if key not in seen:
                seen.add(key)
                uniq.append(c)

        verified_ids = []
        entry = queue.setdefault(code, {"activity": activity, "section": S, "candidates": []})
        for cand in uniq:
            cid = slugify(cand["name"])
            base_cid = cid
            i = 2
            while cid in companies and companies[cid]["n"].lower() != cand["name"].lower():
                cid = f"{base_cid}{i}"; i += 1
            if cid in used_ids:
                log(f"  skip {cand['name']} ({cand['source']}): company id already used elsewhere")
                continue
            if cand["name"].lower() in used_names:
                log(f"  skip {cand['name']} ({cand['source']}): same name already mapped elsewhere")
                continue
            data, err = verify(session, cand)
            time.sleep(1.0)
            if data:
                log(f"  VERIFIED {cand['name']} ({cand['tk']}, {cand['source']}) -> auto-add")
                companies[cid] = {"n": cand["name"], "tk": cand["tk"], "ctry": cand["ctry"], "path": cand["path"]}
                financials[cid] = dict(data, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        error=None, sources=[cand["source"] + "+stockanalysis"])
                used_ids.add(cid)
                used_names.add(cand["name"].lower())
                verified_ids.append(cid)
                entry["candidates"].append({**cand, "id": cid, "verified": True, "auto_added": True})
                added_total += 1
            else:
                log(f"  unverified {cand['name']} ({cand['tk']}, {cand['source']}): {err}")
                entry["candidates"].append({**cand, "id": cid, "verified": False, "auto_added": False, "error": err})
                queued_total += 1
            if len(verified_ids) >= 5:
                break

        if verified_ids:
            if S not in map_cache:
                map_cache[S] = json.load(open(os.path.join(H, "data", f"map_{S}.json"), encoding="utf-8"))
            map_cache[S].setdefault("biz", {})[code] = verified_ids
            map_cache[S].setdefault("bnote", {})[code] = (
                f"Auto-discovered via Wikipedia/SEC EDGAR and verified against stockanalysis.com "
                f"on {datetime.now(timezone.utc):%Y-%m-%d}. Worth a human sanity check."
            )

    log(f"\ndone: {added_total} auto-added, {queued_total} queued for review "
        f"(see data/discovery_queue.json)")

    if not args.dry_run:
        json.dump(companies, open(COMPANIES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
        json.dump(financials, open(FINANCIALS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
        json.dump(queue, open(QUEUE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
        for S, m in map_cache.items():
            json.dump(m, open(os.path.join(H, "data", f"map_{S}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        log("(--dry-run: nothing written)")


if __name__ == "__main__":
    main()
