# NIC Business → Listed Company Map

For every business activity in India's NIC 2025 classification, this maps up to 5
real listed companies (India first, then abroad if none is listed in India) with
margins, EBITDA, ROCE, ROE, leverage and valuation. Rendered as one static page
published with GitHub Pages — see **Settings → Pages** for the live URL.

## Why this exists

Doing the research by asking an AI assistant to fetch every company's financials
one page at a time, or to search the web for which company fits which business,
is slow and burns a lot of per-call cost. Neither of those tasks actually needs
judgment once the system knows what to look for — "open this URL, read this
table" and "search a few structured sources, verify what you find" are both
things a plain script can do, for free, on a schedule, in GitHub Actions. The
part that still genuinely needs judgment — curating the research, and reviewing
the handful of things the scripts couldn't verify on their own — stays recorded
in plain files for a human (or an assistant, occasionally) to look at.

## How it fits together

```
data/NIC_2025_Business_Master.csv   the business list (never auto-edited)
data/map_<SECTION>.json             business code -> company ids, notes, flags  (hand-maintained + auto-discovered)
data/companies.json                 company id -> {name, ticker, country, stockanalysis.com path} (hand-maintained + auto-discovered)
data/financials.json                company id -> numbers + fetched_at + which source(s) supplied them  (auto-refreshed)
data/discovery_queue.json           candidates discover.py found but could NOT verify -- needs a human look
data/broken_links.json              companies whose source URL is currently returning an error

scripts/sources/finnhub.py          financials source 1 (needs FINNHUB_API_KEY secret): structured JSON API
scripts/sources/stockanalysis.py    financials source 2: scrapes stockanalysis.com/<path>/statistics/
scripts/sources/screener.py         financials source 3, India only: scrapes screener.in as a last resort
scripts/scrape.py                   tries the 3 sources above in order per company, merges field-by-field
scripts/precheck.py                 fast daily check: is every company's URL still resolving? (no scraping)
scripts/discover.py                 for NIC codes with 0 companies: Wikipedia + SEC EDGAR candidates,
                                     verified by an actual stockanalysis.com fetch before being trusted
scripts/gen_all.py                  CSV + map_*.json + companies.json + financials.json -> site/data_<S>.js
scripts/build_site.py               site/template.html + site/data_*.js -> site/index.html  (what Pages serves)

.github/workflows/refresh.yml       weekly: scrape.py -> gen_all.py -> build_site.py, commits if changed
.github/workflows/precheck.yml      daily: precheck.py, commits data/broken_links.json if changed
.github/workflows/discover.yml      twice monthly: discover.py -> gen_all.py -> build_site.py, commits if changed
.github/workflows/pages.yml         deploys site/ to Pages; chained off the other three via workflow_run
                                     (a push made with the default GITHUB_TOKEN can't trigger other
                                     workflows directly -- GitHub's own anti-loop rule -- so this listens
                                     for those workflows' completion instead of a plain push)
```

Nothing above needs an AI assistant at run time.

## The one hard rule

**A company id must never be used under more than one NIC business code,
anywhere in the whole repo.** `gen_all.py` only checks this within one section;
`discover.py` checks it globally before adding anything new. When hand-editing
`data/map_*.json`, grep every `map_*.json` for the id first.

## Financials: multi-source, with real numbers behind the fallback order

Source priority per company: **Finnhub → stockanalysis.com → screener.in**
(screener.in only for India-listed companies). Each source only needs to
answer with *some* of the needed fields — `scrape.py` merges whatever each
source found, field by field, and records which source(s) actually
contributed in `financials.json`'s `"sources"` list. A company only shows up
as failed if every source came back empty.

**Status as verified by an actual run against the live sites** (2026-10-20):
stockanalysis.com succeeded for 1,510 of 1,516 companies in one pass; the other
6 turned out to be a path bug (fixed), a wrong ticker (fixed), one company
whose primary listing has genuinely moved (fixed), and two whose pages loaded
fine on re-check (likely transient — the next scheduled run will pick them up).
**Not yet verified live:** Finnhub (needs the `FINNHUB_API_KEY` secret added
first — see below) and screener.in (only gets exercised when stockanalysis.com
fails for an India company, which is rare). Check a run's log for
`FAIL ... screener.in:` or unusually empty Finnhub fields and fix the matching
pattern table in that source's file — same process that found and fixed the
`rev` field bug in stockanalysis.py's first live run.

### Enabling Finnhub

1. Free account: https://finnhub.io/register (no card required)
2. GitHub → **Settings → Secrets and variables → Actions → New repository secret**
   → name `FINNHUB_API_KEY`, value your key.
3. Nothing else to do — `refresh.yml` already passes it through, and
   `scrape.py` simply skips Finnhub (falls straight to stockanalysis.com) when
   the secret isn't set.

Honest limitation: Finnhub's free tier is strongest for US-listed tickers;
treat it as "try first, keep whatever it returns" rather than a full
replacement for the scrapers.

## Company discovery (filling the 0/5 gaps)

Many NIC codes genuinely have **no listed company anywhere** — a granular
activity like "growing of bajra and jowar" is done by private, diversified
agribusinesses virtually everywhere, so no scraper or search, however broad,
will ever find a public company for it. `discover.py` does not try to force a
match in that case; it leaves the code unfilled, same as the hand-researched
sections always have for activities with no real listed match.

What it does do, for a batch of currently-empty NIC codes each run:
1. Search **Wikipedia** for the activity, batch-fetch the search hits'
   infobox wikitext in one request, and pull a ticker out of the `traded_as`
   field — both the `{{NSE|TCS}}` template style and the plain-text
   `Nasdaq: PLUG` style real infoboxes actually use.
2. Search **SEC EDGAR's full-text index** (10-K filings mentioning the
   activity) and resolve a name to a ticker via SEC's own official ticker list.
3. **Verify** every candidate by actually fetching its stockanalysis.com page
   — a name mention alone is never enough to trust.
4. A candidate that verifies (the page is real and returns numbers) is
   auto-added straight into `map_<S>.json` and `companies.json`, up to 5 per
   code. A candidate that's *found* but doesn't verify goes into
   `data/discovery_queue.json` for a quick manual look instead of being merged.

Deliberately left out of v1: general web search (DuckDuckGo/etc.) as a further
fallback. Wikipedia and EDGAR are precise enough to auto-verify against; a bare
web search returns enough noise that it would need a human reviewing every
hit anyway, which defeats the point of automating this. If the two structured
sources keep coming up empty for codes that plausibly *do* have a listed
company, that's the natural next thing to add.

**Verified live** (2026-10-21): the first live runs came back with zero
candidates everywhere, which turned out to be two real bugs rather than
"no company exists" for every code tested — both confirmed and fixed by
checking actual Wikipedia/EDGAR responses:
- Every Wikipedia API call was getting HTTP 429'd, immediately, from
  GitHub's shared runner IP range; a spoofed browser User-Agent plus
  several delay-free per-title requests is exactly the pattern anonymous-
  abuse throttling targets. Fixed with a plain tool/contact User-Agent,
  retry-with-backoff (honors `Retry-After`) on every outbound call, and
  batching a search's hit titles into one request instead of one per title.
- EDGAR's `display_names` come back as `"Apple Inc.  (AAPL)  (CIK
  0000320193)"` — two trailing parenthetical annotations, not one — and the
  ticker-matching regex only stripped the `(CIK ...)` part, so the name
  never matched SEC's own ticker list and every real EDGAR hit got silently
  dropped. Fixed to strip all trailing `(...)` groups.

Re-tested after the fix directly against real pages: Wikipedia resolves
Tata Consultancy Services to NSE:TCS/BSE:532540 and Apple Inc. to
NASDAQ:AAPL; EDGAR resolves Apple Inc. to AAPL. Genuinely niche activities
(growing millets, growing grapes, cotton ginning) correctly come back with
*zero* candidates on both sources — which is the honest, correct result for
activities no listed company specializes in this narrowly, not a bug.

## Running things by hand

```
pip install requests beautifulsoup4

python3 scripts/scrape.py --limit 20          # small test batch first
python3 scripts/scrape.py --only tcs,infy     # just these ids
python3 scripts/scrape.py                     # everything older than 6 days
python3 scripts/scrape.py --force             # ignore the cache, refresh all ~1,500

python3 scripts/precheck.py                   # check every URL still resolves, no scraping

python3 scripts/discover.py --limit 20        # find & verify candidates for 20 empty codes
python3 scripts/discover.py --section Q --dry-run   # test without writing anything

python3 scripts/gen_all.py && python3 scripts/build_site.py   # rebuild the site locally
```

A failed fetch never deletes an existing number — it's logged in that
company's `error` field and the old value stays until a later run succeeds.

## Triggering a run without waiting for its schedule

**GitHub → Actions →** pick the workflow → **Run workflow.** All three
data-gathering workflows (`refresh`, `precheck`, `discover`) take an optional
`limit` input so you can test with a small batch before trusting a full run.
