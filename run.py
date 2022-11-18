import json
import os
import time
import typing
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

import requests


# - pip3.11 install requests
# - open dev tools, go to timeline and copy a /i/api/graphql/.../UserTweets request
#   as "node.js fetch"
# - pbpaste > fetch.js
# - python3.11 run.py


def _translate_fetch(url: str, options: dict) -> requests.Request:
    def opt_else(key: str, default: any = None):
        if key in options:
            return options[key]
        return default

    headers = {}
    cookies = None

    method = opt_else('method', 'GET')
    body = opt_else('body')

    if 'headers' in options:
        for header in options['headers']:
            value = options['headers'][header]
            headers[header] = value

            if header.lower() == 'cookie':
                del headers[header]
                # https://stackoverflow.com/a/32281245
                cookie = SimpleCookie()
                cookie.load(value)
                cookies = {k: v.value for k, v in cookie.items()}

    return requests.Request(
        method=method,
        url=url,
        headers=headers,
        data=body,
        cookies=cookies
    )


# copy as "node-js" fetch
def _parse_fetch_js(js_str: str) -> requests.Request:
    # assume "correctness" lol
    lines = js_str.splitlines()

    line0 = lines.pop(0)
    line0_args = line0.split('"')

    if len(line0_args) != 3 or line0_args[0] != 'fetch(' or line0_args[2] != ', {':
        raise Exception("failed to parse fetch js, invalid line 1", line0)

    line_n = lines.pop(-1)
    if line_n.strip() != '});':
        raise Exception("failed to parse fetch js, invalid line -1", line_n)

    url = line0_args[1]
    fetch_opts = json.loads('{' + '\n'.join(lines) + '}')

    return _translate_fetch(url, fetch_opts)


def _iter(base_url: str,
          auth_header: str,
          auth_cookie: str,
          csrf_header: str,
          csrf_cookie: str,
          query: dict,
          cursor: typing.Optional[str]) -> tuple[str, str]:
    params = query.copy()
    vars_str = params['variables'][0]
    vars = json.loads(vars_str)
    if cursor is None:
        if 'cursor' in vars:
            del vars['cursor']
    else:
        vars['cursor'] = cursor
    params['variables'] = [json.dumps(vars)]

    r = requests.get(base_url, headers={
        'authorization': auth_header,
        'x-csrf-token': csrf_header,
    }, cookies={
        'auth_token': auth_cookie,
        'ct0': csrf_cookie,
    }, params=params)
    if r.status_code != 200:
        raise Exception(f"invalid {r.status_code=}, {r.text=}, {r.headers=}")

    js_str = r.text
    cursor = None

    js = json.loads(js_str)

    # '.data.user.result.timeline_v2.timeline.instructions[] | select(.type == "TimelineAddEntries")'
    try:
        entries_cnt = 0
        tl_cursor_entries_cnt = 0
        tl = js['data']['user']['result']['timeline_v2']['timeline']
        for inst in tl['instructions']:
            if inst['type'] == 'TimelineAddEntries':
                entries_cnt = len(inst['entries'])
                for entry in inst['entries']:
                    if entry['content']['entryType'] == 'TimelineTimelineCursor':
                        tl_cursor_entries_cnt += 1
                        if entry['content']['cursorType'] == 'Bottom':
                            cursor = entry['content']['value']
    except Exception as e:
        print("exception trying to extract cursor", e)
        with open('failed.json', 'w') as fp:
            fp.write(js_str)
        raise e

    if entries_cnt == tl_cursor_entries_cnt:
        print("possibly reached end of tl, stopping here")
        cursor = None

    return js_str, cursor


def main():
    with open('fetch.js') as fp:
        request = _parse_fetch_js(fp.read())

    parsed = urlparse(request.url)

    base_url = parsed.scheme + '://' + parsed.netloc + parsed.path
    query = parse_qs(parsed.query)

    vars_str = query['variables'][0]
    vars = json.loads(vars_str)

    if 'userId' not in vars:
        raise Exception("userId not in request")

    if 'cursor' in vars:
        raise Exception("cursor in request, "
                        "make sure you provide the first UserTweets request")

    auth_header = request.headers['authorization']
    auth_cookie = request.cookies['auth_token']
    csrf_cookie = request.cookies['ct0']
    csrf_header = request.headers['x-csrf-token']

    # if already fetched, stop
    try:
        os.makedirs('out', exist_ok=False)
    except FileExistsError as e:
        print("ERROR: output directory 'out' already exists, remove to continue")
        raise e

    page_count = 0
    cursor = None
    while cursor is not None or page_count == 0:
        page_count += 1
        print(f"fetching page={page_count}")

        (page, next_cursor) = _iter(
            base_url=base_url,
            auth_header=auth_header,
            auth_cookie=auth_cookie,
            csrf_header=csrf_header,
            csrf_cookie=csrf_cookie,
            query=query,
            cursor=cursor
        )

        with open(f'out/{page_count}.json', 'w') as fp:
            fp.write(page)

        if next_cursor is not None:
            print(f"got {next_cursor =}")
            time.sleep(0.5)
        cursor = next_cursor

        print(f"fetched page={page_count}")


if __name__ == '__main__':
    main()
