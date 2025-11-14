# src/debug_extract.py
from bs4 import BeautifulSoup
from pathlib import Path

p = Path(__file__).parent / "page.html"
html = p.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")

# Print h1 and following 40 lines of the file around where <h1> appears:
h1 = soup.find("h1")
if h1:
    print("=== H1 AREA (HTML) ===")
    el = h1
    # print the element and next siblings up to some text length
    print(el.prettify())
    # also print 40 lines from the raw file around the position for context
    raw = html
    idx = raw.find("<h1")
    start = max(0, idx - 400)
    end = min(len(raw), idx + 2000)
    excerpt = raw[start:end]
    print("\n=== RAW CONTEXT AROUND <h1> (for exact lines) ===\n")
    print(excerpt)

# Search for 'Born' lines
print("\n\n=== LINES CONTAINING 'Born' ===")
for ln in html.splitlines():
    if "Born" in ln or "born" in ln:
        print(ln)

print("\n\n=== LINES CONTAINING 'Foot' or 'Footedness' ===")
for ln in html.splitlines():
    if "Foot" in ln or "foot" in ln or "Footedness" in ln or "footedness" in ln:
        print(ln)
