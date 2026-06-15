"""
check_whe_403s.py
Re-checks the 403 entries from whe_link_audit.csv using GET requests
with full browser-like headers to bypass bot rejection. Updates the CSV.
"""

import csv, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

INPUT_CSV  = r'C:\my stuff\claudetest\mapper\whe_link_audit.csv'
OUTPUT_CSV = r'C:\my stuff\claudetest\mapper\whe_link_audit.csv'
THREADS    = 10   # lower thread count to be less aggressive
TIMEOUT    = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
}

def check_url_get(entity, url):
    req = Request(url, headers=HEADERS)  # GET by default
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
    # Load existing CSV
    rows = []
    with open(INPUT_CSV, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows.append(row)

    # Separate 403s from the rest
    to_recheck = [(r[0], r[1]) for r in rows if r[2] == '403']
    keep = {r[1]: r for r in rows if r[2] != '403'}

    print(f'Re-checking {len(to_recheck)} 403 entries with GET...')

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(check_url_get, e, u): (e, u) for e, u in to_recheck}
        for fut in as_completed(futures):
            entity, url, status = fut.result()
            results[url] = [entity, url, str(status)]
            done += 1
            if done % 50 == 0 or done == len(to_recheck):
                print(f'  {done}/{len(to_recheck)} done...', flush=True)

    # Merge back
    all_rows = list(keep.values()) + list(results.values())
    all_rows.sort(key=lambda r: r[0].lower())

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

    count_200 = sum(1 for r in all_rows if r[2] == '200')
    count_404 = sum(1 for r in all_rows if r[2] == '404')
    other     = [r for r in all_rows if r[2] not in ('200', '404')]

    print(f'\nDone. Updated CSV saved to: {OUTPUT_CSV}')
    print(f'  200 (OK):        {count_200}')
    print(f'  404 (Not Found): {count_404}')
    if other:
        print(f'  Other:           {len(other)}')
        for r in other[:10]:
            print(f'    [{r[2]}] {r[0]}: {r[1]}')
        if len(other) > 10:
            print(f'    ...and {len(other)-10} more (see CSV)')

if __name__ == '__main__':
    main()
