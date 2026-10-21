"""One-off: why does EDGAR's quoted full-text search for "Manufacture of gur"
keep matching Celanese Corporation, a specialty-chemicals company with no
connection to jaggery (gur)? Dumps the raw search response."""
import json
import requests
from discover import SEC_HEADERS, get_with_retry

session = requests.Session()
out = {}

for q in ['"Manufacture of gur"', "gur", '"gur"']:
    r = get_with_retry(session, "https://efts.sec.gov/LATEST/search-index", SEC_HEADERS, {
        "q": q, "forms": "10-K",
    })
    entry = {"status": r.status_code if r else None}
    if r is not None and r.status_code == 200:
        body = r.json()
        entry["total"] = body.get("hits", {}).get("total")
        entry["hits"] = [
            {"display_names": h.get("_source", {}).get("display_names"),
             "score": h.get("_score")}
            for h in body.get("hits", {}).get("hits", [])[:5]
        ]
    out[q] = entry

with open("data/debug_edgar_gur.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(json.dumps(out, indent=2, ensure_ascii=False))
