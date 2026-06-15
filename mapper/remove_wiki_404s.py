"""
remove_wiki_404s.py
Removes Wikipedia URLs that returned 404 from refs.json.
Leaves WHE URLs and any 200/429/error Wikipedia URLs untouched.
If removing a Wikipedia URL leaves an entry with no URLs at all, removes the entry.
"""

import json, csv

AUDIT_CSV = r'C:\my stuff\claudetest\mapper\wiki_link_audit.csv'
REFS_JSON = r'C:\my stuff\claudetest\mapper\refs.json'

dead_urls = set()
with open(AUDIT_CSV, newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row['Status'] == '404':
            dead_urls.add(row['URL'])

print(f'Confirmed 404 Wikipedia URLs to remove: {len(dead_urls)}')

with open(REFS_JSON, encoding='utf-8') as f:
    refs = json.load(f)

removed_urls    = 0
removed_entries = 0
updated = {}

for entity, urls in refs.items():
    filtered = [u for u in urls if u not in dead_urls]
    if filtered == urls:
        updated[entity] = urls
    elif filtered:
        updated[entity] = filtered
        removed_urls += 1
    else:
        removed_entries += 1
        removed_urls += 1

with open(REFS_JSON, 'w', encoding='utf-8') as f:
    json.dump(updated, f, indent=2, ensure_ascii=False)

print(f'Wikipedia URLs removed: {removed_urls}')
print(f'Entries removed:        {removed_entries}')
print(f'Entries remaining:      {len(updated)}')
print(f'refs.json updated.')
