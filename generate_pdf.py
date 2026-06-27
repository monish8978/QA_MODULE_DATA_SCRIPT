import urllib.request
import urllib.parse
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    with open(os.path.join(SCRIPT_DIR, "QA_Module_Documentation.md"), "r", encoding="utf-8") as f:
        md_content = f.read()
except Exception as e:
    print(f"Error reading Markdown: {e}")
    sys.exit(1)

print("Converting Markdown to PDF via API...")
url = "https://md-to-pdf.fly.dev/"
data = urllib.parse.urlencode({"markdown": md_content}).encode("utf-8")

req = urllib.request.Request(url, data=data)
try:
    with urllib.request.urlopen(req) as response:
        pdf_bytes = response.read()
        
    with open(os.path.join(SCRIPT_DIR, "QA_Module_Documentation.pdf"), "wb") as f:
        f.write(pdf_bytes)
    print("Successfully generated QA_Module_Documentation.pdf")
except Exception as e:
    print(f"Error generating PDF: {e}")
    print("Please use VS Code 'Markdown PDF' extension instead.")
