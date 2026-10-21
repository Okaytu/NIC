"""Source 0 (tried first when a FINNHUB_API_KEY is configured): the Finnhub
REST API (https://finnhub.io), free tier, 60 req/min. Structured JSON
instead of HTML -- far more robust than scraping where it has coverage.

Real limitation, stated plainly: Finnhub's free tier is strongest for
US-listed tickers. International/small-cap coverage on the free tier is
inconsistent -- this pipeline treats it as "try first, keep whatever
fields it returns" and lets the HTML scrapers fill in anything missing,
rather than assuming it covers everything. NOT YET LIVE-TESTED (no key
configured yet at the time this was written) -- the exact JSON keys
below are Finnhub's documented field names as of this pipeline's
knowledge cutoff; if Finnhub's response shape differs, the first live
run's error log will show which fields came back empty and this file's
METRIC_KEYS table is the one place to fix it.
"""
import os

TIMEOUT = 15
BASE = "https://finnhub.io/api/v1"

# path-prefix -> Finnhub exchange suffix. Best-effort; Finnhub's own
# /stock/symbol-lookup endpoint would be more reliable but costs an extra
# call per company, so this static map is tried first.
EXCHANGE_SUFFIX = {
    "quote/nse/": ".NS", "quote/bom/": ".BO",
    "quote/lon/": ".L", "quote/etr/": ".DE", "quote/epa/": ".PA",
    "quote/swx/": ".SW", "quote/osl/": ".OL", "quote/sto/": ".ST",
    "quote/hel/": ".HE", "quote/cph/": ".CO", "quote/ams/": ".AS",
    "quote/bit/": ".MI", "quote/tyo/": ".T", "quote/hkg/": ".HK",
    "quote/asx/": ".AX", "quote/tsx/": ".TO", "quote/bvmf/": ".SA",
    "quote/bkk/": ".BK", "quote/sgx/": ".SI", "quote/she/": ".SZ",
    "quote/vie/": ".VI", "quote/wse/": ".WA",
}

METRIC_KEYS = {
    "pe":   ["peTTM", "peExclExtraTTM", "peBasicExclExtraTTM", "peAnnual"],
    "roe":  ["roeTTM", "roeRfy", "roeAnnual"],
    "roce": ["roicTTM", "roiTTM", "roicAnnual"],  # ROIC used as a ROCE proxy
    "ebm":  ["ebitdaMarginTTM", "ebitdaMargin5Y"],
    "npm":  ["netProfitMarginTTM", "netMarginTTM", "netProfitMarginAnnual"],
    "ev":   ["currentEv/freeCashFlowTTM"],  # placeholder; EV/EBITDA often absent on free tier
}


def to_symbol(path):
    for prefix, suffix in EXCHANGE_SUFFIX.items():
        if path.startswith(prefix):
            return path[len(prefix):] + suffix
    if path.startswith("stocks/"):
        return path[len("stocks/"):].upper()
    return None


def fetch(session, ident, headers, max_retries=2, sleep_fn=None):
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return None, "no FINNHUB_API_KEY configured"
    symbol = to_symbol(ident["path"])
    if not symbol:
        return None, f"no Finnhub symbol mapping for path {ident['path']}"
    out = {}
    last_err = None
    try:
        r = session.get(f"{BASE}/stock/metric", params={"symbol": symbol, "metric": "all", "token": key}, timeout=TIMEOUT)
        if r.status_code == 200:
            m = (r.json() or {}).get("metric", {}) or {}
            for field, keys in METRIC_KEYS.items():
                for k in keys:
                    if m.get(k) is not None:
                        out[field] = m[k]
                        break
        elif r.status_code == 429:
            return None, "rate limited"
        else:
            last_err = f"metric HTTP {r.status_code}"
    except Exception as e:
        last_err = f"metric error: {e}"

    try:
        r = session.get(f"{BASE}/stock/profile2", params={"symbol": symbol, "token": key}, timeout=TIMEOUT)
        if r.status_code == 200:
            p = r.json() or {}
            if p.get("marketCapitalization"):
                out["mc"] = p["marketCapitalization"] / 1000.0  # Finnhub reports in millions
            if p.get("currency"):
                out["cur"] = p["currency"]
    except Exception as e:
        if not last_err:
            last_err = f"profile error: {e}"

    if not out:
        return None, last_err or "no data returned"
    return out, None
