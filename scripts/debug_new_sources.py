"""One-off: validate the new yahoo_candidates()/screener_candidates()
sources actually work and return sane data against real known companies
and a few real NIC activities, before trusting them in a big batch run."""
import json
import requests
from discover import yahoo_candidates, screener_candidates, HEADERS, get_with_retry

session = requests.Session()
out = {}

for label, query in [
    ("easy_tcs", "Tata Consultancy Services"),
    ("easy_apple", "Apple Inc"),
    ("activity_grain_milling", "Other grain milling and processing"),
    ("activity_iron_ore", "Underground mining of iron ore"),
    ("activity_millets", "Growing of Bajra and Jowar and other millets"),
]:
    out[label] = {
        "query": query,
        "yahoo": yahoo_candidates(session, query),
        "screener": screener_candidates(session, query),
    }

# raw Yahoo response for Apple, to check field shapes if anything looks off
r = get_with_retry(session, "https://query1.finance.yahoo.com/v1/finance/search", HEADERS, {
    "q": "Apple Inc", "quotesCount": 4, "newsCount": 0,
})
out["yahoo_raw_status"] = r.status_code if r else None
try:
    out["yahoo_raw_body"] = r.json() if r is not None else None
except ValueError:
    out["yahoo_raw_body"] = r.text[:500] if r is not None else None

r2 = get_with_retry(session, "https://www.screener.in/api/company/search/", HEADERS, {"q": "Tata Consultancy"})
out["screener_raw_status"] = r2.status_code if r2 else None
try:
    out["screener_raw_body"] = r2.json() if r2 is not None else None
except ValueError:
    out["screener_raw_body"] = r2.text[:500] if r2 is not None else None

with open("data/debug_new_sources.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(json.dumps(out, indent=2, ensure_ascii=False))
