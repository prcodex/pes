#!/usr/bin/env python3
"""c50 + rejeição (linha paralela; o c50 congelado não é tocado). claude-app 21/10.

Ideia: rejeição não é teto. "Alcançável" de um candidato = 100 − voto (totais) − rejeição = eleitores que não votam
nele hoje mas não o rejeitam. A diferença alcançável_L − alcançável_F (assimetria) é o upside relativo de Lula.
Ganho esperado de Lula em válidos = c · assimetria / 0,91, com a taxa de conversão c incerta (uniforme em [0, c_max]).
P(Lula) = média sobre c e sobre o erro das pesquisas N(0, σ) de 1[share_c50 + ganho + ε > 50].
Média da assimetria ponderada por recência: peso = n^0.5 · 0,5^(dias/meia_vida) (Pedro: mais peso às últimas).

uso: c50_rej.py add --instituto X --data_fim YYYY-MM-DD --lula_t 44 --flavio_t 45 --rej_l 47 --rej_f 52 [--bn 9] [--n 2154] [--url ...]
     c50_rej.py run            -> JSON do estado (lido pelo dash_export.py c50_rej)
     c50_rej.py list
"""
import os, sys, csv, json, math, argparse, subprocess, datetime as dt, random
BASE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(BASE, "data", "rejeicao.csv")
FIELDS = ["instituto", "data_fim", "lula_t", "flavio_t", "rej_l", "rej_f", "bn", "n", "url", "nota", "adicionado"]
MEIA_VIDA_DIAS = 3.0
C_MAX = 0.5
N_SIM = 200000
VALIDOS_SHARE = 0.91   # pool em % de respondentes -> pp de válidos


def load():
    if not os.path.exists(CSV):
        return []
    with open(CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("lula_t", "flavio_t", "rej_l", "rej_f", "bn", "n"):
            r[k] = float(r[k]) if r.get(k) not in (None, "") else None
        r["alc_l"] = 100 - r["lula_t"] - r["rej_l"]
        r["alc_f"] = 100 - r["flavio_t"] - r["rej_f"]
        r["assimetria"] = r["alc_l"] - r["alc_f"]
    return sorted(rows, key=lambda r: r["data_fim"])


def save(rows):
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in FIELDS})


def c50_state():
    try:
        o = json.loads(subprocess.run([sys.executable, os.path.join(BASE, "dash_export.py"), "c50"],
                                      capture_output=True, text=True, cwd=BASE, timeout=120).stdout)
        return {"share": o["share_media"], "sigma": o["sigma"], "p_c50": o["p"]["central"], "window": o.get("window")}
    except Exception as e:
        return {"share": None, "sigma": None, "p_c50": None, "erro": str(e)[:120]}


def run(as_of=None):
    rows = load()
    st = c50_state()
    today = dt.date.fromisoformat(as_of) if as_of else dt.datetime.utcnow().date()
    # uma por instituto (a mais recente), ponderada por recência e raiz de n
    latest = {}
    for r in rows:
        if r["instituto"] not in latest or r["data_fim"] > latest[r["instituto"]]["data_fim"]:
            latest[r["instituto"]] = r
    usadas = []
    for r in latest.values():
        dias = (today - dt.date.fromisoformat(r["data_fim"])).days
        w = math.sqrt(r["n"] or 2000) / math.sqrt(2000) * 0.5 ** (dias / MEIA_VIDA_DIAS)
        usadas.append({**r, "dias": dias, "peso": round(w, 3)})
    out = {"versao": "c50+rejeicao (paralelo)", "as_of": str(today), "meia_vida_dias": MEIA_VIDA_DIAS, "c_max": C_MAX,
           "c50": st, "pesquisas": usadas, "n_pesquisas": len(usadas)}
    if not usadas or st["share"] is None:
        out["p"] = None; return out
    W = sum(u["peso"] for u in usadas)
    asym = sum(u["peso"] * u["assimetria"] for u in usadas) / W
    alc_l = sum(u["peso"] * u["alc_l"] for u in usadas) / W
    alc_f = sum(u["peso"] * u["alc_f"] for u in usadas) / W
    rng = random.Random(7)
    share, sigma = st["share"], st["sigma"]
    def P(cmax):
        hits = 0
        for _ in range(N_SIM):
            c = rng.uniform(0, cmax); eps = rng.gauss(0, sigma)
            if share + c * asym / VALIDOS_SHARE + eps > 50: hits += 1
        return hits / N_SIM
    p50, p30 = P(C_MAX), P(0.3)
    out.update({"alcancavel_lula": round(alc_l, 2), "alcancavel_flavio": round(alc_f, 2), "assimetria": round(asym, 2),
                "ganho_esperado_pp_validos": round(0.5 * C_MAX * asym / VALIDOS_SHARE, 2),
                "p": {"central": round(p50, 3), "conversao_ate_30": round(p30, 3), "c50_sem_rejeicao": st["p_c50"]},
                "leitura": (f"Alcançável Lula {alc_l:.1f}% vs Flávio {alc_f:.1f}% (assimetria {asym:+.1f} pts, média ponderada por recência, "
                            f"meia-vida {MEIA_VIDA_DIAS:.0f} dias). Com conversão uniforme em [0, {C_MAX:.0%}], P(Lula) {p50:.0%} "
                            f"(c50 sem rejeição {st['p_c50']:.0%}).")})
    return out


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    for k in ("instituto", "data_fim", "url", "nota"): a.add_argument("--" + k, default="")
    for k in ("lula_t", "flavio_t", "rej_l", "rej_f", "bn", "n"): a.add_argument("--" + k, type=float, default=None)
    r = sub.add_parser("run"); r.add_argument("--as-of", default=None)
    sub.add_parser("list")
    x = ap.parse_args()
    if x.cmd == "add":
        rows = load()
        rows = [q for q in rows if not (q["instituto"] == x.instituto and q["data_fim"] == x.data_fim)]
        rows.append({"instituto": x.instituto, "data_fim": x.data_fim, "lula_t": x.lula_t, "flavio_t": x.flavio_t, "rej_l": x.rej_l,
                     "rej_f": x.rej_f, "bn": x.bn, "n": x.n, "url": x.url, "nota": x.nota, "adicionado": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"})
        save(sorted(rows, key=lambda q: q["data_fim"])); print(json.dumps({"ok": True, "n": len(rows)}))
    elif x.cmd == "list":
        for q in load(): print(q["data_fim"], q["instituto"], "L", q["lula_t"], "/", q["rej_l"], "->", q["alc_l"], "| F", q["flavio_t"], "/", q["rej_f"], "->", q["alc_f"], "| assim", q["assimetria"])
    else:
        print(json.dumps(run(x.as_of), ensure_ascii=False))


if __name__ == "__main__":
    main()
