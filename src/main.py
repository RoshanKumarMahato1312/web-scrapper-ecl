# src/main.py
import os
import csv
import json
import re
from datetime import datetime, date

# optional heavy import is delayed until used
try:
    import cloudscraper
except Exception:
    raise SystemExit("cloudscraper missing. Install with: pip install cloudscraper")

from bs4 import BeautifulSoup, Comment

# ---------------- CONFIG ----------------
URL = "https://fbref.com/en/players/dea698d9/Cristiano-Ronaldo"  # change this to any player page
THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "..", "data")
OUTPUT_CSV = os.path.join(DATA_DIR, "output.csv")
DEBUG_HTML = os.path.join(THIS_DIR, "page.html")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://google.com/"
}
# Toggle this to True to parse the existing page.html (skip fetching)
USE_EXISTING_PAGE_IF_PRESENT = False
# ----------------------------------------

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def save_debug(html):
    with open(DEBUG_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print("Saved debug HTML to:", DEBUG_HTML)

# ---------- Date helpers ----------
def try_parse_date(s):
    if not s:
        return None
    s = s.strip()
    # normalize few variants
    s = s.replace("\xa0", " ")
    # common formats
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %Y", "%b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    # month year like "June 2027"
    m = re.search(r'([A-Za-z]+)\s+(\d{4})', s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%B %Y").date()
        except Exception:
            try:
                return datetime.strptime(m.group(0), "%b %Y").date()
            except Exception:
                pass
    # yyyy-mm-dd anywhere
    m2 = re.search(r'(\d{4}-\d{2}-\d{2})', s)
    if m2:
        try:
            return datetime.strptime(m2.group(1), "%Y-%m-%d").date()
        except Exception:
            pass
    # dd Month yyyy or similar inside text
    m3 = re.search(r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', s)
    if m3:
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                return datetime.strptime(m3.group(1), fmt).date()
            except Exception:
                pass
    return None

def compute_age(birth_date):
    if not isinstance(birth_date, date):
        return None
    today = date.today()
    yrs = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return str(yrs)

# ---------- Fetch with cloudscraper (faster) ----------
def fetch_html_cloudscraper(url, attempts=3):
    import random, time
    from urllib.parse import urlparse

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    ]

    last_status = None
    last_text = None

    for attempt in range(1, attempts + 1):
        ua = random.choice(user_agents)
        headers_try = HEADERS.copy()
        headers_try["User-Agent"] = ua
        try:
            print(f"[cloudscraper] Attempt {attempt} with UA: {ua[:60]}...")
            scraper = cloudscraper.create_scraper(browser={'browser':'chrome','platform':'windows','mobile': False})
            scraper.headers.update(headers_try)
            r = scraper.get(url, timeout=20)
            last_status = getattr(r, "status_code", None)
            last_text = getattr(r, "text", "")
            print("[cloudscraper] Status:", last_status)
            if last_status == 200:
                save_debug(r.text)
                return r.text
            if last_status == 403:
                # try visiting site root for cookies then retry quickly
                parsed = urlparse(url)
                root = f"{parsed.scheme}://{parsed.netloc}/"
                try:
                    print("[cloudscraper] 403 -> visiting root to gather cookies...")
                    scraper.get(root, timeout=10)
                    time.sleep(0.5)
                    r2 = scraper.get(url, timeout=20)
                    last_status = getattr(r2, "status_code", None)
                    last_text = getattr(r2, "text", "")
                    print("[cloudscraper] after root visit status:", last_status)
                    if last_status == 200:
                        save_debug(r2.text)
                        return r2.text
                except Exception as e:
                    print("[cloudscraper] root visit failed:", e)
            time.sleep(0.5 * attempt)
        except Exception as e:
            print("[cloudscraper] attempt exception:", e)
            time.sleep(0.5 * attempt)
    # save last text for debugging
    if last_text:
        try:
            with open(DEBUG_HTML, "w", encoding="utf-8") as f:
                f.write(last_text)
            print("Saved last response to debug HTML:", DEBUG_HTML)
        except Exception:
            pass
    raise RuntimeError(f"cloudscraper failed; last status: {last_status}")

# ---------- Selenium fallback (fixed init, minimal wait) ----------
def fetch_html_selenium(url, headless=False, wait_seconds=4):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    import time

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1200,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    print("[selenium] Starting Chrome (real browser). If a CAPTCHA appears, solve it in the browser window.")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)

    try:
        driver.get(url)
        time.sleep(wait_seconds)
        html = driver.page_source
        save_debug(html)
        return html
    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ---------- Parsing helpers & extractors ----------
def extract_born_section(soup):
    born_tag = soup.find("strong", string=lambda s: s and "born" in s.lower())
    if not born_tag:
        return None, None
    date_span = born_tag.find_next("span")
    dob_raw = date_span.get_text(strip=True) if date_span else None
    bp_span = date_span.find_next("span") if date_span else None
    birthplace = None
    if bp_span:
        bp_txt = bp_span.get_text(strip=True)
        bp_txt = re.sub(r'^\s*in\s+', '', bp_txt, flags=re.I).strip()
        if bp_txt:
            birthplace = bp_txt
    parsed = try_parse_date(dob_raw)
    dob = parsed.isoformat() if parsed else dob_raw
    return dob, birthplace

def extract_preferred_foot(soup):
    foot_tag = soup.find("strong", string=lambda s: s and "foot" in s.lower())
    if foot_tag:
        parent_text = foot_tag.parent.get_text(" ", strip=True)
        m = re.search(r'Footed[:\s]*([A-Za-z\-]+)', parent_text, re.I)
        if m:
            return m.group(1).strip()
    txt_all = soup.get_text(" ", strip=True)
    m = re.search(r'(?:Preferred\s*Foot|Footed|Footedness|Foot)[:\s]+([A-Za-z\-]+)', txt_all, re.I)
    if m:
        return m.group(1).strip()
    return None

def extract_position(soup):
    pos_tag = soup.find("strong", string=lambda s: s and "position" in s.lower())
    if pos_tag:
        parent_text = pos_tag.parent.get_text(" ", strip=True)
        m = re.search(r'Position[:\s]*(.+?)(?:Foot|Footed|Footedness|$)', parent_text, re.I)
        if m:
            return m.group(1).strip().rstrip('▪').strip()
        return parent_text.replace("Position:", "").strip()
    return None

def parse_json_ld(soup):
    scripts = soup.find_all("script", type="application/ld+json")
    for s in scripts:
        try:
            data = json.loads(s.string)
        except Exception:
            continue
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    t = str(entry.get("@type","")).lower()
                    if "person" in t or "player" in t or "sports" in t:
                        return entry
        elif isinstance(data, dict):
            t = str(data.get("@type","")).lower()
            if "person" in t or "player" in t or "sports" in t:
                return data
    return None

def extract_label_values(fragment):
    LABEL_RE = re.compile(r'(born|birth|weight|height|nationalit|foot|position|place of birth|contract|debut|born:)', re.I)
    HEIGHT_RE = re.compile(r'(\d{2,3}\s?cm|\d\.\d+\s?m)', re.I)
    WEIGHT_RE = re.compile(r'(\d{2,3}\s?kg)', re.I)
    DOB_RE = re.compile(r'(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\w+\s+\d{4})')
    text = fragment.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = {}
    for ln in lines:
        if not LABEL_RE.search(ln):
            continue
        if ":" in ln:
            label, val = ln.split(":",1)
            label = label.strip().lower()
            val = val.strip()
        else:
            parts = ln.split(None,1)
            label = parts[0].strip().lower() if parts else ln
            val = parts[1].strip() if len(parts)>1 else ""
        if "born" in label:
            out["dob_raw"] = val
        if ("birth" in label and "place" in label) or "birthplace" in label:
            out["birthplace_raw"] = val
        if "height" in label:
            out["height_raw"] = val
        if "weight" in label:
            out["weight_raw"] = val
        if "nationalit" in label:
            out["nationality_raw"] = val
        if label.strip().startswith("position"):
            out["position_raw"] = val
        if "foot" in label:
            out["preferred_foot_raw"] = val
        if "contract" in label or "expires" in ln.lower():
            # capture the portion after label or the whole line
            out["contract_raw"] = val if val else ln
        if "debut" in label or "debut" in ln.lower():
            out["debut_raw"] = val if val else ln
    if "height_raw" not in out:
        hm = HEIGHT_RE.search(text)
        if hm:
            out["height_raw"] = hm.group(1)
    if "weight_raw" not in out:
        wm = WEIGHT_RE.search(text)
        if wm:
            out["weight_raw"] = wm.group(1)
    if "dob_raw" not in out:
        dm = DOB_RE.search(text)
        if dm:
            out["dob_raw"] = dm.group(1)
    nation = None
    for a in fragment.find_all("a"):
        txt = a.get_text(strip=True)
        href = a.get("href","")
        if txt and txt[0].isupper() and len(txt) < 60 and "players" not in href and "teams" not in href:
            nation = txt
            break
    if nation and "nationality_raw" not in out:
        out["nationality_raw"] = nation
    return out

def find_meta_fragment(soup):
    meta = soup.find(id="meta")
    if meta:
        return meta, "meta_id"
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        txt = comment.strip()
        if 'id="meta"' in txt or 'data-birth' in txt or 'itemprop' in txt or 'Born' in txt:
            frag = BeautifulSoup(txt, "lxml")
            return frag, "meta_in_comment"
    return None, None

# ---- new: extract contract and debut helpers ----
def extract_contract_from_fragment(fragment):
    # try to find phrases like "Expires June 2027" or "Contract until <date>"
    txt = fragment.get_text(" ", strip=True)
    # common patterns
    m = re.search(r'Expires\s+([A-Za-z0-9,\s\-]+?)(?:\.|Via|$)', txt, re.I)
    if m:
        candidate = m.group(1).strip()
        d = try_parse_date(candidate)
        return (d.isoformat() if d else candidate)
    m2 = re.search(r'Contract(?:\s+until|\s*[:])\s*([A-Za-z0-9,\s\-]+?)(?:\.|$)', txt, re.I)
    if m2:
        candidate = m2.group(1).strip()
        d = try_parse_date(candidate)
        return (d.isoformat() if d else candidate)
    # maybe line contains "Expires <month year>"
    m3 = re.search(r'(Expires\s+[A-Za-z]+\s+\d{4})', txt, re.I)
    if m3:
        candidate = m3.group(1).replace("Expires", "").strip()
        d = try_parse_date(candidate)
        return (d.isoformat() if d else candidate)
    return None

def extract_debut_from_fragment(fragment):
    # look for lines containing debut or "Senior debut" etc.
    txt = fragment.get_text("\n", strip=True)
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    for ln in lines:
        if re.search(r'\bdebut\b', ln, re.I):
            # try to extract a date from the line
            d = try_parse_date(ln)
            if d:
                return d.isoformat()
            # otherwise return cleaned snippet
            # remove leading label like "Debut:" or "Senior debut:"
            ln2 = re.sub(r'^[A-Za-z ]*debut[:\s\-]*', '', ln, flags=re.I).strip()
            return ln2
    # try a looser search in whole fragment
    m = re.search(r'(Debut[:\s]*[A-Za-z0-9,\s\-]+)', txt, re.I)
    if m:
        candidate = m.group(1).split(":",1)[-1].strip()
        d = try_parse_date(candidate)
        return (d.isoformat() if d else candidate)
    return None

# ---------- main extraction combining everything ----------
def extract_player(soup, meta_fragment):
    info = {
        "name": "Not Found",
        "dob": "Not Found",
        "age": "Not Found",
        "height": "Not Found",
        "weight": "Not Found",
        "nationality": "Not Found",
        "position": "Not Found",
        "preferred_foot": "Not Found",
        "birthplace": "Not Found",
        "debut": "Not Found",            # new
        "contract_until": "Not Found"    # new
    }

    h1 = soup.find("h1")
    if h1:
        info["name"] = h1.get_text(strip=True)

    jl = parse_json_ld(soup)
    if jl:
        if jl.get("birthDate"):
            info["dob"] = jl.get("birthDate")
            bd = try_parse_date(info["dob"])
            if bd:
                info["age"] = compute_age(bd)
        bp = jl.get("birthPlace")
        if isinstance(bp, dict):
            info["birthplace"] = bp.get("name") or info["birthplace"]
        elif isinstance(bp, str):
            info["birthplace"] = bp
        if jl.get("height"):
            info["height"] = normalize_quant_val(jl.get("height"))
        if jl.get("weight"):
            info["weight"] = normalize_quant_val(jl.get("weight"))
        if jl.get("nationality"):
            info["nationality"] = jl.get("nationality")
        if jl.get("roleName"):
            info["position"] = jl.get("roleName")

    # try parse meta fragment / comment fragment
    if meta_fragment is not None:
        candidates = extract_label_values(meta_fragment)
        # basic fields
        if candidates.get("dob_raw") and info["dob"] == "Not Found":
            dr = candidates["dob_raw"].strip()
            if dr and dr != ":":
                info["dob"] = dr
                bd = try_parse_date(dr)
                if bd:
                    info["age"] = compute_age(bd)
        if info["dob"] == "Not Found":
            dob_val, bp_val = extract_born_section(soup)
            if dob_val:
                info["dob"] = dob_val
                bd = try_parse_date(dob_val)
                if bd:
                    info["age"] = compute_age(bd)
            if bp_val and info["birthplace"] == "Not Found":
                info["birthplace"] = bp_val
        if candidates.get("birthplace_raw") and info["birthplace"] == "Not Found":
            if candidates["birthplace_raw"].strip() and candidates["birthplace_raw"].strip() != ":":
                info["birthplace"] = candidates["birthplace_raw"]
        if candidates.get("height_raw") and info["height"] == "Not Found":
            info["height"] = candidates["height_raw"]
        if candidates.get("weight_raw") and info["weight"] == "Not Found":
            info["weight"] = candidates["weight_raw"]
        if candidates.get("nationality_raw") and info["nationality"] == "Not Found":
            info["nationality"] = candidates["nationality_raw"]

        # NEW: contract and debut attempts from fragment
        cval = None
        if candidates.get("contract_raw"):
            cval = candidates.get("contract_raw")
        if not cval:
            cval = extract_contract_from_fragment(meta_fragment)
        if cval:
            info["contract_until"] = cval if isinstance(cval, str) else str(cval)

        dval = None
        if candidates.get("debut_raw"):
            dval = candidates.get("debut_raw")
        if not dval:
            dval = extract_debut_from_fragment(meta_fragment)
        if dval:
            info["debut"] = dval if isinstance(dval, str) else str(dval)

    # fallback scan of whole page text (if missing)
    whole_text = soup.get_text(" ", strip=True)
    if info["contract_until"] == "Not Found":
        # patterns across whole page
        m = re.search(r'Expires\s+([A-Za-z0-9,\s\-]+?)(?:\.|Via|$)', whole_text, re.I)
        if m:
            candidate = m.group(1).strip()
            d = try_parse_date(candidate)
            info["contract_until"] = d.isoformat() if d else candidate
        else:
            m2 = re.search(r'Contract(?:\s+until|\s*[:])\s*([A-Za-z0-9,\s\-]+?)(?:\.|$)', whole_text, re.I)
            if m2:
                candidate = m2.group(1).strip()
                d = try_parse_date(candidate)
                info["contract_until"] = d.isoformat() if d else candidate

    if info["debut"] == "Not Found":
        m = re.search(r'\bDebut[:\s\-]*([A-Za-z0-9,\s\-]+)', whole_text, re.I)
        if m:
            candidate = m.group(1).strip()
            d = try_parse_date(candidate)
            info["debut"] = d.isoformat() if d else candidate

    # other existing fallbacks for height, weight, nationality, birthplace
    if info["height"] == "Not Found":
        h = soup.find("span", {"itemprop":"height"})
        if h:
            info["height"] = h.get_text(strip=True)
    if info["weight"] == "Not Found":
        w = soup.find("span", {"itemprop":"weight"})
        if w:
            info["weight"] = w.get_text(strip=True)
    if info["nationality"] == "Not Found":
        n = soup.find("span", {"itemprop":"nationality"})
        if n:
            info["nationality"] = n.get_text(strip=True)
    if info["birthplace"] == "Not Found":
        bp = soup.find("span", {"itemprop":"birthPlace"})
        if bp:
            info["birthplace"] = bp.get_text(strip=True)

    pos = extract_position(soup)
    if pos:
        info["position"] = pos
    pf = extract_preferred_foot(soup)
    if pf:
        info["preferred_foot"] = pf

    if info["age"] == "Not Found" and info["dob"] not in (None, "Not Found"):
        parsed = try_parse_date(info["dob"])
        if parsed:
            info["age"] = compute_age(parsed)

    for k in ("height","weight"):
        v = info.get(k)
        if isinstance(v, dict):
            if "value" in v and isinstance(v["value"], str):
                info[k] = v["value"].strip()
            else:
                try:
                    info[k] = json.dumps(v, ensure_ascii=False)
                except Exception:
                    info[k] = str(v)

    for k in info:
        if isinstance(info[k], str):
            val = info[k].strip()
            if val == ":" or val == "":
                info[k] = "Not Found"
            else:
                info[k] = val

    return info

def normalize_quant_val(q):
    if not q:
        return None
    if isinstance(q, dict):
        if "value" in q and isinstance(q["value"], str) and q["value"].strip():
            return q["value"].strip()
        if "value" in q and ("unitText" in q or "unitCode" in q):
            v = str(q["value"])
            unit = q.get("unitText") or q.get("unitCode") or ""
            return f"{v} {unit}".strip()
    if isinstance(q, str):
        return q.strip()
    return None

def save_csv(row):
    ensure_data_dir()
    header = ["name","dob","age","height","weight","nationality","position","preferred_foot","birthplace","debut","contract_until","source_url"]
    write_header = not os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        w.writerow(row)
    print("Saved to:", OUTPUT_CSV)

def main():
    # If you already have a debug page saved and want to parse it without fetching,
    # set USE_EXISTING_PAGE_IF_PRESENT = True at the top of this file.
    html = None
    if USE_EXISTING_PAGE_IF_PRESENT and os.path.exists(DEBUG_HTML):
        print("Parsing existing page.html (skip fetch).")
        with open(DEBUG_HTML, "r", encoding="utf-8") as f:
            html = f.read()

    if not html:
        # try cloudscraper first
        try:
            html = fetch_html_cloudscraper(URL)
        except Exception as e:
            print("cloudscraper failed:", e)
            print("Falling back to Selenium (real browser). This will open Chrome on your machine.")
            html = fetch_html_selenium(URL, headless=False, wait_seconds=4)

    soup = BeautifulSoup(html, "lxml")
    meta_frag, method = find_meta_fragment(soup)
    print("Meta discovery method:", method)
    info = extract_player(soup, meta_frag)
    info["source_url"] = URL

    print("\nExtracted fields:")
    for k,v in info.items():
        print(f"{k}: {v}")

    save_csv(info)

if __name__ == "__main__":
    main()
