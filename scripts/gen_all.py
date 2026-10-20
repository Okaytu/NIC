"""Generate site/data_<S>.js for every section from:
  data/NIC_2025_Business_Master.csv  (business list, never touched by automation)
  data/map_<S>.json                  (business -> company-id mapping, hand-maintained)
  data/companies.json                (company identity: name/ticker/country/path, hand-maintained)
  data/financials.json               (scraped numbers, refreshed by scripts/scrape.py)

This replaces the old build/gen.py + raw_<S>.txt pair: identity and financials are
now shared across all sections in two files instead of being duplicated per section,
so a company's id is globally unique and a scrape failure never loses the name/ticker.
"""
import csv, glob, json, os, re, sys

H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(H, "data", "NIC_2025_Business_Master.csv")
DIV = {"01":"Crop and animal production","02":"Forestry and logging","03":"Fishing and aquaculture","05":"Coal mining","06":"Crude oil and natural gas","07":"Metal ore mining","08":"Other mining and quarrying","09":"Mining support services","10":"Food products","11":"Beverages","12":"Tobacco products","13":"Textiles","14":"Wearing apparel","15":"Leather and footwear","16":"Wood products","17":"Paper and paper products","18":"Printing and recorded media","19":"Coke and refined petroleum","20":"Chemicals","21":"Pharmaceuticals","22":"Rubber and plastics","23":"Non-metallic mineral products","24":"Basic metals","25":"Fabricated metal products","26":"Computer, electronic and optical products","27":"Electrical equipment","28":"Machinery and equipment","29":"Motor vehicles","30":"Other transport equipment","31":"Furniture","32":"Other manufacturing","33":"Repair and installation of machinery","35":"Electricity, gas and steam","36":"Water collection and supply","37":"Sewerage","38":"Waste collection and recycling","39":"Remediation","41":"Construction of buildings","42":"Civil engineering","43":"Specialised construction","46":"Wholesale trade","47":"Retail trade","49":"Land transport","50":"Water transport","51":"Air transport","52":"Warehousing and transport support","53":"Postal and courier","55":"Accommodation","56":"Food and beverage service","58":"Publishing","59":"Film, video, TV and sound","60":"Broadcasting and content distribution","61":"Telecommunications","62":"Computer programming and consultancy","63":"Computing infrastructure and information services","64":"Financial services","65":"Insurance and pensions","66":"Auxiliary financial services","68":"Real estate","69":"Legal and accounting","70":"Head offices and management consultancy","71":"Architecture, engineering and testing","72":"Scientific research","73":"Advertising and market research","74":"Other professional and technical","75":"Veterinary","77":"Rental and leasing","78":"Employment activities","79":"Travel agencies and tour operators","80":"Security and investigation","81":"Building services and landscaping","82":"Office and business support","84":"Public administration and defence","85":"Education","86":"Human health","87":"Residential care","88":"Social work without accommodation","90":"Creative and performing arts","91":"Libraries, museums and heritage","92":"Gambling and betting","93":"Sports, amusement and recreation","94":"Membership organisations","95":"Repair of computers and household goods","96":"Other personal services","97":"Households as employers","98":"Household production for own use","99":"Extraterritorial organisations"}
NONE = "No listed company found, in India or abroad, that runs this as a main business."


def short(s):
    s = s.replace("Group Class Sub-Class Description", "").strip()
    s = re.sub(r"\s+", " ", s)
    t = re.sub(r"\s*\([^)]*\)", "", s).strip()
    if len(t) > 90:
        cut = t[:90]
        t = cut[:cut.rfind(" ")].rstrip(",;") + "…"
    return t[0].upper() + t[1:], s


def r2(v, d=1):
    return None if v is None else round(v, d)


def build_company(cid, ident, fin):
    rev, ebitda, ni = fin.get("rev"), fin.get("ebitda"), fin.get("ni")
    ebm, npm = fin.get("ebm"), fin.get("npm")
    if ebm is None and rev and ebitda is not None:
        ebm = ebitda / rev * 100
    if npm is None and rev and ni is not None:
        npm = ni / rev * 100
    netcash, roce, roe = fin.get("netcash"), fin.get("roce"), fin.get("roe")
    pe, ev, mc = fin.get("pe"), fin.get("ev"), fin.get("mc")
    nd = (-netcash / ebitda) if (netcash is not None and ebitda and ebitda > 0) else None
    if ebitda is not None and ebitda <= 0:
        ev = None
    if ni is not None and ni <= 0:
        pe = None
    out = {
        "n": ident["n"], "tk": ident["tk"], "ctry": ident["ctry"], "cur": fin.get("cur"), "p": "TTM",
        "u": f"https://stockanalysis.com/{ident['path']}/statistics/",
        "rev": r2(rev, 3), "g": None, "eb": r2(ebm), "np": r2(npm), "roce": r2(roce), "roe": r2(roe),
        "nd": r2(nd, 2), "pe": r2(pe), "ev": r2(ev), "mc": r2(mc, 3),
    }
    return out


def main(S, companies, financials):
    rows = [r for r in csv.DictReader(open(CSV, encoding="utf-8-sig")) if r["Section"] == S]
    mpath = os.path.join(H, "data", f"map_{S}.json")
    m = json.load(open(mpath, encoding="utf-8"))

    co = {}
    used = set()
    biz, groups = [], {}
    for r in rows:
        code = r["NIC Code"]
        d = code[:2]
        groups.setdefault(d, DIV.get(d, "Division " + d))
        ids = m["biz"].get(code, [])
        for i in ids:
            if i not in companies:
                raise SystemExit(f"{S}/{code}: unknown company id {i} (not in data/companies.json)")
            if i in used:
                raise SystemExit(f"{S}/{code}: company {i} used twice within section {S}")
            used.add(i)
            if i not in co:
                co[i] = build_company(i, companies[i], financials.get(i, {}))
                flag = m.get("flags", {}).get(i)
                if flag:
                    co[i]["f"] = flag
        nm, full = short(r["Business Activity"])
        done = m.get("done")
        pending = done is not None and d not in done
        note = m.get("bnote", {}).get(code, "" if ids else ("Queued: this division has not been researched yet." if pending else NONE))
        biz.append([code, nm, d, r["B2B / B2C / Both"], m.get("bflag", {}).get(code, ""), ids, note, full])

    out = "(function(){\nObject.assign(COMPANIES," + json.dumps(co, ensure_ascii=False) + ");\n"
    out += f"SECTIONS.{S}=" + json.dumps({
        "name": m["name"], "range": m["range"], "groups": groups, "businesses": biz,
        "bench": [], "notes": m.get("notes", []),
    }, ensure_ascii=False) + ";\n})();\n"
    open(os.path.join(H, "site", f"data_{S}.js"), "w", encoding="utf-8").write(out)

    cov = sum(1 for b in biz if b[5])
    full5 = sum(1 for b in biz if len(b[5]) >= 5)
    india = sum(1 for i in used if co[i]["ctry"] == "India")
    return len(biz), cov, full5, len(used), india


if __name__ == "__main__":
    companies = json.load(open(os.path.join(H, "data", "companies.json"), encoding="utf-8"))
    financials = json.load(open(os.path.join(H, "data", "financials.json"), encoding="utf-8"))
    sections = sys.argv[1:] or [os.path.basename(p)[4] for p in sorted(glob.glob(os.path.join(H, "data", "map_*.json")))]
    used_globally = set()
    for S in sections:
        n, cov, full5, nused, india = main(S, companies, financials)
        print(f"{S}: {n} businesses, {cov} covered, {full5} full, {nused} companies ({india} India, {nused-india} abroad)")
