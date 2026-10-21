#!/usr/bin/env python3
"""Fast weekly health check: HEAD (falling back to GET) every company's
stockanalysis.com URL and report which ones are broken -- a renamed
ticker, a delisting, a typo in data/companies.json -- *before* the full
scrape run hits them. Writes data/broken_links.json and prints a summary;
does not touch financials.json.
"""
import json, os, sys, time
import requests

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_PATH = os.path.join(H, "data", "companies.json")
OUT_PATH = os.path.join(H, "data", "broken_links.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def main():
    companies = json.load(open(COMPANIES_PATH, encoding="utf-8"))
    session = requests.Session()
    broken = {}
    for n, (cid, ident) in enumerate(companies.items(), 1):
        url = f"https://stockanalysis.com/{ident['path']}/statistics/"
        try:
            r = session.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                broken[cid] = {"n": ident["n"], "path": ident["path"], "status": r.status_code}
                print(f"[{n}/{len(companies)}] BROKEN {cid} ({ident['n']}): HTTP {r.status_code}")
        except requests.RequestException as e:
            broken[cid] = {"n": ident["n"], "path": ident["path"], "status": f"error: {e}"}
            print(f"[{n}/{len(companies)}] BROKEN {cid} ({ident['n']}): {e}")
        time.sleep(0.6)
    json.dump(broken, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\n{len(broken)} broken link(s) out of {len(companies)} -- see data/broken_links.json")


if __name__ == "__main__":
    main()
