#!/usr/bin/env python3
"""Banco separado de pesquisas (claude-app 23/10, pedido do Pedro): data/pesquisas.db.

Tabelas:
  pesquisas   uma linha por pesquisa (instituto, datas, n, registro, totais, válidos, rejeição, urls, fonte, json extra)
  recortes    segmentos (região/sexo/idade/renda/escolaridade/religião/...) por pesquisa: pesquisa_id, segmento, categoria, lula, flavio, bn, ns
  docs        documentos: pdf/relatório, matéria, transcrição de vídeo, análise — com texto integral, fonte, url, data, outlet/canal
  notas       anotações de análise (autor, data, texto)
Ingestão: (a) polls + c50_inputs do eleicao.db; (b) articles rotuladas tema pesquisas-eleitorais; (c) transcrições de vídeos que citam
pesquisa/instituto; (d) PDFs/MDs em out/polls/; (e) JSON compilado pela claude-app (polls_week.json) via `ingest-json`.
uso: pesquisas_db.py build | ingest-json <file> | ingest-doc <tipo> <path> [--url U --fonte F --data D] | stats
"""
import os, sys, json, sqlite3, subprocess, argparse, datetime as dt, re
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "data", "eleicao.db")
DB = os.path.join(BASE, "data", "pesquisas.db")
POLLS_DIR = os.path.join(BASE, "out", "polls")
INST_RX = re.compile(r"(?i)pesquisa|datafolha|quaest|atlas|poderdata|aya\b|paran[áa] pesquisas|ipec|ipsos|futura|gerp|real time|vox|nexus|meta\b.*pesquisa|intenç[ãa]o de voto|votos v[áa]lidos|rejei")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pesquisas(id INTEGER PRIMARY KEY, instituto TEXT, contratante TEXT, data_inicio TEXT, data_fim TEXT, data_divulgacao TEXT,
  n INTEGER, margem REAL, registro_tse TEXT, modo TEXT, lula_total REAL, flavio_total REAL, branco_nulo REAL, indecisos REAL,
  lula_validos REAL, flavio_validos REAL, rejeicao_lula REAL, rejeicao_flavio REAL, url_noticia TEXT, url_pdf TEXT, pdf_path TEXT,
  fonte TEXT, extra_json TEXT, notas TEXT, criado TEXT, UNIQUE(instituto, data_fim));
CREATE TABLE IF NOT EXISTS recortes(id INTEGER PRIMARY KEY, pesquisa_id INTEGER, segmento TEXT, categoria TEXT, lula REAL, flavio REAL,
  branco_nulo REAL, nao_sabe REAL, base INTEGER, fonte TEXT, UNIQUE(pesquisa_id, segmento, categoria));
CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY, tipo TEXT, fonte TEXT, outlet TEXT, bloco TEXT, titulo TEXT, url TEXT, path TEXT,
  data TEXT, texto TEXT, meta_json TEXT, criado TEXT, UNIQUE(tipo, url, path));
CREATE TABLE IF NOT EXISTS notas(id INTEGER PRIMARY KEY, autor TEXT, data TEXT, titulo TEXT, texto TEXT);
"""


def iso():
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; c.executescript(SCHEMA); return c


def norm_inst(s):
    s = (s or "").strip()
    m = {"poderdata/aya": "PoderData", "poderdata": "PoderData", "aya": "PoderData", "quaest/genial": "Quaest", "genial/quaest": "Quaest",
         "atlasintel": "AtlasIntel", "atlas/bloomberg": "AtlasIntel", "atlas": "AtlasIntel", "ipsos-ipec": "Ipsos-Ipec", "ipec": "Ipsos-Ipec", "ipespe": "Ipespe", "instituto verita": "Veritá", "meio": "Meio/Ideia", "ideia": "Meio/Ideia", "vox brasil": "Vox Brasil", "vox": "Vox Brasil",
         "paraná pesquisas": "Paraná Pesquisas", "parana pesquisas": "Paraná Pesquisas", "meta/ipespe": "Meta", "real time big data": "Real Time Big Data"}
    base = re.split(r"\s*[\(/]", s)[0].strip()  # 'Quaest (Genial/Quaest)' -> 'Quaest'; 'Nexus/BTG Pactual' -> 'Nexus'
    return m.get(s.lower(), m.get(base.lower(), base or s))


def upsert_poll(c, d, fonte):
    d = {k: (None if v == "" else v) for k, v in d.items()}
    inst = norm_inst(d.get("instituto"))
    if not inst or not d.get("data_fim"):
        return None
    known = {"instituto", "contratante", "data_inicio", "data_fim", "data_divulgacao", "n", "margem", "registro_tse", "modo", "lula_total", "flavio_total",
             "branco_nulo", "indecisos", "lula_validos", "flavio_validos", "rejeicao_lula", "rejeicao_flavio", "url_noticia", "url_pdf", "pdf_path", "notas"}
    extra = {k: v for k, v in d.items() if k not in known}
    row = c.execute("SELECT * FROM pesquisas WHERE instituto=? AND data_fim=?", (inst, d["data_fim"])).fetchone()
    vals = {k: d.get(k) for k in known}; vals["instituto"] = inst
    if row:
        # fill only missing fields; merge extra
        old = dict(row); oldx = json.loads(old.get("extra_json") or "{}")
        for k in known:
            if old.get(k) in (None, "") and vals.get(k) not in (None, ""):
                c.execute(f"UPDATE pesquisas SET {k}=? WHERE id=?", (vals[k], old["id"]))
        oldx.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
        c.execute("UPDATE pesquisas SET extra_json=?, fonte=COALESCE(fonte,'')||' | '||? WHERE id=?", (json.dumps(oldx, ensure_ascii=False), fonte, old["id"]))
        return old["id"]
    cols = list(known) + ["fonte", "extra_json", "criado"]
    c.execute(f"INSERT INTO pesquisas({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
              [vals.get(k) for k in known] + [fonte, json.dumps(extra, ensure_ascii=False), iso()])
    return c.execute("SELECT id FROM pesquisas WHERE instituto=? AND data_fim=?", (inst, d["data_fim"])).fetchone()[0]


def add_recortes(c, pid, seg, fonte):
    """seg: {segmento: {categoria: {lula:.., flavio:.., bn:.., ns:..}}} or lists."""
    if not isinstance(seg, dict):
        return 0
    k = 0
    for segmento, cats in seg.items():
        if isinstance(cats, dict):
            for cat, v in cats.items():
                if isinstance(v, dict):
                    c.execute("INSERT OR REPLACE INTO recortes(pesquisa_id,segmento,categoria,lula,flavio,branco_nulo,nao_sabe,base,fonte) VALUES(?,?,?,?,?,?,?,?,?)",
                              (pid, segmento, str(cat), v.get("lula"), v.get("flavio"), v.get("branco_nulo", v.get("bn")), v.get("nao_sabe", v.get("ns")), v.get("base"), fonte)); k += 1
        elif isinstance(cats, list):
            for v in cats:
                if isinstance(v, dict) and v.get("categoria"):
                    c.execute("INSERT OR REPLACE INTO recortes(pesquisa_id,segmento,categoria,lula,flavio,branco_nulo,nao_sabe,base,fonte) VALUES(?,?,?,?,?,?,?,?,?)",
                              (pid, segmento, str(v["categoria"]), v.get("lula"), v.get("flavio"), v.get("branco_nulo", v.get("bn")), v.get("nao_sabe", v.get("ns")), v.get("base"), fonte)); k += 1
    return k


def add_doc(c, tipo, fonte, outlet, bloco, titulo, url, path, data, texto, meta=None):
    if c.execute("SELECT 1 FROM docs WHERE tipo=? AND COALESCE(url,'')=? AND COALESCE(path,'')=?", (tipo, url or '', path or '')).fetchone():
        return
    c.execute("INSERT OR IGNORE INTO docs(tipo,fonte,outlet,bloco,titulo,url,path,data,texto,meta_json,criado) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (tipo, fonte, outlet, bloco, titulo, url, path, data, texto, json.dumps(meta or {}, ensure_ascii=False), iso()))


def build(c):
    s = sqlite3.connect(SRC); s.row_factory = sqlite3.Row
    n = {"polls": 0, "c50": 0, "art": 0, "vid": 0, "pdf": 0}
    for r in s.execute("SELECT * FROM polls"):
        upsert_poll(c, {"instituto": r["instituto"], "data_fim": r["data_fim"], "lula_validos": r["lula_v"], "flavio_validos": r["flavio_v"],
                        "registro_tse": r["registro_tse"], "url_noticia": r["fonte_url"]}, "eleicao.db/polls"); n["polls"] += 1
    for r in s.execute("SELECT * FROM c50_inputs WHERE tipo='poll'"):
        v = json.loads(r["valor_json"])
        d = {"instituto": v.get("instituto"), "data_inicio": v.get("data_inicio"), "data_fim": v.get("data_fim"), "lula_validos": v.get("lula_v"),
             "flavio_validos": v.get("flavio_v"), "lula_total": v.get("lula_e"), "flavio_total": v.get("flavio_e"), "branco_nulo": v.get("bn"),
             "indecisos": v.get("ind"), "registro_tse": v.get("registro_tse"), "n": v.get("n"), "margem": v.get("margem"), "url_noticia": v.get("url") or r["url"],
             "notas": r["nota"]}
        upsert_poll(c, d, "eleicao.db/c50_inputs"); n["c50"] += 1
    try:
        rej = os.path.join(BASE, "data", "rejeicao.csv")
        import csv
        for q in csv.DictReader(open(rej, encoding="utf-8")):
            upsert_poll(c, {"instituto": q["instituto"], "data_fim": q["data_fim"], "rejeicao_lula": float(q["rej_l"]), "rejeicao_flavio": float(q["rej_f"]),
                            "lula_total": float(q["lula_t"]), "flavio_total": float(q["flavio_t"]), "url_pdf": q.get("url") or None, "notas": q.get("nota")}, "rejeicao.csv")
    except Exception as e:
        print("rejeicao.csv:", e)
    # articles about polls (labels tema pesquisas-eleitorais) since 10/10, all blocos
    q = ("SELECT a.id, a.outlet, a.bloco, a.title, a.summary, a.url, a.published_utc, l.tema, l.valence_lula, l.valence_flavio, l.polls_cited "
         "FROM articles a JOIN labels l ON l.item_id='a:'||a.id AND l.model='haiku' WHERE l.tema_slug='pesquisas-eleitorais' AND a.published_utc>='2026-10-10'")
    for r in s.execute(q):
        add_doc(c, "materia", "eleicao.db/articles", r["outlet"], r["bloco"], r["title"], r["url"], None, r["published_utc"],
                f"{r['title']}\n\n{r['summary'] or ''}", {"tema": r["tema"], "vl": r["valence_lula"], "vf": r["valence_flavio"], "polls_cited": r["polls_cited"]}); n["art"] += 1
    # video transcripts mentioning polls since 15/10 (all channels; bloco kept)
    q = ("SELECT v.id, v.channel, v.bloco, v.title, v.published, v.views, t.text FROM videos v JOIN transcripts t ON t.video_id=v.id WHERE v.published>='2026-10-12'")
    for r in s.execute(q):
        if INST_RX.search(r["text"] or "") and len(r["text"] or "") > 200:
            add_doc(c, "transcricao", "eleicao.db/transcripts", r["channel"], r["bloco"], r["title"], f"https://www.youtube.com/watch?v={r['id']}", None,
                    r["published"], r["text"], {"views": r["views"], "mencoes": len(INST_RX.findall(r["text"]))}); n["vid"] += 1
    # PDFs / MDs in out/polls
    if os.path.isdir(POLLS_DIR):
        for f in sorted(os.listdir(POLLS_DIR)):
            p = os.path.join(POLLS_DIR, f)
            if f.endswith(".pdf"):
                t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
                add_doc(c, "relatorio_pdf", "out/polls", None, None, f, None, p, None, t, {"chars": len(t)}); n["pdf"] += 1
            elif f.endswith(".md"):
                add_doc(c, "relatorio_md", "out/polls", None, None, f, None, p, None, open(p, encoding="utf-8", errors="ignore").read(), {}); n["pdf"] += 1
    c.commit(); return n


def ingest_json(c, path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("pesquisas") or data.get("polls") or list(data.values())
    k = 0; kr = 0
    for d in data:
        if not isinstance(d, dict):
            continue
        seg = (d.get("outros_campos") or {}).get("segmentos") if isinstance(d.get("outros_campos"), dict) else None
        seg = seg or d.get("segmentos")
        pid = upsert_poll(c, {kk: v for kk, v in d.items() if kk != "segmentos"}, f"claude-app web {os.path.basename(path)}")
        if pid:
            k += 1
            if seg:
                kr += add_recortes(c, pid, seg, "claude-app web")
    c.commit(); return {"pesquisas": k, "recortes": kr}


def stats(c):
    out = {"pesquisas": c.execute("SELECT COUNT(*) FROM pesquisas").fetchone()[0], "recortes": c.execute("SELECT COUNT(*) FROM recortes").fetchone()[0],
           "docs": dict(c.execute("SELECT tipo, COUNT(*) FROM docs GROUP BY tipo").fetchall()), "notas": c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]}
    out["lista"] = [dict(r) for r in c.execute("SELECT instituto, data_inicio, data_fim, n, registro_tse, lula_total, flavio_total, lula_validos, flavio_validos, rejeicao_lula, rejeicao_flavio, url_pdf FROM pesquisas ORDER BY data_fim DESC, instituto")]
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("arg", nargs="*")
    ap.add_argument("--url"); ap.add_argument("--fonte"); ap.add_argument("--data"); ap.add_argument("--outlet"); ap.add_argument("--titulo")
    a = ap.parse_args(); c = db()
    if a.cmd == "build":
        print(json.dumps(build(c)))
    elif a.cmd == "ingest-json":
        print(json.dumps(ingest_json(c, a.arg[0])))
    elif a.cmd == "ingest-doc":
        tipo, path = a.arg[0], a.arg[1]
        t = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout if path.endswith(".pdf") else open(path, encoding="utf-8", errors="ignore").read()
        add_doc(c, tipo, a.fonte or "manual", a.outlet, None, a.titulo or os.path.basename(path), a.url, path, a.data, t, {"chars": len(t)}); c.commit(); print("ok", len(t))
    elif a.cmd == "stats":
        print(json.dumps(stats(c), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
