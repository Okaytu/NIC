"""Each module here implements one data source for company financials.
Every fetch_* function has the same contract:

    fetch_<source>(session, ident: dict) -> (data: dict | None, error: str | None)

`ident` is a data/companies.json entry: {"n", "tk", "ctry", "path"}.
`data`, when not None, is a subset of the canonical field names used
throughout this pipeline: cur, rev, ebitda, ni, ebm, npm, roce, roe,
netcash, pe, ev, mc. Missing fields are simply omitted (not set to None) --
scripts/scrape.py merges sources field-by-field, first non-missing wins
in source-priority order, so a source only needs to return what it
actually found.
"""
