"""Source 1 (primary for every non-US-mega-cap company): stockanalysis.com's
statistics page. Confirmed working in production -- a live GitHub Actions run
fetched 1,510/1,516 companies successfully from this source alone (the other
6 were genuine 404s: renamed/delisted tickers, a companies.json data problem,
not a scraper problem).
"""
import re
from bs4 import BeautifulSoup

TIMEOUT = 20

FIELD_PATTERNS = {
    "mc":      [r"market\s*cap"],
    "pe":      [r"\bpe\s*ratio\b", r"price\s*/?\s*earnings", r"p\s*/\s*e\b"],
    "ev":      [r"ev\s*/\s*ebitda"],
    "rev":     [r"^revenue\s*(\(|$)"],
    "ebitda":  [r"^ebitda\s*(\(|$)"],
    "ni":      [r"^net\s*income\s*(\(|$)", r"^earnings\s*(\(|$)"],
    "ebm":     [r"ebitda\s*margin"],
    "npm":     [r"profit\s*margin", r"net\s*margin"],
    "roe":     [r"return\s*on\s*equity", r"\broe\b"],
    "roce":    [r"return\s*on\s*capital\s*employed", r"\broce\b",
                r"return\s*on\s*invested\s*capital", r"\broic\b"],
    "netcash": [r"net\s*cash\s*\(?\s*debt\s*\)?", r"net\s*debt", r"net\s*cash\b"],
}


def parse_number(text):
    if text is None:
        return None
    t = text.strip().replace(",", "").replace("$", "").replace("%", "").replace("x", "")
    if t in ("", "-", "NaN", "n/a", "N/A", "NA", "--"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    mult = 1.0
    if t and t[-1] in "TBMK":
        mult = {"T": 1000.0, "B": 1.0, "M": 0.001, "K": 0.000001}[t[-1]]
        t = t[:-1]
    try:
        v = float(t) * mult
    except ValueError:
        return None
    return -v if neg else v


def extract_table_rows(soup):
    rows = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        value = cells[1].get_text(" ", strip=True)
        if label and label not in rows:
            rows[label] = value
    return rows


def match_field(rows, patterns):
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for label, value in rows.items():
            if rx.search(label):
                v = parse_number(value)
                if v is not None:
                    return v
    return None


def fetch(session, ident, headers, max_retries=3, sleep_fn=None):
    import time
    url = f"https://stockanalysis.com/{ident['path']}/statistics/"
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, headers=headers, timeout=TIMEOUT)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                if sleep_fn:
                    sleep_fn(2 * attempt)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.get_text() if soup.title else ""
            if "just a moment" in title.lower() or "attention required" in title.lower():
                last_err = "blocked (challenge page)"
                if sleep_fn:
                    sleep_fn(3 * attempt)
                continue
            rows = extract_table_rows(soup)
            if not rows:
                last_err = "no tables found on page"
                if sleep_fn:
                    sleep_fn(2 * attempt)
                continue
            out = {}
            for field, patterns in FIELD_PATTERNS.items():
                v = match_field(rows, patterns)
                if v is not None:
                    out[field] = v
            cur = None
            for label in rows:
                if "₹" in rows.get(label, ""):
                    cur = "INR"; break
                if "$" in rows.get(label, ""):
                    cur = "USD"; break
            if cur:
                out["cur"] = cur
            return out, None
        except Exception as e:
            last_err = str(e)
            if sleep_fn:
                sleep_fn(2 * attempt)
    return None, last_err or "unknown error"
