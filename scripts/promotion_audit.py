"""Inspect the public listing loader; no notifications or state writes."""
import re
import requests
url = "https://www.radiopopular.pt/includes/js/rp.js?v=202609091153"
r = requests.get(url, timeout=20)
print("STATUS", r.status_code)
r.raise_for_status()
for pattern in [r"ajax:\s*\{", r"getData:\s*function", r"convertFormToJSON:", r"loadProducts:"]:
    m = re.search(pattern, r.text)
    if m:
        print("SNIPPET", pattern, r.text[m.start():m.start()+4500])
