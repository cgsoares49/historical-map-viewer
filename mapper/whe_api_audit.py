"""
whe_api_audit.py
Re-audits all WHE references in refs.json using the World History Encyclopedia API.

Matching rules (in order):
  1. Exact case-insensitive title match
  2. Title matches after stripping leading qualifier words (Ancient, Medieval, The, etc.)
  3. Single-word entity: plural/singular match against single-word title

For API mismatches and API errors:
  - If old URL is confirmed-200 in whe_link_audit.csv: keep it
  - Otherwise: remove (guessed URL is likely dead)

Writes whe_api_audit.csv with full details, then updates refs.json.
Run with --retry-errors to only re-query the 40 entries that errored last time.
"""

import json, csv, time, urllib.parse, os, re, sys
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REFS_JSON   = os.path.join(SCRIPT_DIR, 'refs.json')
REPORT_CSV  = os.path.join(SCRIPT_DIR, 'whe_api_audit.csv')
OLD_AUDIT   = os.path.join(SCRIPT_DIR, 'whe_link_audit.csv')

API_KEY       = 'ffd4a9fd6b4592c749b1862868cbe51acb40d8b3'
MIN_QUALITY   = 70
THREADS       = 2
TIMEOUT       = 15
REQUEST_DELAY = 0.6

QUALIFIER_WORDS = {
    'a', 'an', 'the',
    'ancient', 'medieval', 'modern', 'classical', 'early', 'late',
    'old', 'new', 'pre', 'colonial', 'proto', 'neo',
}

def _words(text):
    return re.sub(r'[^\w\s]', '', text.lower()).split()

def _strip_leading_qualifiers(words):
    for i, w in enumerate(words):
        if w not in QUALIFIER_WORDS:
            return words[i:]
    return []

def titles_match(entity_key, api_title):
    e = _words(entity_key)
    t = _words(api_title)
    ts = _strip_leading_qualifiers(t)

    # Rule 1: exact match
    if e == t:
        return True

    # Rule 2: exact after stripping leading qualifiers from title
    if e == ts:
        return True

    # Rule 3: single-word plural/singular (whole title must also be one word)
    if len(e) == 1 and len(t) == 1:
        ew, tw = e[0], t[0]
        if ew.rstrip('s') == tw or ew == tw.rstrip('s'):
            return True

    return False

def search_whe(entity_key):
    """Return (url, title, score) for top API result, or (None, None, None)."""
    query = urllib.parse.quote(entity_key)
    api_url = (
        f'https://www.worldhistory.org/api/search.php'
        f'?q={query}&ci_type_ids=1,2&min_quality={MIN_QUALITY}&key={API_KEY}'
    )
    for attempt in range(4):
        try:
            with urlopen(api_url, timeout=TIMEOUT) as resp:
                data = json.load(resp)
            if data:
                top = data[0]
                return top['url'], top['data']['ci_title'], top['score']
            return None, None, None
        except HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (2 ** attempt))
                continue
            return None, None, f'ERROR: HTTP {e.code}'
        except (URLError, json.JSONDecodeError, KeyError) as e:
            return None, None, f'ERROR: {e}'
        finally:
            time.sleep(REQUEST_DELAY)
    return None, None, 'ERROR: 429 after retries'

def apply_result(key, refs, old_whe, non_whe, api_url, api_title, score, confirmed_200):
    """Decide what to do with one entry. Returns (change_label, new_urls)."""
    is_error = isinstance(score, str) and score.startswith('ERROR')

    if not is_error and api_url and titles_match(key, api_title):
        # Good API match
        refs[key] = [api_url] + non_whe
        if old_whe == api_url:   return 'confirmed'
        elif old_whe:            return 'replaced'
        else:                    return 'added'

    # No good match (error, no result, or title mismatch)
    if old_whe and old_whe in confirmed_200:
        return 'kept'          # confirmed working — preserve it

    # Unverified old URL (or no old URL) — remove
    refs[key] = non_whe
    if old_whe:
        return 'removed'
    return 'no_result'         # never had a URL, API found nothing useful

def main():
    retry_errors = '--retry-errors' in sys.argv

    # Load confirmed-200 URLs from previous crawl audit
    confirmed_200 = set()
    if os.path.exists(OLD_AUDIT):
        with open(OLD_AUDIT, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if str(row.get('Status', '')).strip() == '200':
                    confirmed_200.add(row['URL'])

    with open(REFS_JSON, encoding='utf-8') as f:
        refs = json.load(f)

    # Load previous audit results if doing incremental retry
    prev_results = {}
    if retry_errors and os.path.exists(REPORT_CSV):
        with open(REPORT_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                prev_results[row['Entity']] = row

    keys = list(refs.keys())

    if retry_errors:
        keys_to_query = [k for k in keys if prev_results.get(k, {}).get('Change') == 'error']
        print(f'Retrying {len(keys_to_query)} errored entries...')
    else:
        keys_to_query = keys
        print(f'Querying WHE API for {len(keys_to_query)} entries ({THREADS} threads)...')

    api_results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(search_whe, k): k for k in keys_to_query}
        for fut in as_completed(futures):
            k = futures[fut]
            api_results[k] = fut.result()
            done += 1
            if done % 50 == 0 or done == len(keys_to_query):
                print(f'  {done}/{len(keys_to_query)}...', flush=True)

    # Merge with previous results for retry mode
    if retry_errors:
        for k, row in prev_results.items():
            if k not in api_results:
                api_url   = row.get('API URL') or None
                api_title = row.get('API Title') or None
                score     = row.get('Score') or None
                api_results[k] = (api_url, api_title, score)

    # Reset refs to original state for clean re-application
    with open(REFS_JSON, encoding='utf-8') as f:
        refs = json.load(f)

    report_rows = []
    counts = {}

    for key in keys:
        urls    = refs[key]
        old_whe = next((u for u in urls if 'worldhistory.org' in u), None)
        non_whe = [u for u in urls if 'worldhistory.org' not in u]

        api_url, api_title, score = api_results.get(key, (None, None, None))
        change = apply_result(key, refs, old_whe, non_whe, api_url, api_title, score, confirmed_200)
        counts[change] = counts.get(change, 0) + 1

        new_whe = next((u for u in refs[key] if 'worldhistory.org' in u), '')
        report_rows.append([key, old_whe or '', api_url or '', api_title or '', score or '', change])

    order = {'replaced':0,'added':1,'kept':2,'confirmed':3,'removed':4,'no_result':5,'error':6}
    report_rows.sort(key=lambda r: (order.get(r[5], 9), r[0].lower()))

    with open(REPORT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Entity', 'Old WHE URL', 'API URL', 'API Title', 'Score', 'Change'])
        writer.writerows(report_rows)

    with open(REFS_JSON, 'w', encoding='utf-8') as f:
        json.dump(refs, f, indent=2, ensure_ascii=False)

    print(f'\nDone.')
    labels = [('confirmed','Confirmed (same URL)'),('replaced','Replaced (new URL)'),
              ('added','Added (new entry)'),('kept','Kept (confirmed-200)'),
              ('removed','Removed (unverified/dead)'),('no_result','No result, no URL'),
              ('error','Errors')]
    for k, label in labels:
        if counts.get(k): print(f'  {label+":":<30} {counts[k]}')
    print(f'\nReport: {REPORT_CSV}')

if __name__ == '__main__':
    main()
