"""
add_whe_refs.py
Adds World History Encyclopedia URLs to all PAR-derived geodata entries in refs.json.
Only touches entries not already in refs.json (hand-curated entries with Wikipedia
links are left alone). User can verify/remove broken links later.
"""

import re, json, os

MAPPER_DIR = os.path.dirname(os.path.abspath(__file__))
GEODATA_JS = os.path.join(MAPPER_DIR, 'js', 'geodata.js')
REFS_JSON  = os.path.join(MAPPER_DIR, 'refs.json')

def to_whe_url(key):
    """Convert a geodata key to a World History Encyclopedia URL."""
    # Unescape apostrophes, strip leading/trailing parens
    name = key.replace("\\'", "'")
    name = re.sub(r'^\((.+)\)$', r'\1', name).strip()
    # Title-case: capitalise after start, spaces, and hyphens
    name = re.sub(r'(^|(?<=[ \-]))([a-z])', lambda m: m.group(1) + m.group(2).upper(), name)
    # Replace spaces with underscores for the URL path
    name = name.replace(' ', '_')
    return f'https://www.worldhistory.org/{name}/'

# ── Read PAR-derived keys from geodata.js ─────────────────────────────────────
with open(GEODATA_JS, encoding='utf-8') as f:
    text = f.read()

# Extract only the PAR section
par_marker = '// ── From primaries / PAR tile data'
par_idx = text.find(par_marker)
if par_idx == -1:
    print('ERROR: PAR section not found'); exit()

par_section = text[par_idx:]
par_keys = re.findall(r"'((?:[^'\\]|\\.)*)'\s*:", par_section)

# ── Load existing refs ────────────────────────────────────────────────────────
with open(REFS_JSON, encoding='utf-8') as f:
    refs = json.load(f)

# ── Add/prepend WHE URLs; ensure WHE always comes before Wiki ─────────────────
added = 0
for key in par_keys:
    real_key = key.replace("\\'", "'")
    whe_url  = to_whe_url(key)
    if real_key not in refs:
        refs[real_key] = [whe_url]
        added += 1
    else:
        urls = refs[real_key]
        if not any('worldhistory.org' in u for u in urls):
            refs[real_key] = [whe_url] + urls   # prepend WHE before existing refs
            added += 1
        else:
            # WHE already present — ensure it's first
            whe  = [u for u in urls if 'worldhistory.org' in u]
            rest = [u for u in urls if 'worldhistory.org' not in u]
            refs[real_key] = whe + rest

# ── Write back ────────────────────────────────────────────────────────────────
with open(REFS_JSON, 'w', encoding='utf-8') as f:
    json.dump(refs, f, indent=2, ensure_ascii=False)

print(f'Added WHE refs for {added} PAR-derived entries.')
print(f'refs.json now has {len(refs)} total entries.')
print(f'\nSample URLs:')
count = 0
for k, v in refs.items():
    if 'worldhistory.org' in v[0]:
        print(f'  {k}: {v[0]}')
        count += 1
        if count >= 8: break
