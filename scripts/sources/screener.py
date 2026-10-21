"""Source 2 (India-only fallback): screener.in. Used only when
stockanalysis.com fails for an India-listed company -- screener.in is
scrape-friendly (plain server-rendered HTML, no login) and actually
computes ROCE natively for Indian companies, which is a real strength,
but its money figures are in Rs Crore, not Rs billion, so every money
field here is divided by 100 to match this pipeline's billions convention.
NOT YET LIVE-TESTED against the real site -- same caveat as every other
scraper in this repo: written from memory of the page layout, first real
test is the first Actions run that actually needs this fallback. Check
scripts/scrape.py's error log for `source=screener.in` failures.
"""
import re
from bs4 import BeautifulSoup

TIMEOUT = 20
CR_TO_BN = 0.01  # 1 Rs Crore = 1e7 INR = 0.01 Rs billion

RATIO_PATTERNS = {
    "mc":  [r"market\s*cap"],
    "pe":  [r"stock\s*p\s*/\s*e", r"\bp\s*/\s*e\b"],
    "roce": [r"\broce\b"],
    "roe":  [r"\broe\b"],
}


def _num(text):
    if text is None:
        return None
    t = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not t or t in ("-", "."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _ratio_card(soup):
    """The top 'ratios' box: <li class="..."><span class="name">X</span>
    <span class="...number...">Y</span></li> pairs."""
    out = {}
    for li in soup.select("li"):
        name_el = li.select_one(".name")
        if not name_el:
            continue
        num_els = li.select(".number")
        if not num_els:
            continue
        label = name_el.get_text(" ", strip=True)
        value = num_els[0].get_text(" ", strip=True)
        if label and label not in out:
            out[label] = value
    return out


def _latest_column(table):
    """Most screener.in tables are one row per line item, one column per
    period, most recent period last. Return {row_label: last_cell_text}."""
    out = {}
    if table is None:
        return out
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        value = cells[-1].get_text(" ", strip=True)
        if label:
            out[label] = value
    return out


def fetch(session, ident, headers, max_retries=2, sleep_fn=None):
    import time
    if ident.get("ctry") != "India":
        return None, "screener.in is India-only"
    symbol = ident["path"].rsplit("/", 1)[-1]
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 404:
                # some companies only have standalone, not consolidated, financials
                r = session.get(f"https://www.screener.in/company/{symbol}/", headers=headers, timeout=TIMEOUT)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                if sleep_fn:
                    sleep_fn(2 * attempt)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            ratios = _ratio_card(soup)
            out = {"cur": "INR"}
            for field, patterns in RATIO_PATTERNS.items():
                for pat in patterns:
                    rx = re.compile(pat, re.I)
                    hit = next((v for k, v in ratios.items() if rx.search(k)), None)
                    if hit is not None:
                        v = _num(hit)
                        if v is not None:
                            out[field] = v * CR_TO_BN if field in ("mc",) else v
                            break

            # Profit & Loss table: Sales / Operating Profit / OPM % / Net Profit
            pl_table = None
            for section in soup.select("section"):
                if section.get("id") == "profit-loss":
                    pl_table = section.find("table")
                    break
            pl = _latest_column(pl_table)
            if "Sales" in pl:
                v = _num(pl["Sales"])
                if v is not None:
                    out["rev"] = v * CR_TO_BN
            if "Net Profit" in pl:
                v = _num(pl["Net Profit"])
                if v is not None:
                    out["ni"] = v * CR_TO_BN
            if "OPM %" in pl:
                v = _num(pl["OPM %"])
                if v is not None:
                    out["ebm"] = v
            if out.get("rev") and "OPM %" in pl:
                opm = _num(pl["OPM %"])
                if opm is not None:
                    out["ebitda"] = out["rev"] * opm / 100
            if out.get("rev") and out.get("ni") is not None:
                out["npm"] = out["ni"] / out["rev"] * 100 if out["rev"] else None

            if len(out) <= 1:  # only "cur" -- nothing useful found
                last_err = "ratio card / P&L table not found (page layout may differ)"
                if sleep_fn:
                    sleep_fn(2 * attempt)
                continue
            return out, None
        except Exception as e:
            last_err = str(e)
            if sleep_fn:
                sleep_fn(2 * attempt)
    return None, last_err or "unknown error"
