"""
find_no_links.py
Finds entities that appear in geodata.js but have no entry in refs.json,
meaning their popups will show no links at all.
"""

import json, re

GEODATA_JS = r'C:\my stuff\claudetest\mapper\js\geodata.js'
REFS_JSON  = r'C:\my stuff\claudetest\mapper\refs.json'

with open(REFS_JSON, encoding='utf-8') as f:
    refs = json.load(f)

with open(GEODATA_JS, encoding='utf-8') as f:
    text = f.read()

# Extract all entity keys from geodata.js
keys = re.findall(r"'((?:[^'\\]|\\.)*)'\s*:", text)
keys = [k.replace("\\'", "'") for k in keys]
keys = list(dict.fromkeys(keys))  # deduplicate, preserve order

no_links = [k for k in keys if k not in refs]

print(f'Total geodata entities:      {len(keys)}')
print(f'Entities with refs:          {len(keys) - len(no_links)}')
print(f'Entities with NO links:      {len(no_links)}')
print()
for k in sorted(no_links):
    print(f'  {k}')
