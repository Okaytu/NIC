"""One-time migration: split the old raw_<S>.txt snapshot files (id|ticker|country|
path|name|currency|rev|ebitda|ni|ebm|npm|roce|roe|netcash|pe|evebitda|mcap) into two
durable files:
  data/companies.json  -- identity only, rarely changes, hand-maintained
  data/financials.json -- scraped numbers, refreshed by scripts/scrape.py
Run once against the old build/ directory, then build/ is no longer needed.
"""
import glob, json, os, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "../../build"
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root

def num(x):
    x = x.strip()
    if x in ("", "NA", "N/A", "-"):
        return None
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return None

companies = {}
financials = {}

for path in sorted(glob.glob(os.path.join(SRC, "raw_*.txt"))):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split("|")
        if len(p) < 17:
            print("SKIP bad line in", path, ":", line)
            continue
        i, tk, ctry, cpath, name, cur = p[0], p[1], p[2], p[3], p[4], p[5]
        rev, ebitda, ni, ebm, npm, roce, roe, nc, pe, ev, mc = [num(v) for v in p[6:17]]
        companies[i] = {"n": name, "tk": tk, "ctry": ctry, "path": cpath}
        financials[i] = {
            "cur": cur, "rev": rev, "ebitda": ebitda, "ni": ni,
            "ebm": ebm, "npm": npm, "roce": roce, "roe": roe,
            "netcash": nc, "pe": pe, "ev": ev, "mc": mc,
            "fetched_at": None, "error": None,
        }

json.dump(companies, open(os.path.join(OUT, "data", "companies.json"), "w", encoding="utf-8"),
           ensure_ascii=False, indent=1, sort_keys=True)
json.dump(financials, open(os.path.join(OUT, "data", "financials.json"), "w", encoding="utf-8"),
           ensure_ascii=False, indent=1, sort_keys=True)
print(f"{len(companies)} companies written to data/companies.json and data/financials.json")
