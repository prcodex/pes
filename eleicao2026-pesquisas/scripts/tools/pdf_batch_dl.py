#!/usr/bin/env python3
"""Download a list of PDF URLs (direct, ZenRows fallback). usage: pdf_batch_dl.py <outdir> <urls.json>  (optional env ZENROWS_API_KEY)"""
import sys, os, json, time, urllib.request, urllib.parse
def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/pdf,*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read()
def main():
    out, lst = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True); k = os.environ.get('ZENROWS_API_KEY')
    for u in json.load(open(lst)):
        name = os.path.basename(urllib.parse.urlparse(u).path); dst = os.path.join(out, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 10000: print('skip', name); continue
        body = b''
        try: st, body = get(u)
        except Exception as e: print('direct fail', name, str(e)[:60])
        if not body.startswith(b'%PDF') and k:
            try: st, body = get('https://api.zenrows.com/v1/?' + urllib.parse.urlencode({'url': u, 'apikey': k, 'premium_proxy': 'true', 'proxy_country': 'br'}), 180)
            except Exception as e: print('zenrows fail', name, str(e)[:60])
        if body.startswith(b'%PDF'): open(dst, 'wb').write(body); print('OK', len(body), name)
        else: print('ERR', name)
        time.sleep(0.5)
if __name__ == '__main__': main()
