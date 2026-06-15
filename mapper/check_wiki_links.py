"""
check_wiki_links.py
Checks every Wikipedia URL in refs.json and writes a CSV with the HTTP
status code returned. Uses HEAD requests — Wikipedia is bot-friendly.
"""

import json, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REFS_JSON  = r'C:\my stuff\claudetest\mapper\refs.json'
OUTPUT_CSV = r'C:\my stuff\claudetest\mapper\wiki_link_audit.csv'
THREADS    = 20
TIMEOUT    = 12

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; HistoryMapperAudit/1.0; '
                  '+https://mapper.historymaps.org)'
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

    tasks = []
    for entity, urls in refs.items():
        for url in urls:
            if 'wikipedia.org' in url:
                tasks.append((entity, url))
                break  # only first Wikipedia URL per entity

    total = len(tasks)
    print(f'Checking {total} Wikipedia URLs with {THREADS} threads...')

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

    results.sort(key=lambda r: r[0].lower())

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Entity', 'URL', 'Status'])
        writer.writerows(results)

    count_200 = sum(1 for _, _, s in results if s == 200)
    count_404 = sum(1 for _, _, s in results if s == 404)
    other     = [(e, u, s) for e, u, s in results if s not in (200, 404)]

    print(f'\nDone. Results saved to: {OUTPUT_CSV}')
    print(f'  200 (OK):        {count_200}')
    print(f'  404 (Not Found): {count_404}')
    if other:
        print(f'  Other:           {len(other)}')
        for e, u, s in other[:10]:
            print(f'    [{s}] {e}: {u}')
        if len(other) > 10:
            print(f'    ...and {len(other)-10} more (see CSV)')

if __name__ == '__main__':
    main()
