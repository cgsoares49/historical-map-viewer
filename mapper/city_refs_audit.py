"""
city_refs_audit.py
Looks up WHE and Wikipedia references for city names not already in refs.json.
Skips entries already in refs.json to preserve curated PAR refs.
Applies city_overrides.csv so ref names match what CITY_DATA actually uses.

Usage:
  python city_refs_audit.py            # full run, updates refs.json
  python city_refs_audit.py --dry-run  # report only, no writes

Rate limiting: 2 threads, 0.6s WHE delay, 0.2s Wikipedia delay.
Estimated runtime: 8-12 minutes for ~600 new entries.
"""

import json, csv, time, urllib.parse, os, re, sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
REFS_JSON     = os.path.join(SCRIPT_DIR, 'refs.json')
LOC_CSV       = os.path.join(SCRIPT_DIR, 'city_locations.csv')
OVERRIDES_CSV = os.path.join(SCRIPT_DIR, 'city_overrides.csv')
REPORT_CSV    = os.path.join(SCRIPT_DIR, 'city_refs_audit.csv')

API_KEY       = 'ffd4a9fd6b4592c749b1862868cbe51acb40d8b3'
MIN_QUALITY   = 70
THREADS       = 2
TIMEOUT       = 15
WHE_DELAY     = 0.6   # seconds between WHE requests
WIKI_DELAY    = 0.2   # seconds between Wikipedia requests

QUALIFIER_WORDS = {
    'a', 'an', 'the',
    'ancient', 'medieval', 'modern', 'classical', 'early', 'late',
    'old', 'new', 'pre', 'colonial', 'proto', 'neo',
}


# ── Name helpers ──────────────────────────────────────────────────────────────

def _words(text):
    return re.sub(r'[^\w\s]', '', text.lower()).split()

def _strip_qualifiers(words):
    for i, w in enumerate(words):
        if w not in QUALIFIER_WORDS:
            return words[i:]
    return []

def titles_match(search_name, api_title):
    """Match city name against WHE API title.
    Handles disambiguation format: 'Memphis (Ancient Egypt)' matches 'Memphis'."""
    e = _words(search_name)
    t = _words(api_title)
    ts = _strip_qualifiers(t)

    if e == t:  return True
    if e == ts: return True

    # Strip parenthetical disambiguation from WHE title: 'Memphis (Ancient Egypt)' → 'Memphis'
    bare = re.sub(r'\s*\(.*\)', '', api_title).strip()
    tb = _words(bare)
    if e == tb: return True
    if e == _strip_qualifiers(tb): return True

    # Single-word plural/singular
    if len(e) == 1 and len(tb) == 1:
        ew, tw = e[0], tb[0]
        if ew.rstrip('s') == tw or ew == tw.rstrip('s'): return True

    return False

def clean_name(ref_name):
    """Strip parenthetical suffixes for lookup: 'Priene (Old)' → 'Priene'."""
    return re.sub(r'\s*\(.*\)\s*$', '', ref_name).strip()

def is_ruins(ref_name):
    """Names entirely in parens like '(Alassa)' indicate uncertain/ruins sites."""
    return ref_name.startswith('(') and ref_name.endswith(')')


# ── API calls ─────────────────────────────────────────────────────────────────

def search_whe(search_name):
    """Return (url, title, score) or (None, None, reason)."""
    query = urllib.parse.quote(search_name)
    url = (f'https://www.worldhistory.org/api/search.php'
           f'?q={query}&ci_type_ids=1,2&min_quality={MIN_QUALITY}&key={API_KEY}')
    for attempt in range(4):
        try:
            with urlopen(url, timeout=TIMEOUT) as resp:
                data = json.load(resp)
            if data:
                top = data[0]
                return top['url'], top['data']['ci_title'], top['score']
            return None, None, 'no_result'
        except HTTPError as e:
            if e.code == 429:
                wait = 5 * (2 ** attempt)
                print(f'  429 rate limit — waiting {wait}s', flush=True)
                time.sleep(wait)
                continue
            return None, None, f'HTTP {e.code}'
        except (URLError, json.JSONDecodeError, KeyError) as e:
            return None, None, f'error: {e}'
        finally:
            time.sleep(WHE_DELAY)
    return None, None, '429 retries exhausted'


def search_wiki(search_name):
    """Return (canonical_url, page_type) or (None, reason).
    page_type is 'standard' (article), 'disambiguation', or error string."""
    title = urllib.parse.quote(search_name.replace(' ', '_'))
    api_url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{title}'
    try:
        req = Request(api_url, headers={
            'User-Agent': 'HistoryMapper/1.0 (city-refs-audit; cgsoares49@outlook.com)'
        })
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
        page_type = data.get('type', 'unknown')
        page_url  = data.get('content_urls', {}).get('desktop', {}).get('page', '')
        return (page_url or None), page_type
    except HTTPError as e:
        return None, ('not_found' if e.code == 404 else f'HTTP {e.code}')
    except (URLError, json.JSONDecodeError) as e:
        return None, f'error: {e}'
    finally:
        time.sleep(WIKI_DELAY)


# ── City name loading ─────────────────────────────────────────────────────────

def load_overrides():
    overrides = {}
    if os.path.exists(OVERRIDES_CSV):
        with open(OVERRIDES_CSV, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                key = (round(float(row['Lon']), 4),
                       round(float(row['Lat']), 4),
                       row['FromYear'].strip())
                overrides[key] = {
                    'action':   row['Action'].strip(),
                    'new_name': row.get('NewRefName', '').strip(),
                }
    return overrides


def get_city_ref_names():
    """Read city_locations.csv, apply overrides, return deduplicated ref names."""
    overrides = load_overrides()
    seen, names = set(), []
    with open(LOC_CSV, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            ov_key = (round(float(row['Lon']), 4),
                      round(float(row['Lat']), 4),
                      row['FromYear'].strip())
            ov = overrides.get(ov_key)
            if ov:
                if ov['action'] in ('SKIP', 'SKIP_DUPE'):
                    continue
                if ov['action'] == 'RENAME' and ov['new_name']:
                    row = dict(row)
                    row['RefName'] = ov['new_name']
            n = row['RefName']
            if n.lower() not in seen:
                seen.add(n.lower())
                names.append(n)
    return names


# ── Per-city lookup ───────────────────────────────────────────────────────────

def lookup_city(ref_name):
    """Run WHE + Wikipedia lookups. Returns (whe_url, whe_title, whe_score, wiki_url, wiki_type)."""
    if is_ruins(ref_name):
        search = ref_name[1:-1].strip()   # strip outer parens
    else:
        search = clean_name(ref_name)

    if not search:
        return None, None, 'empty', None, 'skipped'

    whe_url, whe_title, whe_score = search_whe(search)
    if whe_url and whe_title and not titles_match(search, whe_title):
        whe_url   = None
        whe_score = f'mismatch ({whe_title})'

    wiki_url, wiki_type = search_wiki(search)

    return whe_url, whe_title, whe_score, wiki_url, wiki_type


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    dry_run = '--dry-run' in sys.argv

    with open(REFS_JSON, encoding='utf-8') as f:
        refs = json.load(f)

    all_names  = get_city_ref_names()
    to_lookup  = [n for n in all_names if n.lower() not in refs]
    n_existing = len(all_names) - len(to_lookup)

    print(f'City ref names (unique): {len(all_names)}')
    print(f'Already in refs.json:    {n_existing}  (skipped)')
    print(f'Need lookup:             {len(to_lookup)}')
    if dry_run:
        print('DRY RUN — refs.json will NOT be written')
    print()

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(lookup_city, n): n for n in to_lookup}
        for fut in as_completed(futures):
            n = futures[fut]
            results[n] = fut.result()
            done += 1
            if done % 25 == 0 or done == len(to_lookup):
                print(f'  {done}/{len(to_lookup)}...', flush=True)

    # Reload refs fresh before writing (avoids threading races)
    with open(REFS_JSON, encoding='utf-8') as f:
        refs = json.load(f)

    report_rows = []
    counts = {'both': 0, 'whe': 0, 'wiki': 0, 'none': 0}

    for ref_name in to_lookup:
        whe_url, whe_title, whe_score, wiki_url, wiki_type = results.get(
            ref_name, (None, None, None, None, None))

        urls = []
        if whe_url:  urls.append(whe_url)
        if wiki_url: urls.append(wiki_url)

        if not dry_run and urls:
            refs[ref_name.lower()] = urls

        status = ('both' if (whe_url and wiki_url)
                  else 'whe'  if whe_url
                  else 'wiki' if wiki_url
                  else 'none')
        counts[status] += 1

        report_rows.append([
            ref_name,
            whe_url   or '',
            whe_title or '',
            str(whe_score or ''),
            wiki_url  or '',
            wiki_type or '',
            status,
        ])

    order = {'both': 0, 'whe': 1, 'wiki': 2, 'none': 3}
    report_rows.sort(key=lambda r: (order.get(r[6], 9), r[0].lower()))

    with open(REPORT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['RefName', 'WHE URL', 'WHE Title', 'WHE Score',
                    'Wiki URL', 'Wiki Type', 'Status'])
        w.writerows(report_rows)

    if not dry_run:
        with open(REFS_JSON, 'w', encoding='utf-8') as f:
            json.dump(refs, f, indent=2, ensure_ascii=False)

    print(f'\nResults from {len(to_lookup)} lookups:')
    print(f'  Both WHE + Wiki : {counts["both"]}')
    print(f'  WHE only        : {counts["whe"]}')
    print(f'  Wiki only       : {counts["wiki"]}')
    print(f'  Nothing found   : {counts["none"]}')
    print(f'\nReport written to: {REPORT_CSV}')
    if not dry_run:
        print(f'refs.json updated.')
    else:
        print('(dry run — refs.json unchanged)')


if __name__ == '__main__':
    main()
