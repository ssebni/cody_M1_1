"""One-off export of the authenticated user's Threads posts and insights.

Set THREADS_ACCESS_TOKEN in the environment; credentials never enter the CSV.
This script reads Threads only and does not enable any recurring collection.
"""
import argparse
import csv
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

METRICS = ('views', 'likes', 'replies', 'reposts', 'quotes')
KST = timezone(timedelta(hours=9))


class APIError(RuntimeError):
    def __init__(self, status, code=None):
        self.status, self.code = status, code
        super().__init__(f'Threads API HTTP {status}, error code {code}')


def api_get(path, params, token):
    request = Request('https://graph.threads.net/v1.0/' + path + '?' + urlencode(params),
                      headers={'Authorization': 'Bearer ' + token})
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.load(response)
    except HTTPError as exc:
        try:
            code = json.load(exc).get('error', {}).get('code')
        except (ValueError, AttributeError):
            code = None
        raise APIError(exc.code, code) from None
    if not isinstance(payload.get('data'), list):
        raise RuntimeError('Invalid API data response')
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'data/threads_insights.csv')
    args = parser.parse_args()
    token = os.getenv('THREADS_ACCESS_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Set THREADS_ACCESS_TOKEN; do not put it in the source code.')
    posts, seen, after = {}, set(), None
    for _ in range(100):
        params = {'fields': 'id,timestamp,text,media_type', 'limit': 100}
        if after:
            params['after'] = after
        page = api_get('me/threads', params, token)
        for post in page['data']:
            post_id = post.get('id', '')
            if not post_id.isascii() or not post_id.isdigit():
                raise RuntimeError('Invalid post identifier')
            posts[post_id] = post
        paging = page.get('paging', {})
        if not paging.get('next'):
            break
        after = paging.get('cursors', {}).get('after')
        if not after or after in seen:
            raise RuntimeError('Invalid pagination; output not replaced')
        seen.add(after)
    else:
        raise RuntimeError('Pagination safety limit reached; output not replaced')
    if not posts:
        raise RuntimeError('No posts returned; output not replaced')
    print(json.dumps({'phase': 'posts', 'unique_posts': len(posts)}), flush=True)
    rows = []
    for i, (post_id, post) in enumerate(posts.items(), 1):
        values = {metric: None for metric in METRICS}
        status = 'empty'
        try:
            payload = api_get(post_id + '/insights', {'metric': ','.join(METRICS)}, token)
            for metric in payload['data']:
                name, entries = metric.get('name'), metric.get('values', [])
                value = entries[0].get('value') if entries else None
                if name in values and type(value) is int and value >= 0:
                    values[name] = value
            status = 'success' if all(v is not None for v in values.values()) else 'empty'
        except APIError as exc:
            if exc.status in (401, 403, 429) or exc.code in (4, 32, 190, 613):
                raise
            status = 'error'
        rows.append({'post_id': post_id, 'timestamp': post.get('timestamp'), 'text': post.get('text'),
                     'media_type': post.get('media_type'), **values, 'status': status,
                     'collected_at': datetime.now(KST).isoformat()})
        if i % 20 == 0 or i == len(posts):
            print(json.dumps({'phase': 'insights', 'processed': i, 'total': len(posts),
                              'success': sum(r['status'] == 'success' for r in rows)}), flush=True)
        time.sleep(.15)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.csv.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(args.output)
    print(json.dumps({'saved_rows': len(rows), 'success': sum(r['status'] == 'success' for r in rows)}))


if __name__ == '__main__':
    main()
