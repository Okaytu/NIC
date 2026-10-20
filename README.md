# NIC Business → Listed Company Map

For every business activity in India's NIC 2025 classification, this maps up to 5
real listed companies (India first, then abroad if none is listed in India) with
margins, EBITDA, ROCE, ROE, leverage and valuation. Rendered as one static page
published with GitHub Pages — see **Settings → Pages** for the live URL.

## Why this exists

Doing the research by asking an AI assistant to fetch every company's financials
one page at a time is slow and burns a lot of per-call cost. The fetching itself
needs no judgment — it is "open this URL, read this table" — so it belongs in a
plain script running on a schedule, for free, in GitHub Actions. The part that
genuinely needs judgment — *which* companies are the right fit for *which*
business activity, and whether a number looks wrong enough to flag — stays a
one-time research task done by hand (or by an assistant) and recorded in the
`data/map_*.json` files below.

## How it fits together

```
data/NIC_2025_Business_Master.csv   the business list (never auto-edited)
data/map_<SECTION>.json             business code -> company ids, notes, flags  (hand-maintained)
data/companies.json                 company id -> {name, ticker, country, stockanalysis.com path} (hand-maintained)
data/financials.json                company id -> scraped numbers + fetched_at   (auto-refreshed)
scripts/scrape.py                   fetches stockanalysis.com/<path>/statistics/ for every company, fills financials.json
scripts/gen_all.py                  CSV + map_*.json + companies.json + financials.json -> site/data_<S>.js
scripts/build_site.py               site/template.html + site/data_*.js -> site/index.html  (what Pages serves)
.github/workflows/refresh.yml       runs scrape.py -> gen_all.py -> build_site.py on a schedule, commits if changed
```

Nothing above needs an AI assistant at run time. The only things that need a
human (or an assistant, once) are the contents of `data/map_*.json` and
`data/companies.json` — deciding which companies belong where.

## Adding or fixing a company

1. **New company for an existing business**: add it to `data/companies.json`
   (`id`, `n` name, `tk` ticker-as-displayed, `ctry` country, `path` — the part
   of the stockanalysis.com URL between the domain and `/statistics/`, e.g.
   `quote/nse/TCS` or `stocks/aapl`), then add its `id` to the right NIC code's
   list in `data/map_<SECTION>.json` under `"biz"`. Leave `data/financials.json`
   alone — the next scheduled run fills it in (or trigger the workflow by hand
   for an immediate fetch, see below).
2. **A company id must never appear under more than one NIC business code
   anywhere in the whole repo** — that's the one hard rule this project is
   built around. `scripts/gen_all.py` raises an error if the same id is used
   twice inside one section; there's no automatic check *across* sections yet,
   so when adding a company, grep `data/map_*.json` for its id first.
3. **A business with no listed company**: leave its code out of `"biz"` and,
   optionally, add a one-line reason to `"bnote"` in that section's map file.
4. After any `data/` edit, regenerate locally to check it before pushing:
   ```
   python3 scripts/gen_all.py && python3 scripts/build_site.py
   ```

## Running the scraper by hand

```
pip install requests beautifulsoup4
python3 scripts/scrape.py --limit 20          # small test batch first
python3 scripts/scrape.py --only tcs,infy     # just these ids
python3 scripts/scrape.py                     # everything older than 6 days
python3 scripts/scrape.py --force             # ignore the cache, refresh all ~1,500
```

A failed fetch (page blocked, field not found, network error) never deletes the
existing number — it's logged in that company's `error` field and the old value
stays until a later run succeeds.

## Triggering a refresh without waiting for the schedule

**GitHub → Actions → "Refresh company financials and rebuild site" → Run workflow.**
Leave the inputs blank for a normal run, or set a `limit` to test with a small
batch first.

## Known limitation

`scripts/scrape.py` was written from memory of the stockanalysis.com statistics
page layout and matched against it with flexible label patterns, but it has not
been run against the live site yet — this container's network can't reach it.
The **first real test is the first Actions run.** Check the run's log after
triggering it by hand; if several companies come back `FAIL ... no tables
found` or similar, the page structure likely differs from what the patterns in
`FIELD_PATTERNS` (top of `scrape.py`) expect, and those patterns need a quick
adjustment against the actual HTML.
