"""One-off diagnostic: checks whether wiki_search()/wiki_infobox_ticker() in
discover.py actually find anything on real Wikipedia, for both an easy known
company and a genuinely-niche NIC activity. Writes results to a JSON file
since GitHub Actions run logs aren't readable from this session. Delete this
script (and its workflow) once the discovery pipeline is confirmed working.
"""
import json
import re
import requests
from discover import wiki_search, wiki_infobox_ticker, wiki_candidates, edgar_candidates, HEADERS

session = requests.Session()
out = {}

# Raw wikitext dump for a known case, to see exactly what traded_as looks
# like on a real page (TCS infobox parsing came back empty despite the
# search itself finding the right title).
r = session.get("https://en.wikipedia.org/w/api.php", headers=HEADERS, timeout=15, params={
    "action": "parse", "page": "Tata Consultancy Services", "prop": "wikitext", "section": 0, "format": "json",
})
wikitext = r.json().get("parse", {}).get("wikitext", {}).get("*", "") if r.status_code == 200 else f"<http {r.status_code}>"
out["tcs_raw_status"] = r.status_code
out["tcs_raw_wikitext_first_2000"] = wikitext[:2000]
m = re.search(r"traded_as", wikitext, re.I)
out["tcs_has_traded_as_literal"] = bool(m)
if m:
    out["tcs_traded_as_snippet"] = wikitext[m.start(): m.start() + 300]

for label, query in [
    ("easy_company_search", "Tata Consultancy Services"),
    ("easy_company_search2", "Apple Inc company"),
    ("niche_grapes", "Growing of grapes company"),
    ("niche_cotton", "Cotton ginning, cleaning and baling company"),
    ("niche_millets", "Growing of Bajra and Jowar and other millets company"),
]:
    titles = wiki_search(session, query)
    out[label] = {"query": query, "titles": titles, "infobox": {}}
    for t in titles:
        out[label]["infobox"][t] = wiki_infobox_ticker(session, t)

out["wiki_candidates_tcs"] = wiki_candidates(session, "Tata Consultancy Services")
out["wiki_candidates_millets"] = wiki_candidates(session, "Growing of Bajra and Jowar and other millets")
out["edgar_candidates_apple"] = edgar_candidates(session, "Apple Inc")
out["edgar_candidates_millets"] = edgar_candidates(session, "Growing of Bajra and Jowar and other millets")

with open("data/debug_wiki_test.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(json.dumps(out, indent=2, ensure_ascii=False))
