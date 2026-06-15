"""
check_whe_links.py
Checks every WHE (worldhistory.org) URL in refs.json and writes a CSV
with the HTTP status code returned. Uses 20 parallel threads for speed.
"""

import json, csv, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REFS_JSON  = r'C:\my stuff\claudetest\mapper\refs.json'
OUTPUT_CSV = r'C:\my stuff\claudetest\mapper\whe_link_audit.csv'
THREADS    = 20
TIMEOUT    = 12  # seconds per request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; HistoryMapperAudit/1.0)'
}

def check_url(entity, url):
    req = Request(url, method='HEAD', headers=HEADERS)
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            return entity, url, resp.status
    except HTTPError as e:
        return entity, url, e.code
    except URLError as e:
        return entity, url, f'ERROR: {e.reason}'
    except Exception as e:
        return entity, url, f'ERROR: {e}'

def main():
    with open(REFS_JSON, encoding='utf-8') as f:
        refs = json.load(f)

    # Collect (entity, whe_url) pairs — one WHE URL per entity
    tasks = []
    for entity, urls in refs.items():
        for url in urls:
            if 'worldhistory.org' in url:
                tasks.append((entity, url))
                break  # only first WHE URL per entity

    total = len(tasks)
    print(f'Checking {total} WHE URLs with {THREADS} threads...')

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(check_url, e, u): (e, u) for e, u in tasks}
        for fut in as_completed(futures):
            entity, url, status = fut.result()
            results.append((entity, url, status))
            done += 1
            if done % 100 == 0 or done == total:
                print(f'  {done}/{total} done...', flush=True)

    # Sort by entity name for readability
    results.sort(key=lambda r: r[0].lower())

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Entity', 'URL', 'Status'])
        writer.writerows(results)

    count_200 = sum(1 for _, _, s in results if s == 200)
    count_404 = sum(1 for _, _, s in results if s == 404)
    other     = [(e, u, s) for e, u, s in results if s not in (200, 404)]

    print(f'\nDone. Results saved to: {OUTPUT_CSV}')
    print(f'  200 (OK):      {count_200}')
    print(f'  404 (Not Found): {count_404}')
    if other:
        print(f'  Other:         {len(other)}')
        for e, u, s in other[:10]:
            print(f'    [{s}] {e}: {u}')
        if len(other) > 10:
            print(f'    ...and {len(other)-10} more (see CSV)')

if __name__ == '__main__':
    main()
