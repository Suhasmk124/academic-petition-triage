
from pathlib import Path
import fitz
import json

PDF_PATH = Path("data/raw/UG-HandBook-25-26.pdf")
OUTPUT_DIR = Path("data/processed")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not PDF_PATH.exists():
    raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

doc = fitz.open(PDF_PATH)
pages = []
full_text = []

for page_number, page in enumerate(doc, start=1):
    text = page.get_text("text")
    pages.append({
        "page": page_number,
        "text": text
    })
    full_text.append(f"\n--- PAGE {page_number} ---\n{text}")

text_output = OUTPUT_DIR / "handbook_text.txt"
json_output = OUTPUT_DIR / "handbook_pages.json"

text_output.write_text(
    "\n".join(full_text),
    encoding="utf-8"
)

json_output.write_text(
    json.dumps(pages, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"PDF: {PDF_PATH}")
print(f"Pages extracted: {len(doc)}")
print(f"Text file: {text_output}")
print(f"Page-wise JSON: {json_output}")

keywords = [
    "attendance",
    "condonation",
    "medical",
    "absence",
    "examination",
    "committee"
]

print("\n--- KEYWORD SEARCH ---")

for keyword in keywords:
    matches = []

    for item in pages:
        if keyword.lower() in item["text"].lower():
            matches.append(item["page"])

    print(f"{keyword}: pages {matches[:30]}")
