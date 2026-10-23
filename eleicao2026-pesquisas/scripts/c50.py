#!/usr/bin/env python3
"""c50 — "Caminho dos 50%" (addendum 8, 19/10/2026): a live, DECLARED model of what Lula needs to reach 50% of the
valid votes on 25/10, recomputed every 6h window as polls, endorsements, events and turnout signals come in.
P(Lula) is "modelo c50 — parâmetros em c50_params.yaml", not an official forecast.

Tables (own; the existing tables are only read):
  c50_inputs  ledger: id, t_utc (when the information reached the model), tipo (poll | endorsement | event |
              turnout_signal | transfer), fonte, url, valor_json, nota, autor (+ chave unique, ativo)
  c50_queue   candidates from the classified media (polls_cited, apoio themes) waiting for a human: never in the model
  c50_daily   one row per window (hours 6; 1h on debate nights): P central/otimista/pessimista, poll average, levers,
              waterfall, sensitivities, decomposition of ΔP vs. the previous row, per-input effect. window
              'c50_baseline' = the frozen state of claude-app's map (19/10 12:14 BRT)

CLI (JSON on stdout unless noted):
  seed                      baseline facts (TSE 1st round, Quaest poll + crosstab, endorsements) + the registered polls
                            already in `polls` (t_utc ≈ publication), + the frozen c50_baseline row. Idempotent.
  ingest                    new rows of `polls` -> poll inputs (t_utc = now); labels (polls_cited, apoio themes) of the
                            last `fila.janela_h` h -> c50_queue. Cron every 2 h after classify.
  run [--window W|1h] [--dry]   score the last complete window (6h; --window 1h = last complete hour, debate nights)
                            -> c50_daily. --dry: compute and print, write nothing. No Telegram (pulse.py snapshot shows it).
  add --tipo T --json '{..}' [--fonte --url --nota --autor --t ISO]   manual input
  queue | accept QID --json '{..}' [--tipo T] | reject QID       the confirmation queue
  export [--hours 6]        full object (pulse_export.py c50 / dash_export.py c50 / pdf.py)
  block                     the Telegram block of the latest 6h row (plain text)
  backfill                  6h rows from `backfill_desde` to the last complete window (no sending)
  deactivate ID             ativo=0 for a ledger row (wrong input); the next run reflects it

Model (all numbers from c50_params.yaml + the ledger):
  share   Lula % of valid votes = recency×√n weighted mean of the TSE-registered polls whose fieldwork ended in the
          `janela_dias` before the end of the LATEST poll's fieldwork (latest per institute); so with no new poll the
          last average is kept and σ grows `incerteza_dia_pp`/day since that fieldwork ended.
  levers  net votes L − F (positive = good for Lula), min/central/max:
          terceiros     crosstab × 1st-round votes (+ endorsements made after the crosstab, `apoio_forca`)
          abstencao     Δpp fall of abstention × (aptos/100) × [(1−ne)·mix + ne·ne_net_por_eleitor]
          bn_indecisos  bloc (bn+ind of the latest stimulated poll × turnout) × conversão × (2·split − 1)
          persuasao     what is left: gap 1st round + terceiros − abstenção − bn = "o que falta"
  P       Monte Carlo (n, common seed): share ~ Normal(avg + leader_prior_pp + event shifts + lever adjustments not
          already in the polls [endorsements after the crosstab, abstention, bn split vs. proportional],
          σ = √(sampling² + erro_historico²) + staleness); levers drawn triangular(min, central, max).
          otimista / pessimista = levers fixed at the Lula-favourable / unfavourable end.
          P = share of draws with Lula > 50%.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import unicodedata

import numpy as np
import yaml

from common import BASE, db, iso, lock, now_utc

J = "c50"
PARAMS = os.path.join(BASE, "c50_params.yaml")
TIPOS = ("poll", "endorsement", "event", "turnout_signal", "transfer")
FOOTER = "modelo c50 — parâmetros em c50_params.yaml"
LEVERS = ("terceiros", "abstencao", "bn_indecisos")
LEVER_LABEL = {"terceiros": "terceiros", "abstencao": "abstenção", "bn_indecisos": "branco/nulo/indecisos",
               "persuasao": "persuasão"}
CAT_LABEL = {"tempo": "tempo sem pesquisa nova", "poll": "pesquisa nova", "transfer": "transferência nova",
             "endorsement": "apoio", "event": "evento", "turnout_signal": "abstenção", "params": "parâmetro"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS c50_inputs(id INTEGER PRIMARY KEY AUTOINCREMENT, t_utc TEXT, tipo TEXT, fonte TEXT,
  url TEXT, valor_json TEXT, nota TEXT, autor TEXT, chave TEXT UNIQUE, ativo INTEGER DEFAULT 1, criado TEXT);
CREATE TABLE IF NOT EXISTS c50_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, t_utc TEXT, tipo_sugerido TEXT,
  chave TEXT UNIQUE, titulo TEXT, n_itens INTEGER, dias TEXT, itens_json TEXT, status TEXT DEFAULT 'pendente',
  decidido_utc TEXT, input_id INTEGER, ids_json TEXT);
CREATE TABLE IF NOT EXISTS c50_daily(window TEXT, hours INTEGER, t_utc TEXT, cutoff TEXT, p_central REAL,
  p_otimista REAL, p_pessimista REAL, share_media REAL, margem_media REAL, sigma REAL, faltam_central REAL,
  faltam_otimista REAL, faltam_pessimista REAL, state_json TEXT, decomp_json TEXT, sensib_json TEXT,
  efeitos_json TEXT, params_json TEXT, backfill INTEGER DEFAULT 0, PRIMARY KEY(window, hours));
"""


# ---------------------------------------------------------------- small helpers
def elog(msg):
    print(f"[{now_utc():%Y-%m-%d %H:%M:%S}Z] {J}: {msg}", file=sys.stderr, flush=True)  # stdout stays JSON


def P_load():
    with open(PARAMS) as f:
        return yaml.safe_load(f)


def pdt(s):
    """'2026-10-19T15:14Z' / '...:00Z' / date -> aware datetime."""
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d\d-\d\d", s):
        s += "T00:00"
    s = s.rstrip("Z")
    if s.count(":") == 1:
        s += ":00"
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


def zs(d):
    return d.strftime("%Y-%m-%dT%H:%MZ")


def fim_campo(data_fim):
    """end of fieldwork = end of the BRT day = data_fim + 1 day 03:00Z."""
    return pdt(data_fim) + dt.timedelta(days=1, hours=3)


def norm_inst(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()
    return s


ALIAS = {"btg": "nexus", "aya": "poderdata", "broadcast": "indexa", "bloomberg": "atlasintel", "atlas": "atlasintel"}


def inst_key(raw, known):
    s = norm_inst(raw)
    parts = [p for p in re.split(r"[/\s,+&-]+", s) if p]
    for p in parts:
        if p in known:
            return p
    for p in parts:
        if p in ALIAS:
            return ALIAS[p]
    return s


def ensure(c):
    """CREATE TABLE one statement at a time (executescript would COMMIT an open transaction, e.g. in --dry)."""
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            c.execute(stmt)


def inputs(c, cutoff=None, only_active=True):
    q = "SELECT * FROM c50_inputs" + (" WHERE ativo=1" if only_active else "") + " ORDER BY t_utc, id"
    out = []
    for r in c.execute(q):
        d = dict(r)
        d["valor"] = json.loads(d["valor_json"] or "{}")
        if cutoff is None or pdt(d["t_utc"]) <= cutoff:
            out.append(d)
    return out


def add_input(c, tipo, valor, t_utc=None, fonte=None, url=None, nota=None, autor="c50", chave=None, commit=True):
    if tipo not in TIPOS:
        raise SystemExit(f"tipo must be one of {TIPOS}")
    t_utc = t_utc or zs(now_utc())
    chave = chave or f"{tipo}:" + hashlib.sha1(json.dumps(valor, sort_keys=True).encode()).hexdigest()[:12]
    cur = c.execute("INSERT OR IGNORE INTO c50_inputs(t_utc,tipo,fonte,url,valor_json,nota,autor,chave,ativo,criado) "
                    "VALUES(?,?,?,?,?,?,?,?,1,?)", (t_utc, tipo, fonte, url, json.dumps(valor, ensure_ascii=False),
                                                    nota, autor, chave, iso()))
    if commit:
        c.commit()
    return cur.lastrowid if cur.rowcount else None


# ---------------------------------------------------------------- seed (baseline of the handoff)
TSE = {"flavio": 56104503, "lula": 53879538,
       "terceiros": {"cury": 3448569, "renan": 2675887, "caiado": 2605148, "zema": 326488, "outros_resto": 260655},
       "comparecimento": 125275835, "aptos": 158745502, "abstencao": 33469244, "abstencao_pct": 21.08,
       "brancos": 2300798, "nulos": 3674249, "ne_lula": 21494584, "ne_lula_validos_pct": 63.77}
QUAEST_T = "2026-10-14T21:00Z"
SEED = [
    ("turnout_signal", "seed:tse-1turno", "2026-10-05T03:00Z", "TSE", "https://resultados.tse.jus.br/",
     {"resultado_1turno": TSE}, "Resultado oficial do 1º turno (04/10). Terceiros 9.316.747; pool ausentes+brancos+nulos 39,44M."),
    ("poll", "poll:quaest:2026-10-13", QUAEST_T, "Quaest",
     "https://www.poder360.com.br/poder-eleicoes-2026/flavio-tem-46-e-lula-tem-44-no-2o-turno-diz-quaest/",
     {"instituto": "Quaest", "campo": "10–13/10", "data_fim": "2026-10-13", "lula_v": 49.0, "flavio_v": 51.0,
      "registro_tse": "BR-08729/2026", "estimulada": {"f": 46, "l": 44, "ind": 1, "bn": 9}, "voto_definido": 91,
      "podem_mudar": 9, "rejeicao": {"f": 54, "l": 53}, "n": None},
     "Quaest 14/10: válidos F 51 × L 49; estimulada 46/44/1/9; 91% voto definido; rejeição F 54 / L 53."),
    ("transfer", "seed:quaest-transfer-2026-10-13", QUAEST_T, "Quaest",
     "https://www.poder360.com.br/poder-eleicoes-2026/flavio-tem-46-e-lula-tem-44-no-2o-turno-diz-quaest/",
     {"instituto": "Quaest", "campo_fim": "2026-10-13",
      "grupos": {"caiado": {"f": 42, "l": 23, "bn": 33}, "renan": {"f": 40, "l": 14, "bn": 43},
                 "cury": {"f": 30, "l": 34, "bn": 30}, "outros": {"f": 38, "l": 33, "bn": 22}},
      "pool_ausentes": {"l": 43, "f": 38, "nv": 17}},
     "Transferência Quaest (F/L/bn) por eleitor do 1º turno; ausentes+brancos+nulos 43 L / 38 F / 17 não vota."),
    ("endorsement", "seed:apoio-caiado", QUAEST_T, "baseline claude-app 19/10", None,
     {"quem": "Caiado", "para": "Flavio", "grupo": "caiado", "embutido_no_crosstab": True},
     "Apoio declarado a Flávio; assumido já presente no crosstab Quaest (campo 10–13/10)."),
    ("endorsement", "seed:apoio-cury", QUAEST_T, "baseline claude-app 19/10", None,
     {"quem": "Cury", "para": "Flavio", "grupo": "cury", "embutido_no_crosstab": True},
     "Apoio declarado a Flávio; assumido já presente no crosstab Quaest."),
    ("endorsement", "seed:apoio-zema", QUAEST_T, "baseline claude-app 19/10", None,
     {"quem": "Zema", "para": "Flavio", "grupo": "outros", "embutido_no_crosstab": True},
     "Apoio declarado a Flávio; assumido já presente no crosstab Quaest (grupo 'outros')."),
    ("event", "seed:renan-sem-apoio", QUAEST_T, "baseline claude-app 19/10", None,
     {"evento": "Renan Santos não declara apoio"}, "Sem efeito no modelo (marco)."),
    ("event", "seed:precedente-lider", "2026-10-05T03:00Z", "TSE (histórico 1989–2022)", None,
     {"evento": "Todo líder do 1º turno desde 1989 venceu o 2º"},
     "Marco; o efeito, se Pedro quiser, entra só por leader_prior_pp no yaml (padrão 0)."),
    ("turnout_signal", "seed:abstencao-2022", "2026-10-05T03:00Z", "TSE 2022", None,
     {"precedente": "2022: abstenção do 2º turno caiu 0,36pp vs. o 1º"},
     "Referência do prior de abstenção (central 0,3pp de queda, NE-ponderado)."),
]


def import_polls(c, initial, commit=True):
    """`polls` (collect.py <- polls_manual.csv) -> poll inputs. initial: t_utc ≈ publication (data_fim + 1 d 00Z);
    later: t_utc = now (when the poll reached the model, so the decomposition credits it to this window)."""
    n = 0
    for r in c.execute("SELECT * FROM polls ORDER BY data_fim"):
        chave = f"poll:{norm_inst(r['instituto'])}:{r['data_fim']}"
        if c.execute("SELECT 1 FROM c50_inputs WHERE chave=?", (chave,)).fetchone():
            continue
        t = zs(pdt(r["data_fim"]) + dt.timedelta(days=1)) if initial else zs(now_utc())
        v = {"instituto": r["instituto"], "data_fim": r["data_fim"], "lula_v": r["lula_v"], "flavio_v": r["flavio_v"],
             "registro_tse": r["registro_tse"], "n": None}
        if add_input(c, "poll", v, t, r["instituto"], r["fonte_url"], "importada de `polls` (polls_manual.csv)",
                     "c50 ingest", chave, commit=False):
            n += 1
    if commit:
        c.commit()
    return n


def seeded(c):
    """the ledger has the seed (c50 keeps its state in its own tables only: no `meta`, no `runs`)."""
    return c.execute("SELECT 1 FROM c50_inputs WHERE chave='seed:tse-1turno'").fetchone() is not None


def seed(c, commit=True):
    ensure(c)
    initial = not seeded(c)
    n = 0
    for tipo, chave, t, fonte, url, valor, nota in SEED:
        if add_input(c, tipo, valor, t, fonte, url, nota, "claude-app (handoff 8)", chave, commit=False):
            n += 1
    n_polls = import_polls(c, initial=initial, commit=False)
    if commit:
        c.commit()
    return {"seed_rows": n, "polls_imported": n_polls}


# ---------------------------------------------------------------- the model
def latest(rows, pred=lambda r: True):
    rs = [r for r in rows if pred(r)]
    return rs[-1] if rs else None


def tri(u, a, m, b):
    """inverse CDF of triangular(a, m, b) at uniforms u (vectorised); degenerate -> constant."""
    a, b = min(a, b), max(a, b)
    m = min(max(m, a), b)
    if b - a < 1e-12:
        return np.full_like(u, a)
    fc = (m - a) / (b - a)
    return np.where(u < fc, a + np.sqrt(u * (b - a) * (m - a)), b - np.sqrt((1 - u) * (b - a) * (b - m)))


def poll_average(polls, P, as_of):
    pp = P["polls"]
    rx = re.compile(pp["registro_regex"])
    reg = [p for p in polls if rx.match((p["valor"].get("registro_tse") or "").strip())
           and p["valor"].get("lula_v") is not None and p["valor"].get("flavio_v") is not None]
    excluded = [p["id"] for p in polls if p not in reg]
    if not reg:
        return None
    # The window and the recency weights are anchored at the end of the latest fieldwork, not at as_of: with no new
    # poll the average stays the same ("repete a última") and only sigma grows (incerteza_dia_pp); polls do not
    # age out one by one between releases.
    last_end = max(fim_campo(p["valor"]["data_fim"]) for p in reg)
    anchor = min(as_of, last_end)
    lo = anchor - dt.timedelta(days=pp["janela_dias"])
    win = [p for p in reg if fim_campo(p["valor"]["data_fim"]) >= lo]
    if pp.get("uma_por_instituto", True):
        by = {}
        for p in sorted(win, key=lambda p: (p["valor"]["data_fim"], p["t_utc"], p["id"])):
            by[norm_inst(p["valor"]["instituto"])] = p
        win = list(by.values())
    used, sw, sws, sw2se2 = [], 0.0, 0.0, 0.0
    for p in sorted(win, key=lambda p: p["valor"]["data_fim"]):
        v = p["valor"]
        s = 100 * v["lula_v"] / (v["lula_v"] + v["flavio_v"])
        n = v.get("n") or pp["n_padrao"]
        age = max(0.0, (anchor - fim_campo(v["data_fim"])).total_seconds() / 86400)
        w = 0.5 ** (age / pp["meia_vida_dias"]) * math.sqrt(n / pp["n_ref"])
        se = 100 * math.sqrt((s / 100) * (1 - s / 100) / (n * pp["fracao_validos"]))
        sw += w; sws += w * s; sw2se2 += (w * se) ** 2
        used.append({"id": p["id"], "instituto": v["instituto"], "data_fim": v["data_fim"], "lula": round(s, 2),
                     "n": n, "peso": w})
    for u in used:
        u["peso"] = round(u["peso"] / sw, 3)
    stale_days = max(0.0, (as_of - last_end).total_seconds() / 86400 - pp.get("carencia_dias", 0))
    return {"share": sws / sw, "se_amostral": math.sqrt(sw2se2) / sw, "usadas": used, "excluidas_sem_registro": excluded,
            "dias_sem_pesquisa": round(stale_days, 2), "ultima_fim_campo": zs(last_end)}


def compute_state(inp, P, as_of):
    """Everything except the Monte Carlo: poll average, levers (min/central/max), adjustments, waterfall."""
    tse_row = latest(inp, lambda r: r["tipo"] == "turnout_signal" and "resultado_1turno" in r["valor"])
    if not tse_row:
        raise RuntimeError("no TSE 1st-round row in c50_inputs (run `c50.py seed`)")
    T = tse_row["valor"]["resultado_1turno"]
    V = T["flavio"] + T["lula"] + sum(T["terceiros"].values())  # valid votes, 1st round
    groups = {"caiado": T["terceiros"]["caiado"], "renan": T["terceiros"]["renan"], "cury": T["terceiros"]["cury"],
              "outros": T["terceiros"]["zema"] + T["terceiros"]["outros_resto"]}
    polls = [r for r in inp if r["tipo"] == "poll"]
    pa = poll_average(polls, P, as_of)
    if pa is None:
        raise RuntimeError("no registered poll in c50_inputs")
    mu = pa["share"]
    estim = latest(polls, lambda r: r["valor"].get("estimulada"))
    rej = latest(polls, lambda r: r["valor"].get("rejeicao"))

    # --- terceiros
    tr = latest(inp, lambda r: r["tipo"] == "transfer" and r["valor"].get("grupos"))
    e = P["terceiros"]["erro_crosstab_pp"]
    terc = {"min": 0.0, "central": 0.0, "max": 0.0, "grupos": {}, "crosstab": None}
    if tr:
        terc["crosstab"] = {"id": tr["id"], "fonte": tr["fonte"], "campo_fim": tr["valor"].get("campo_fim")}
        for g, x in tr["valor"]["grupos"].items():
            vg = groups.get(g, 0)
            net = vg * (x["l"] - x["f"]) / 100
            terc["grupos"][g] = round(net)
            terc["central"] += net
            terc["min"] += vg * (x["l"] - x["f"] - e) / 100
            terc["max"] += vg * (x["l"] - x["f"] + e) / 100
    tr_end = fim_campo(tr["valor"]["campo_fim"]) if tr and tr["valor"].get("campo_fim") else None
    apoio_shift, apoios = 0.0, []
    for r in inp:
        if r["tipo"] != "endorsement":
            continue
        v = r["valor"]
        sign = 1 if norm_inst(v.get("para")) == "lula" else -1 if norm_inst(v.get("para")) in ("flavio", "flávio") else 0
        embutido = v.get("embutido_no_crosstab") or (tr_end is not None and pdt(r["t_utc"]) <= tr_end)
        g = v.get("grupo")
        if v.get("alcance_votos"):
            base = v["alcance_votos"] * (tr["valor"]["grupos"][g]["bn"] / 100 if tr and g in tr["valor"]["grupos"]
                                         else P["terceiros"]["apoio_bn_sem_grupo"])
        elif tr and g in tr["valor"]["grupos"]:
            base = groups.get(g, 0) * tr["valor"]["grupos"][g]["bn"] / 100
        else:
            base = 0.0
        forca = v.get("forca", P["terceiros"]["apoio_forca"])
        s = 0.0 if embutido else sign * forca * base
        apoio_shift += s
        apoios.append({"id": r["id"], "quem": v.get("quem"), "para": v.get("para"), "embutido": bool(embutido),
                       "shift_votos": round(s)})
    # endorsements after the crosstab: triangular(0, s, 2s) — they are the only part of this lever not in the polls
    terc["ajuste"] = {"min": min(0.0, 2 * apoio_shift), "central": apoio_shift, "max": max(0.0, 2 * apoio_shift)}
    for k in ("min", "central", "max"):
        terc[k] += terc["ajuste"][k]
    terc["apoios"] = apoios

    # --- abstenção
    ab = copy.deepcopy(P["abstencao"])
    ts = latest(inp, lambda r: r["tipo"] == "turnout_signal" and ("abst_pp_delta" in r["valor"] or "ne_share" in r["valor"]))
    if ts:
        for k_in, k_p in (("abst_pp_delta", "delta_pp"), ("ne_share", "ne_share")):
            if k_in in ts["valor"]:
                ab[k_p].update(ts["valor"][k_in])
    pool = (tr["valor"].get("pool_ausentes") if tr else None) or {"l": 50, "f": 50}
    mix = (pool["l"] - pool["f"]) / (pool["l"] + pool["f"])
    per_pp = T["aptos"] / 100
    rate = lambda ne: (1 - ne) * mix + ne * ab["ne_net_por_eleitor"]  # noqa: E731
    abst = {"central": ab["delta_pp"]["central"] * per_pp * rate(ab["ne_share"]["central"]),
            "max": ab["delta_pp"]["max"] * per_pp * rate(ab["ne_share"]["max"]),
            "min": ab["delta_pp"]["min"] * per_pp * rate(ab["ne_share"]["min"] if ab["delta_pp"]["min"] >= 0
                                                         else ab["ne_share"]["max"] if mix > ab["ne_net_por_eleitor"]
                                                         else ab["ne_share"]["min"]),
            "por_pp_mix": per_pp * mix, "por_pp_ne": per_pp * ab["ne_net_por_eleitor"],
            "teto_teorico": (T["abstencao"] + T["brancos"] + T["nulos"]) * (pool["l"] - pool["f"]) / 100,
            "pool": T["abstencao"] + T["brancos"] + T["nulos"], "prior": ab,
            "sinal": ts["id"] if ts else None}
    abst["ajuste"] = {k: abst[k] for k in ("min", "central", "max")}

    # --- branco/nulo/indecisos
    bp = P["bn_indecisos"]
    es = (estim or {}).get("valor", {}).get("estimulada") or {"bn": 9, "ind": 1}
    bloc = (es.get("bn", 0) + es.get("ind", 0)) / 100 * T["comparecimento"]
    q_c = mu / 100 if bp["split_lula"]["central"] == "poll" else float(bp["split_lula"]["central"])
    bn = {"bloco": bloc, "q": {"min": bp["split_lula"]["min"], "central": q_c, "max": bp["split_lula"]["max"]},
          "conv": dict(bp["conversao"]), "fonte": (estim or {}).get("fonte")}
    net_bn = lambda c_, q: bloc * c_ * (2 * q - 1)  # noqa: E731
    bn["central"] = net_bn(bp["conversao"]["central"], q_c)
    bn["max"] = net_bn(bp["conversao"]["max"], bp["split_lula"]["max"])
    bn["min"] = net_bn(bp["conversao"]["max"], bp["split_lula"]["min"])

    # --- events with an explicit (manual) effect on the share
    ev = [r for r in inp if r["tipo"] == "event"]
    ev_shift = sum(float(r["valor"].get("efeito_pp") or 0) for r in ev)

    # --- waterfall (central and ends), in votes; gap = F − L
    gap1 = T["flavio"] - T["lula"]
    wf = {}
    for k, kt in (("central", "central"), ("otimista", "max"), ("pessimista", "min")):
        g = gap1 - terc[kt] - abst[kt] - bn[kt]
        wf[k] = {"gap_1turno": gap1, "terceiros": -terc[kt], "abstencao": -abst[kt], "bn_indecisos": -bn[kt],
                 "persuasao_restante": g, "eleitores_a_virar": max(0, math.ceil(g / 2) + 1) if g > 0 else 0}
    gap_poll = V * (100 - 2 * mu) / 100
    rejf = (rej or {}).get("valor", {}).get("rejeicao")
    return {"as_of": zs(as_of), "V": V, "mu": mu, "polls": pa, "terceiros": terc, "abstencao": abst, "bn_indecisos": bn,
            "evento_pp": ev_shift, "waterfall": wf, "gap_pesquisas": gap_poll, "tse_id": tse_row["id"],
            "estimulada": es, "rejeicao": rejf,
            "teto_rejeicao_lula_votantes": None,  # removed 19/10 review: rejection is % of respondents, not a ceiling of valid votes
            "sigma_base": math.sqrt(pa["se_amostral"] ** 2 + P["erro_historico_pp"] ** 2),
            # claude-app 19/10 review: staleness in quadrature (sqrt(dias)), not added linearly to sigma
            "sigma": math.sqrt(pa["se_amostral"] ** 2 + P["erro_historico_pp"] ** 2
                               + (P["polls"]["incerteza_dia_pp"] * math.sqrt(max(0.0, pa["dias_sem_pesquisa"]))) ** 2)}


def draws(P):
    rng = np.random.default_rng(P["monte_carlo"]["seed"])
    n = P["monte_carlo"]["n"]
    return {"z": rng.standard_normal(n), "u_terc": rng.random(n), "u_abd": rng.random(n), "u_abn": rng.random(n),
            "u_conv": rng.random(n), "u_q": rng.random(n)}


def p_lula(st, P, mode="central", dmu=0.0, bn_q=None, R=None):
    """P(Lula > 50% of valid votes). mode central: levers triangular; otimista/pessimista: fixed at the ends."""
    R = R or draws(P)
    V = st["V"]
    to_pp = 100 / (2 * V)
    t, a, b = st["terceiros"]["ajuste"], st["abstencao"], st["bn_indecisos"]
    if mode == "central":
        adj_t = tri(R["u_terc"], t["min"], t["central"], t["max"]) * to_pp
        pr = a["prior"]
        d = tri(R["u_abd"], pr["delta_pp"]["min"], pr["delta_pp"]["central"], pr["delta_pp"]["max"])
        ne = tri(R["u_abn"], pr["ne_share"]["min"], pr["ne_share"]["central"], pr["ne_share"]["max"])
        rate = (1 - ne) * (a["por_pp_mix"]) + ne * a["por_pp_ne"]
        adj_a = d * rate * to_pp
        conv = tri(R["u_conv"], b["conv"]["min"], b["conv"]["central"], b["conv"]["max"])
        qc = b["q"]["central"] if bn_q is None else bn_q
        q = tri(R["u_q"], min(b["q"]["min"], qc), qc, max(b["q"]["max"], qc)) if bn_q is None else np.full_like(conv, bn_q)
    else:
        k = "max" if mode == "otimista" else "min"
        adj_t = np.full_like(R["z"], t[k] * to_pp)
        adj_a = np.full_like(R["z"], a[k] * to_pp)
        conv = np.full_like(R["z"], b["conv"]["max"])
        q = np.full_like(R["z"], b["q"][k] if bn_q is None else bn_q)
    mu = st["mu"] + dmu
    bc = b["bloco"] * conv
    share0 = mu + P.get("leader_prior_pp", 0.0) + st["evento_pp"] + adj_t + adj_a
    share = (share0 * V + 100 * q * bc) / (V + bc)  # bn converted at split q (q = mu/100 -> no change)
    share = share + st["sigma"] * R["z"]
    return float(np.mean(share > 50.0))


def sensitivities(st, P, R, p0):
    S = P["sensibilidades"]
    es = st["estimulada"]
    L, F = es.get("l", 44), es.get("f", 46)
    r = S["rejeicao_para_lula"]
    d_rej = 100 * (L + r) / (L + F - 1 + r) - 100 * L / (L + F)
    to_pp = 100 / (2 * st["V"])
    d_ne = st["abstencao"]["por_pp_ne"] * to_pp
    d_t = S["terceiros_neutralizados"] * to_pp
    out = [{"chave": "rejeicao_flavio_+1pp", "label": "+1pp de rejeição do Flávio",
            "premissa": f"1pp dos eleitores sai do Flávio; {int(100 * r)}% vai a Lula, o resto a branco/nulo",
            "d_share_pp": d_rej, "dP": p_lula(st, P, dmu=d_rej, R=R) - p0},
           {"chave": "abstencao_ne_-1pp", "label": "−1pp de abstenção, toda no NE",
            "premissa": f"+{st['abstencao']['por_pp_ne'] / P['abstencao']['ne_net_por_eleitor'] / 1e6:.2f}M votantes "
                        f"do NE, líquido {st['abstencao']['por_pp_ne'] / 1e6:+.2f}M L",
            "d_share_pp": d_ne, "dP": p_lula(st, P, dmu=d_ne, R=R) - p0},
           {"chave": "terceiros_500k", "label": f"{S['terceiros_neutralizados'] / 1e3:.0f}k de terceiros neutralizados",
            "premissa": "a vantagem líquida de Flávio entre eleitores de terceiros cai 500k votos",
            "d_share_pp": d_t, "dP": p_lula(st, P, dmu=d_t, R=R) - p0},
           {"chave": "bn_60_40", "label": "bloco branco/nulo/indeciso 60/40 para Lula",
            "premissa": f"conversão central {int(100 * st['bn_indecisos']['conv']['central'])}% de "
                        f"{st['bn_indecisos']['bloco'] / 1e6:.1f}M, split 60/40",
            "d_share_pp": None, "dP": p_lula(st, P, bn_q=S["bn_split"], R=R) - p0},
           {"chave": "pesquisas_+1pp", "label": "+1pp de Lula na média das pesquisas", "premissa": "nova média",
            "d_share_pp": 1.0, "dP": p_lula(st, P, dmu=1.0, R=R) - p0}]
    for o in out:
        o["dP"] = round(o["dP"], 4)
        if o["d_share_pp"] is not None:
            o["d_share_pp"] = round(o["d_share_pp"], 3)
    return out


def tornado(st, P, R):
    """P with one lever at its min / max end (others drawn as in the central run): which variable moves P most."""
    out = []
    to_pp = 100 / (2 * st["V"])
    for k in ("terceiros", "abstencao"):
        aj = st[k]["ajuste"]
        lo = p_lula(st, P, dmu=(aj["min"] - aj["central"]) * to_pp, R=R)
        hi = p_lula(st, P, dmu=(aj["max"] - aj["central"]) * to_pp, R=R)
        out.append({"variavel": LEVER_LABEL[k], "p_min": round(lo, 4), "p_max": round(hi, 4)})
    b = st["bn_indecisos"]
    out.append({"variavel": LEVER_LABEL["bn_indecisos"], "p_min": round(p_lula(st, P, bn_q=b["q"]["min"], R=R), 4),
                "p_max": round(p_lula(st, P, bn_q=b["q"]["max"], R=R), 4)})
    s = st["sigma"]
    out.append({"variavel": "pesquisas (±1σ de erro)", "p_min": round(p_lula(st, P, dmu=-s, R=R), 4),
                "p_max": round(p_lula(st, P, dmu=s, R=R), 4)})
    for o in out:
        o["amplitude"] = round(o["p_max"] - o["p_min"], 4)
    return sorted(out, key=lambda o: -o["amplitude"])


def full(inp, P, as_of, R=None):
    R = R or draws(P)
    st = compute_state(inp, P, as_of)
    p = {m: p_lula(st, P, m, R=R) for m in ("central", "otimista", "pessimista")}
    return st, p


def decompose(c, P, prev, cutoff, as_of, R):
    """ΔP vs. the previous row, by sequential replacement (same draws): tempo -> poll -> transfer -> endorsement ->
    event -> turnout_signal -> params. Each step swaps in the new inputs of one type."""
    if not prev:
        return None
    pP = json.loads(prev["params_json"])
    pcut, pas = pdt(prev["cutoff"]), pdt(json.loads(prev["state_json"])["as_of"])
    old, new = inputs(c, pcut), inputs(c, cutoff)
    Rp = draws(pP)
    try:
        base = full(old, pP, pas, Rp)[1]["central"]
    except Exception:
        return None
    steps, cur_inp, last = [], list(old), base
    order = ["tempo", "poll", "transfer", "endorsement", "event", "turnout_signal", "params"]
    new_ids = {r["id"] for r in new} - {r["id"] for r in old}
    gone_ids = {r["id"] for r in old} - {r["id"] for r in new}
    for k in order:
        if k == "tempo":
            pp, a_t = pP, as_of
        elif k == "params":
            pp, a_t = P, as_of
        else:
            cur_inp = [r for r in cur_inp if not (r["tipo"] == k and r["id"] in gone_ids)] + \
                      [r for r in new if r["tipo"] == k and r["id"] in new_ids]
            cur_inp.sort(key=lambda r: (r["t_utc"], r["id"]))
            pp, a_t = pP, as_of
        try:
            pv = full(cur_inp, pp, a_t, Rp if pp is pP else R)[1]["central"]
        except Exception:
            pv = last
        items = [{"id": r["id"], "fonte": r["fonte"], "resumo": resumo(r)} for r in new if r["tipo"] == k
                 and r["id"] in new_ids] if k not in ("tempo", "params") else []
        steps.append({"cat": k, "label": CAT_LABEL[k], "dP": round(pv - last, 4), "itens": items})
        last = pv
    return {"vs_window": prev["window"], "p_anterior": round(base, 4), "p_atual": round(last, 4),
            "dP": round(last - base, 4), "passos": steps}


def resumo(r):
    v = r["valor"]
    if r["tipo"] == "poll":
        reg = re.match(r"^[A-Z]{2}-\d{5}/20\d\d$", (v.get("registro_tse") or "").strip())
        return (("" if reg else "[sem registro TSE, fora do modelo] ") + f"{v.get('instituto')} {v.get('data_fim', '')[8:10]}/{v.get('data_fim', '')[5:7]} "
                f"L {v.get('lula_v'):g} × F {v.get('flavio_v'):g}".replace(".", ","))
    if r["tipo"] == "endorsement":
        return f"{v.get('quem')} apoia {str(v.get('para')).replace('Flavio', 'Flávio')}"
    if r["tipo"] == "event":
        return str(v.get("evento") or r["nota"] or "")[:80]
    if r["tipo"] == "transfer":
        return f"crosstab {v.get('instituto')} {v.get('campo_fim', '')}"
    if "resultado_1turno" in v:
        return "TSE 1º turno"
    if "abst_pp_delta" in v or "ne_share" in v:
        d = v.get("abst_pp_delta") or {}
        return f"sinal de abstenção: queda central {d.get('central', '—')}pp" + (f", NE {v['ne_share'].get('central')}" if v.get("ne_share") else "")
    return str(v.get("precedente") or r["nota"] or "")[:80]


def effects(c, inp, P, as_of, R, p0, k=10):
    """effect of each of the last k inputs = P(all) − P(all but this one)."""
    out = []
    for r in sorted(inp, key=lambda r: (r["t_utc"], r["id"]))[-k:][::-1]:
        try:
            pm = full([x for x in inp if x["id"] != r["id"]], P, as_of, R)[1]["central"]
            eff = round(p0 - pm, 4)
        except Exception:
            eff = None
        out.append({"id": r["id"], "t_utc": r["t_utc"], "tipo": r["tipo"], "fonte": r["fonte"], "resumo": resumo(r),
                    "efeito_dP": eff, "url": r["url"]})
    return out


def last_complete(hours):
    n = now_utc()
    if hours == 1:
        return n.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
    h = (n.hour // 6) * 6
    return n.replace(hour=h, minute=0, second=0, microsecond=0) - dt.timedelta(hours=6)


def run(c, window=None, hours=6, dry=False, backfill=False, commit=True, as_of=None, label=None):
    """Score one window: cutoff = as_of = window end (inputs known by then)."""
    ensure(c)
    P = P_load()
    w = pdt(window) if window else last_complete(hours)
    as_of = as_of or (w + dt.timedelta(hours=hours))
    wkey = label or zs(w)
    R = draws(P)
    inp = inputs(c, as_of)
    st, p = full(inp, P, as_of, R)
    prev = c.execute("SELECT * FROM c50_daily WHERE hours=? AND window<? AND window NOT LIKE 'c50_%' "
                     "ORDER BY window DESC LIMIT 1", (hours, wkey)).fetchone() if not label else None
    dec = decompose(c, P, dict(prev) if prev else None, as_of, as_of, R)
    sens = sensitivities(st, P, R, p["central"])
    st["tornado"] = tornado(st, P, R)
    eff = effects(c, inp, P, as_of, R, p["central"])
    st["inputs_ids"] = [r["id"] for r in inp]
    wf = st["waterfall"]
    row = (wkey, hours, iso(), zs(as_of), p["central"], p["otimista"], p["pessimista"], st["mu"], 2 * st["mu"] - 100,
           st["sigma"], wf["central"]["persuasao_restante"], wf["otimista"]["persuasao_restante"],
           wf["pessimista"]["persuasao_restante"], json.dumps(st, ensure_ascii=False, default=float),
           json.dumps(dec, ensure_ascii=False), json.dumps(sens, ensure_ascii=False),
           json.dumps(eff, ensure_ascii=False), json.dumps(P, ensure_ascii=False), 1 if backfill else 0)
    if not dry:
        c.execute("INSERT OR REPLACE INTO c50_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        if commit:
            c.commit()
    return {"window": wkey, "hours": hours, "cutoff": zs(as_of), "p": {k: round(v, 4) for k, v in p.items()},
            "share_media": round(st["mu"], 3), "sigma": round(st["sigma"], 3),
            "faltam": {k: round(v["persuasao_restante"]) for k, v in wf.items()},
            "decomp": dec, "sensib": sens, "tornado": st["tornado"], "dry": dry}


# ---------------------------------------------------------------- queue (media -> candidates; never the model)
def item_info(c, item_id, item_type):
    if item_type == "article":
        r = c.execute("SELECT title, url, outlet FROM articles WHERE id=?", (item_id[2:],)).fetchone()
    elif item_type == "gdelt":
        r = c.execute("SELECT title, url, outlet FROM gdelt_articles WHERE id=?", (item_id[2:],)).fetchone()
    else:
        vid = item_id.split(":")[1]
        r = c.execute("SELECT title, 'https://youtu.be/' || id, channel FROM videos WHERE id=?", (vid,)).fetchone()
    return {"id": item_id, "titulo": (r[0] or "")[:140] if r else "", "url": r[1] if r else None,
            "veiculo": r[2] if r else None}


def ingest(c, commit=True):
    ensure(c)
    P = P_load()
    fq = P["fila"]
    n_polls = import_polls(c, initial=not seeded(c), commit=False)
    since = (now_utc() - dt.timedelta(hours=fq["janela_h"])).strftime("%Y-%m-%d")
    led = [r for r in inputs(c, None) if r["tipo"] == "poll"]
    known = {norm_inst(r["valor"]["instituto"]): r for r in led}
    last_df = {}
    for r in led:
        k = norm_inst(r["valor"]["instituto"])
        last_df[k] = max(last_df.get(k, ""), r["valor"]["data_fim"])
    cites = {}
    for r in c.execute("SELECT item_id, item_type, day, polls_cited FROM labels WHERE model='haiku' AND day>=? "
                       "AND polls_cited IS NOT NULL AND polls_cited NOT IN ('', '[]')", (since,)):
        try:
            lst = json.loads(r["polls_cited"])
        except Exception:
            continue
        for raw in {inst_key(x, known) for x in lst if x}:
            cites.setdefault((raw, r["day"]), []).append((r["item_id"], r["item_type"]))
        for x in lst:
            k = inst_key(x, known)
            cites.setdefault(("__raw__", k), []).append(x)
    raw_names = {k[1]: max(set(v), key=v.count) for k, v in cites.items() if k[0] == "__raw__"}
    n_new, n_upd = 0, 0
    for (inst, day), items in sorted(((k, v) for k, v in cites.items() if k[0] != "__raw__"), key=lambda kv: kv[0][1]):
        uniq = list(dict.fromkeys(i for i, _ in items))
        if len(uniq) < fq["min_itens"]:
            continue
        ld = last_df.get(inst)
        if ld and pdt(ld) >= pdt(day) - dt.timedelta(days=fq["conhecida_dias"]):
            continue  # most likely the poll already in the ledger
        types = dict(items)
        prev = c.execute("SELECT * FROM c50_queue WHERE tipo_sugerido='poll' AND chave LIKE ? AND status='pendente' "
                         "ORDER BY id DESC LIMIT 1", (f"poll:{inst}:%",)).fetchone()
        if prev and pdt(json.loads(prev["dias"])[-1]) >= pdt(day) - dt.timedelta(days=2):
            dias = sorted(set(json.loads(prev["dias"]) + [day]))
            its = json.loads(prev["itens_json"])
            ids = list(dict.fromkeys(json.loads(prev["ids_json"] or "[]") + uniq))
            have = {i["id"] for i in its}
            its += [item_info(c, i, types[i]) for i in uniq if i not in have][:max(0, 6 - len(its))]
            n_it = len(ids)
            if n_it == prev["n_itens"] and dias == json.loads(prev["dias"]):
                continue
            tit = (f"possível pesquisa nova: {raw_names.get(inst, inst)} (citada por {n_it} itens em "
                   f"{dias[0][8:]}/{dias[0][5:7]}–{dias[-1][8:]}/{dias[-1][5:7]}; última no ledger: {ld or 'nenhuma'})")
            c.execute("UPDATE c50_queue SET dias=?, itens_json=?, n_itens=?, t_utc=?, titulo=?, ids_json=? WHERE id=?",
                      (json.dumps(dias), json.dumps(its, ensure_ascii=False), n_it, iso(), tit, json.dumps(ids), prev["id"]))
            n_upd += 1
            continue
        if c.execute("SELECT 1 FROM c50_queue WHERE chave=?", (f"poll:{inst}:{day}",)).fetchone():
            continue
        nome = raw_names.get(inst, inst)
        tit = (f"possível pesquisa nova: {nome} (citada por {len(uniq)} itens em {day[8:]}/{day[5:7]}; "
               f"última no ledger: {ld or 'nenhuma'})")
        c.execute("INSERT INTO c50_queue(t_utc,tipo_sugerido,chave,titulo,n_itens,dias,itens_json,status,ids_json) "
                  "VALUES(?,?,?,?,?,?,?,'pendente',?)",
                  (iso(), "poll", f"poll:{inst}:{day}", tit, len(uniq), json.dumps([day]),
                   json.dumps([item_info(c, i, types[i]) for i in uniq[:6]], ensure_ascii=False), json.dumps(uniq)))
        n_new += 1
    # apoio themes: one candidate per (free-text theme, day) with ≥ min_itens items
    ph = ",".join("?" * len(fq["temas_apoio"]))
    for r in c.execute(f"SELECT tema, day, COUNT(DISTINCT item_id) n, GROUP_CONCAT(item_id || '|' || item_type) its "
                       f"FROM labels WHERE model='haiku' AND day>=? AND tema_slug IN ({ph}) GROUP BY tema, day "
                       f"HAVING n>=?", (since, *fq["temas_apoio"], fq["min_itens"])).fetchall():
        chave = f"endorsement:{norm_inst(r['tema'])}:{r['day']}"
        its = list(dict.fromkeys(x.split("|")[0] for x in r["its"].split(",")))
        types = dict(x.split("|") for x in r["its"].split(","))
        ex = c.execute("SELECT id, n_itens, status FROM c50_queue WHERE chave=?", (chave,)).fetchone()
        if ex:
            if ex["status"] == "pendente" and ex["n_itens"] != r["n"]:
                c.execute("UPDATE c50_queue SET n_itens=?, t_utc=? WHERE id=?", (r["n"], iso(), ex["id"]))
                n_upd += 1
            continue
        c.execute("INSERT INTO c50_queue(t_utc,tipo_sugerido,chave,titulo,n_itens,dias,itens_json,status) "
                  "VALUES(?,?,?,?,?,?,?,'pendente')",
                  (iso(), "endorsement", chave, f"tema de apoio: {r['tema']} ({r['n']} itens em {r['day'][8:]}/{r['day'][5:7]})",
                   r["n"], json.dumps([r["day"]]),
                   json.dumps([item_info(c, i, types[i]) for i in its[:6]], ensure_ascii=False)))
        n_new += 1
    if commit:
        c.commit()
    elog(f"ingest: polls {n_polls}, queue new {n_new}, updated {n_upd}")
    return {"polls_imported": n_polls, "queue_new": n_new, "queue_updated": n_upd,
            "queue_pendente": c.execute("SELECT COUNT(*) FROM c50_queue WHERE status='pendente'").fetchone()[0]}


def queue_rows(c, status="pendente", limit=50):
    out = []
    for r in c.execute("SELECT * FROM c50_queue WHERE status=? ORDER BY n_itens DESC, id DESC LIMIT ?", (status, limit)):
        d = dict(r)
        d["dias"] = json.loads(d["dias"] or "[]")
        d["itens"] = json.loads(d.pop("itens_json") or "[]")
        d.pop("ids_json", None)
        out.append(d)
    return out


# ---------------------------------------------------------------- export / block
def pct(x, d=0):
    return "n/d" if x is None else f"{100 * x:.{d}f}%".replace(".", ",")


def sgn_pp(dp):
    v = round(100 * dp)
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v)}pp"


def mvotes(x, d=2):
    return f"{x / 1e6:.{d}f}M".replace(".", ",")


def export(c, hours=6, n_series=60):
    ensure(c)
    rows = [dict(r) for r in c.execute("SELECT * FROM c50_daily WHERE hours=? AND window NOT LIKE 'c50_%' "
                                       "ORDER BY window", (hours,))]
    base = c.execute("SELECT * FROM c50_daily WHERE window='c50_baseline'").fetchone()
    if not rows and not base:
        return {"ok": False, "reason": "no c50_daily rows (run c50.py run)", "rodape": FOOTER}
    cur = rows[-1] if rows else dict(base)
    st = json.loads(cur["state_json"])
    wf = st["waterfall"]["central"]
    series = [{"window": r["window"], "p": round(r["p_central"], 4), "p_otim": round(r["p_otimista"], 4),
               "p_pess": round(r["p_pessimista"], 4), "share": round(r["share_media"], 2),
               "margem": round(r["margem_media"], 2), "faltam": round(r["faltam_central"])} for r in rows[-n_series:]]
    lev = {k: {x: round(st[k][x]) for x in ("min", "central", "max")} for k in LEVERS}
    agenda = next_inputs(c, P_load())
    eff = {e["id"]: e["efeito_dP"] for e in json.loads(cur["efeitos_json"] or "[]")}
    since7 = pdt(cur["cutoff"]) - dt.timedelta(days=7)
    semana = [{"id": r["id"], "t_utc": r["t_utc"], "tipo": r["tipo"], "fonte": r["fonte"], "resumo": resumo(r),
               "efeito_dP": eff.get(r["id"])} for r in inputs(c, pdt(cur["cutoff"])) if pdt(r["t_utc"]) >= since7]
    pol = st["polls"]
    out = {"ok": True, "window": cur["window"], "hours": cur["hours"], "cutoff": cur["cutoff"], "rodape": FOOTER,
           "p": {"central": round(cur["p_central"], 4), "otimista": round(cur["p_otimista"], 4),
                 "pessimista": round(cur["p_pessimista"], 4)},
           "share_media": round(cur["share_media"], 2), "margem_media": round(cur["margem_media"], 2),
           "sigma": round(cur["sigma"], 2), "dias_sem_pesquisa": pol["dias_sem_pesquisa"],
           "pesquisas_usadas": pol["usadas"], "excluidas_sem_registro": pol["excluidas_sem_registro"],
           "series": series,
           "waterfall": [{"etapa": "gap 1º turno (F − L)", "votos": round(wf["gap_1turno"])},
                         {"etapa": "terceiros", "votos": round(wf["terceiros"])},
                         {"etapa": "abstenção", "votos": round(wf["abstencao"])},
                         {"etapa": "branco/nulo/indecisos", "votos": round(wf["bn_indecisos"])},
                         {"etapa": "persuasão restante", "votos": round(wf["persuasao_restante"]), "total": True}],
           "faltam": {k: round(v["persuasao_restante"]) for k, v in st["waterfall"].items()},
           "eleitores_a_virar": wf["eleitores_a_virar"], "gap_pesquisas": round(st["gap_pesquisas"]),
           "alavancas": lev, "terceiros_grupos": st["terceiros"]["grupos"], "apoios": st["terceiros"]["apoios"],
           "abstencao_ref": {"por_pp_mix": round(st["abstencao"]["por_pp_mix"]),
                             "por_pp_ne": round(st["abstencao"]["por_pp_ne"]),
                             "teto_teorico": round(st["abstencao"]["teto_teorico"]),
                             "pool": st["abstencao"]["pool"]},
           "bn_bloco": round(st["bn_indecisos"]["bloco"]),
           "rejeicao": st["rejeicao"],
           "sensib": json.loads(cur["sensib_json"]), "tornado": st.get("tornado"),
           "decomp": json.loads(cur["decomp_json"]) if cur["decomp_json"] else None,
           "inputs_recentes": json.loads(cur["efeitos_json"] or "[]"), "inputs_semana": semana[::-1],
           "queue": [{"id": q["id"], "tipo": q["tipo_sugerido"], "titulo": q["titulo"], "n_itens": q["n_itens"],
                      "dias": q["dias"], "exemplo": (q["itens"][0] if q["itens"] else None)}
                     for q in queue_rows(c, limit=12)],
           "queue_pendentes": c.execute("SELECT COUNT(*) FROM c50_queue WHERE status='pendente'").fetchone()[0],
           "proximo_insumo": agenda,
           "baseline": None if not base else {"p": round(base["p_central"], 4), "p_otim": round(base["p_otimista"], 4),
                                              "p_pess": round(base["p_pessimista"], 4),
                                              "share": round(base["share_media"], 2),
                                              "faltam": round(base["faltam_central"]), "as_of": base["cutoff"]},
           "params": {k: json.loads(cur["params_json"])[k] for k in ("erro_historico_pp", "leader_prior_pp")}}
    return out


def next_inputs(c, P):
    q = c.execute("SELECT titulo, n_itens FROM c50_queue WHERE status='pendente' AND tipo_sugerido='poll' "
                  "ORDER BY n_itens DESC LIMIT 1").fetchone()
    n = now_utc()
    ag = next((a for a in P.get("agenda") or [] if pdt(a["t"]) > n), None)
    return {"fila": q["titulo"] if q else None,
            "agenda": None if not ag else {"label": ag["label"], "t": ag["t"], "confirmado": ag.get("confirmado")}}


def block(c, hours=6):
    """Telegram block (≤ 450 chars), from the latest stored row."""
    ensure(c)
    rows = c.execute("SELECT * FROM c50_daily WHERE hours=? AND window NOT LIKE 'c50_%' ORDER BY window DESC LIMIT 2",
                     (hours,)).fetchall()
    if not rows:
        return "🎯 Caminho dos 50%: sem dados\n" + FOOTER
    cur = rows[0]
    st = json.loads(cur["state_json"])
    dec = json.loads(cur["decomp_json"]) if cur["decomp_json"] else None
    wd = pdt(cur["window"])
    if dec:
        dP = dec["dP"]
        top = max(dec["passos"], key=lambda s: abs(s["dP"]))
        why = "sem insumo novo" if abs(dP) < 0.005 and not any(s["itens"] for s in dec["passos"]) else (
            top["label"] + (f" ({top['itens'][0]['resumo']})" if top["itens"] else ""))
        pv = pdt(dec["vs_window"])
        dtxt = f" ({sgn_pp(dP)} vs {pv:%d/%m %H}Z: {why[:70]})"
    else:
        dtxt = ""
    nx = next_inputs(c, P_load())
    prox = (nx["agenda"]["label"] if nx["agenda"] else "—")
    fila = c.execute("SELECT COUNT(*) FROM c50_queue WHERE status='pendente'").fetchone()[0]
    lines = [f"🎯 Caminho dos 50% ({wd:%d/%m %H}Z)",
             f"P(Lula) {pct(cur['p_central'])}{dtxt} · otim. {pct(cur['p_otimista'])} / pess. {pct(cur['p_pessimista'])}",
             f"Pesquisas: L {cur['share_media']:.1f}% ({cur['margem_media']:+.1f}pp vs F) → gap ≈{mvotes(st['gap_pesquisas'])} "
             f"votos · σ {cur['sigma']:.1f}pp".replace(".", ","),
             f"próximo: {prox}" + (f" · fila: {fila}" if fila else ""),  # addendum 10: lever/sensitivity clause cut
             FOOTER]
    msg = "\n".join(lines)
    if len(msg) > 450:  # shorten the reason first, then hard-cut the middle lines
        lines[1] = f"P(Lula) {pct(cur['p_central'])} · otim. {pct(cur['p_otimista'])} / pess. {pct(cur['p_pessimista'])}"
        msg = "\n".join(lines)
    if len(msg) > 450:
        msg = msg[:450 - len(FOOTER) - 2] + "…\n" + FOOTER
    return msg


def backfill(c):
    P = P_load()
    w = pdt(P["backfill_desde"])
    end = last_complete(6)
    out = []
    while w <= end:
        r = run(c, zs(w), 6, backfill=True)
        out.append({"window": r["window"], "p": r["p"]["central"]})
        w += dt.timedelta(hours=6)
    return out


def baseline(c):
    P = P_load()
    a = pdt(P["baseline_as_of"])
    return run(c, zs(a), 0, as_of=a, label="c50_baseline")


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Caminho dos 50% (addendum 8)")
    ap.add_argument("cmd", choices=["seed", "ingest", "run", "add", "queue", "accept", "reject", "export", "block",
                                    "backfill", "deactivate", "baseline"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--window", action="append", default=[])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--tipo")
    ap.add_argument("--json", dest="js")
    ap.add_argument("--fonte"); ap.add_argument("--url"); ap.add_argument("--nota")
    ap.add_argument("--autor", default="manual"); ap.add_argument("--t")
    ap.add_argument("--hours", type=int, default=6)
    a = ap.parse_args(argv)
    c = db()
    if a.cmd in ("run", "ingest", "backfill") and not a.dry:
        _lk = lock("c50")  # noqa: F841 (cron also wraps with flock)
    if a.cmd == "run" and a.dry:
        c.execute("BEGIN")  # everything below (tables, seed, row) is rolled back
    ensure(c)
    if a.cmd == "seed":
        res = seed(c)
        b = c.execute("SELECT p_central FROM c50_daily WHERE window='c50_baseline'").fetchone()
        res["baseline"] = round(b[0], 4) if b else baseline(c)["p"]  # frozen: never recomputed once stored
    elif a.cmd == "ingest":
        res = ingest(c)
    elif a.cmd == "run":
        hours = 1 if "1h" in a.window else 6
        starts = [x for x in a.window if x not in ("1h", "6h")]
        if a.dry:
            if not seeded(c):
                seed(c, commit=False)
            res = run(c, starts[0] if starts else None, hours, dry=True, commit=False)
            res["block_preview"] = None
            c.rollback()
        else:
            if not seeded(c):
                seed(c)
            res = run(c, starts[0] if starts else None, hours)
            elog(f"run {res['window']} ({hours}h): P {res['p']['central']:.3f}")
    elif a.cmd == "add":
        if not a.tipo or not a.js:
            ap.error("add needs --tipo and --json")
        v = json.loads(a.js)
        chave = None
        if a.tipo == "poll":
            if not v.get("instituto") or not v.get("data_fim"):
                ap.error("poll needs instituto and data_fim")
            chave = f"poll:{norm_inst(v['instituto'])}:{v['data_fim']}"
            if not re.match(P_load()["polls"]["registro_regex"], (v.get("registro_tse") or "")):
                elog("WARNING: poll without a valid registro_tse: stored, but it will NOT enter the model")
        i = add_input(c, a.tipo, v, a.t, a.fonte, a.url, a.nota, a.autor, chave)
        res = {"id": i, "duplicate": i is None}
    elif a.cmd == "queue":
        res = queue_rows(c, a.arg or "pendente")
    elif a.cmd in ("accept", "reject"):
        q = c.execute("SELECT * FROM c50_queue WHERE id=?", (int(a.arg),)).fetchone()
        if not q:
            ap.error("no such queue id")
        iid = None
        if a.cmd == "accept":
            if not a.js:
                ap.error("accept needs --json with the input values (e.g. the poll numbers and registro_tse)")
            v = json.loads(a.js)
            tipo = a.tipo or q["tipo_sugerido"]
            chave = f"poll:{norm_inst(v['instituto'])}:{v['data_fim']}" if tipo == "poll" else None
            its = json.loads(q["itens_json"] or "[]")
            iid = add_input(c, tipo, v, a.t, a.fonte or "fila c50", a.url or (its[0]["url"] if its else None),
                            a.nota or q["titulo"], a.autor, chave)
        c.execute("UPDATE c50_queue SET status=?, decidido_utc=?, input_id=? WHERE id=?",
                  ("aceito" if a.cmd == "accept" else "rejeitado", iso(), iid, q["id"]))
        c.commit()
        res = {"queue_id": q["id"], "status": a.cmd, "input_id": iid}
    elif a.cmd == "deactivate":
        c.execute("UPDATE c50_inputs SET ativo=0 WHERE id=?", (int(a.arg),))
        c.commit()
        res = {"deactivated": int(a.arg)}
    elif a.cmd == "export":
        res = export(c, a.hours)
    elif a.cmd == "block":
        print(block(c, a.hours))
        return
    elif a.cmd == "backfill":
        res = backfill(c)
    elif a.cmd == "baseline":
        res = baseline(c)
    print(json.dumps(res, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
