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

What it does do, for a batch of currently-empty NIC codes each run — four
sources, searched in parallel for every code:
1. **Wikipedia**: batch-fetch the search hits' infobox wikitext in one
   request, pull a ticker out of the `traded_as` field — both the
   `{{NSE|TCS}}` template style and the plain-text `Nasdaq: PLUG` style real
   infoboxes actually use.
2. **SEC EDGAR's full-text index** (10-K filings mentioning the activity),
   resolved to a ticker via SEC's own official ticker list, kept only above
   a minimum relevance score.
3. **Yahoo Finance's** own ticker/company search — globally broad (every
   major exchange), no API key, and unlike a Wikipedia search it only ever
   returns real tradeable securities.
4. **screener.in's** own company search — India-only, but this project is
   India-first and EDGAR is structurally blind to every non-US company, so
   this fills a real gap EDGAR can't.

Every candidate is then **verified** by actually fetching its
stockanalysis.com page — a name mention alone is never enough to trust.
**Nothing auto-merges, from any source**, including EDGAR — see the
incident below for why. Every verified candidate goes to
`data/discovery_queue.json` for a human look on `site/review.html`
instead, whatever source found it and however cleanly its ticker
verifies. The only way a company reaches `map_<S>.json` /
`companies.json` now is through human review (applying an approved
decision from `site/review.html`) or the manual add-a-company flow
below — never automatically.

Deliberately left out: a general-purpose web search API (Bing/Google/
DuckDuckGo). Even Yahoo's and screener.in's own search are narrower than
that — they only ever return real, named, tradeable securities, never an
arbitrary ranked web page — which keeps their false-positive shape closer
to "right company, wrong activity" (a human catches this in five seconds
on the review page) rather than "not a company at all."

Deliberately NOT auto-merging Wikipedia matches, even verified ones: see
below.

**Verified live** (2026-10-21), three real bugs found and fixed by actually
running this against live Wikipedia/EDGAR/stockanalysis.com and inspecting
the results, not just reading the code:

1. **Every Wikipedia API call was getting HTTP 429'd**, immediately, from
   GitHub's shared runner IP range — a spoofed browser User-Agent plus
   several delay-free per-title requests is exactly the pattern anonymous-
   abuse throttling targets, and the 429s were silently read as "nothing
   found." Fixed with a plain tool/contact User-Agent, retry-with-backoff
   (honors `Retry-After`) on every outbound call, and batching a search's
   hit titles into one request instead of one per title.
2. **EDGAR's `display_names`** come back as `"Apple Inc.  (AAPL)  (CIK
   0000320193)"` — two trailing parenthetical annotations, not one — and the
   ticker-matching regex only stripped the `(CIK ...)` part, so the name
   never matched SEC's own ticker list and every real EDGAR hit got silently
   dropped. Fixed to strip all trailing `(...)` groups.
3. **Ticker verification was never a relevance check**, only a check that
   the company exists and trades — and a real 300-code production run
   proved it: of 17 candidates that verified, 10 were real companies with
   nothing to do with the activity they got attached to (Amazon for
   "growing of apples", BP for "fish and marine mammal oils", Costco for
   "custom tailoring services", Hershey for "dairy products", and six more),
   every one of them Wikipedia-sourced. Wikipedia's ranked full-text search
   readily surfaces a thematically-adjacent page that just isn't the right
   company. Fixed by restricting auto-merge to EDGAR-sourced candidates only
   (see above); all 17 were reverted out of the live data and moved into the
   review queue. A related data-cleanliness bug fed into this: some
   `Business Activity` CSV cells carry a stray leading backtick or a
   trailing "Group Class Sub-Class Description" fragment left over from the
   source file's original layout (e.g. `` Manufacture of `gur `` ), which
   `clean_activity()` now strips before it reaches any search query.

**Second incident** (2026-10-21, same day, after the EDGAR-only policy
above had already been running cleanly for a while): a full run across
every remaining section produced 5 more auto-merges, and hand-checking
them found 4-5 wrong: Axcelis Technologies (semiconductor equipment)
matched "Auditing services", Akebia Therapeutics (biopharma) matched
"Packaging activities", Onity Group (mortgage servicing) matched
"Households", Xenetic Biosciences (biotech) matched "Rainwater
harvesting" — all boilerplate phrase coincidences (a risk factor, an
ESG disclosure, a customer description) with nothing to do with the
company's actual business, every one above `MIN_EDGAR_SCORE`. (Watts
Water Technologies also matched "Rainwater harvesting" and is
plausible — they do sell water-conservation products — but wasn't
confidently verified either, so it was demoted too rather than assumed
correct.) All 5 were reverted the same way as the first incident.
**Conclusion: a full-text relevance score, however high the threshold,
was never actually a business-relevance signal** — a 10-K is long
enough that almost any phrase scores "relevant" somewhere in it,
regardless of whether it describes what the company does. EDGAR's
auto-merge eligibility has been removed entirely; every source is
queue-only now (see above).

Re-tested after all three fixes: Wikipedia resolves Tata Consultancy
Services to NSE:TCS/BSE:532540 and Apple Inc. to NASDAQ:AAPL; EDGAR resolves
Apple Inc. to AAPL. Genuinely niche activities (growing millets, growing
grapes, cotton ginning) correctly come back with *zero* candidates on both
sources — the honest, correct result for activities no listed company
specializes in this narrowly, not a bug.

**Yahoo Finance and screener.in, verified live** (2026-10-21): both resolve
real companies correctly against known names (Yahoo: "Tata Consultancy
Services" → NSE:TCS and BSE:TCS; "Apple Inc" → NASDAQ:AAPL; screener.in:
"Tata Consultancy Services" → `/company/TCS/`, exactly the slug format
assumed). One real bug found and fixed: **Yahoo returns the same company
twice** whenever it's cross-listed — Apple Inc came back as both
NASDAQ:AAPL *and* a Toronto-listed CAD-hedged CDR of the same stock; TCS
came back as both its NSE and BSE listing. Left alone, that's two review-
queue cards for one real company. Fixed by deduplicating on
`(name, stripped ticker)`, keeping only the first (highest-ranked) listing.

More important finding from the same test, honestly reported rather than
glossed over: **both Yahoo and screener.in search by company name, not by
business description** — unlike EDGAR (full-text search over actual filing
content) or Wikipedia (full-text search over article content), a Yahoo or
screener.in query only ever matches when the activity phrase happens to
resemble a company's registered name. Live-tested against real NIC
activity text ("Other grain milling and processing", "Underground mining
of iron ore", "Growing of Bajra and Jowar and other millets") — all three
came back with *zero* candidates from both sources, correctly, because no
company is literally named after those activities. So these two sources
mainly help the minority of codes whose business activity *is* close to a
known company's name or sector term (which Wikipedia and EDGAR often also
already catch); they do not meaningfully widen coverage of the many
genuinely narrow/generic NIC activities that have no single matching
public company. That ceiling is structural, not something a better scraper
fixes — see the next section.

A general-purpose web search engine (DuckDuckGo, Bing) was considered as a
fifth source and deliberately left out, for a different reason than the
original Wikipedia-style false-positive risk: those return arbitrary web
pages, not structured company/ticker data, so turning a result into a
clean "this is company X, ticker Y" candidate needs real entity extraction
that a plain scraper can't do reliably — it would add noise to the review
queue rather than real candidates, for activities that structurally may
have no listed company anyway.

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
