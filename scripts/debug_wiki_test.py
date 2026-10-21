"""One-off diagnostic: checks whether discover.py's Wikipedia/EDGAR calls
actually find anything on the real sites from inside GitHub Actions. Writes
results to a JSON file since Actions run logs aren't readable from this
session. Delete this script (and its workflow) once the discovery pipeline
is confirmed working end to end.
"""
import json
import requests
from discover import wiki_search, wiki_fetch_wikitexts, wiki_infobox_ticker, wiki_candidates, edgar_candidates, HEADERS

session = requests.Session()
out = {}

for label, query in [
    ("easy_company", "Tata Consultancy Services"),
    ("easy_company2", "Apple Inc"),
    ("niche_grapes", "Growing of grapes"),
    ("niche_cotton", "Cotton ginning, cleaning and baling"),
    ("niche_millets", "Growing of Bajra and Jowar and other millets"),
]:
    titles = wiki_search(session, query)
    wikitexts = wiki_fetch_wikitexts(session, titles)
    out[label] = {
        "query": query,
        "titles": titles,
        "wikitext_lens": {t: len(wt) for t, wt in wikitexts.items()},
        "infobox": {t: wiki_infobox_ticker(wt) for t, wt in wikitexts.items()},
    }

out["wiki_candidates_tcs"] = wiki_candidates(session, "Tata Consultancy Services")
out["wiki_candidates_millets"] = wiki_candidates(session, "Growing of Bajra and Jowar and other millets")
out["edgar_candidates_apple"] = edgar_candidates(session, "Apple Inc")
out["edgar_candidates_millets"] = edgar_candidates(session, "Growing of Bajra and Jowar and other millets")

with open("data/debug_wiki_test.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(json.dumps(out, indent=2, ensure_ascii=False))
