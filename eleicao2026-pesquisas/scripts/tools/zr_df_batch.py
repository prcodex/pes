#!/usr/bin/env python3
"""Bulk-download the Datafolha interactive database (arte.folha) via ZenRows.
usage: ZENROWS_API_KEY=... zr_df_batch.py <outdir> [round] [place] [office]
First fetch index.json: https://arte.folha.uol.com.br/databases/eleicoes/2026/pesquisa-eleitoral/index.json -> df_index.json
"""
import sys, os, json, time, urllib.request, urllib.parse
BASE = "https://arte.folha.uol.com.br/databases/eleicoes/2026/pesquisa-eleitoral/"
def key():
    k = os.environ.get('ZENROWS_API_KEY')
    if not k: raise SystemExit('set ZENROWS_API_KEY')
    return k
def fetch(url, k):
    q = urllib.parse.urlencode({'url': url, 'apikey': k})
    for attempt in range(3):
        try:
            r = urllib.request.urlopen('https://api.zenrows.com/v1/?' + q, timeout=60); return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 422): return e.code, b''
            time.sleep(2)
        except Exception: time.sleep(2)
    return 0, b''
def main():
    out = sys.argv[1]; rnd = sys.argv[2] if len(sys.argv) > 2 else 'segundo-turno'
    place = sys.argv[3] if len(sys.argv) > 3 else 'brasil'; office = sys.argv[4] if len(sys.argv) > 4 else 'presidente'
    os.makedirs(out, exist_ok=True); k = key(); idx = json.load(open('df_index.json')); inst = idx[0]['slug']; paths = []
    for r in idx[0]['items']:
        if r['slug'] != rnd: continue
        for p in r['items']:
            if p['slug'] != place: continue
            for o in p['items']:
                if o['slug'] != office: continue
                paths += [f"{inst}/{rnd}/{place}/{office}/candidates.json", f"{inst}/{rnd}/{place}/{office}/titles.json"]
                for q in o['items']:
                    for h in q['items']:
                        for g in h['items']:
                            stem = f"{inst}/{rnd}/{place}/{office}/{q['slug']}/{h['slug']}/{g['slug']}"; paths += [stem + '.csv', stem + '_metadata.json']
    ok = 0
    for pth in paths:
        dst = os.path.join(out, pth.replace('/', '__'))
        if os.path.exists(dst) and os.path.getsize(dst) > 0: ok += 1; continue
        st, body = fetch(BASE + pth, k)
        if st == 200 and body: open(dst, 'wb').write(body); ok += 1; print('OK', pth)
        else: print('ERR', st, pth)
    print('done', ok, '/', len(paths))
if __name__ == '__main__': main()
