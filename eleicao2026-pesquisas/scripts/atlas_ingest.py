#!/usr/bin/env python3
"""Ingest AtlasIntel/Bloomberg transcriptions (markdown crosstab tables) into data/pesquisas.db recortes,
and register transcription docs (Atlas, Palver, Vox)."""
import os, re, sqlite3, unicodedata, glob

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'pesquisas.db')
POLLS = os.path.join(BASE, 'out', 'polls')

FILES = {  # file -> (instituto, data_fim)
    'Atlas_Bloomberg_2T_13-18-10_transcricao.md': ('AtlasIntel', '2026-10-18'),
    'Atlas_Bloomberg_2T_03-08-10_transcricao.md': ('AtlasIntel', '2026-10-08'),
}
SEG = {'GÊNERO': 'sexo', 'IDADE': 'idade', 'NÍVEL EDUCACIONAL': 'escolaridade', 'RENDA FAMILIAR': 'renda',
       'RELIGIÃO': 'religiao', 'REGIÃO': 'regiao', 'VOTO PRESIDENTE – 2º TURNO 2022': 'voto_2t_2022',
       'VOTO PRESIDENTE - 2º TURNO 2022': 'voto_2t_2022', 'VOTO PRESIDENTE – 1º TURNO 2026': 'voto_1turno',
       'VOTO PRESIDENTE - 1º TURNO 2026': 'voto_1turno'}
CAT = {'Homem': 'homens', 'Mulher': 'mulheres', '16 – 24': '16-24', '16 - 24': '16-24', '25 – 34': '25-34', '25 - 34': '25-34',
       '35 – 44': '35-44', '35 - 44': '35-44', '45 – 59': '45-59', '45 - 59': '45-59', '60 – 100': '60+', '60 - 100': '60+',
       'Até Ensino Médio': 'ate_medio', 'Ensino Fundamental': 'fundamental', 'Ensino Médio': 'medio', 'Ensino Superior': 'superior',
       'R$0 – R$2,000': 'ate_2k', 'R$0 - R$2,000': 'ate_2k', 'R$2,000 – R$3,000': '2k_3k', 'R$2,000 - R$3,000': '2k_3k',
       'R$3,000 – R$5,000': '3k_5k', 'R$3,000 - R$5,000': '3k_5k', 'R$5,000 – R$10,000': '5k_10k', 'R$5,000 - R$10,000': '5k_10k',
       'Acima de R$10,000': 'mais_10k', 'Católico': 'catolicos', 'Evangélico': 'evangelicos', 'Outra religião': 'outra',
       'Crente sem religião': 'crente_sem_religiao', 'Agnóstico ou ateu': 'ateu_agnostico', 'Nordeste': 'nordeste',
       'Sudeste': 'sudeste', 'Sul': 'sul', 'Norte': 'norte', 'Centro – Oeste': 'centro_oeste', 'Centro - Oeste': 'centro_oeste',
       'Lula': 'lula', 'Jair Bolsonaro': 'bolsonaro', 'Voto branco / nulo': 'branco_nulo', 'Voto branco/nulo': 'branco_nulo',
       'Não votei': 'nao_votou', 'Flávio Bolsonaro': 'flavio', 'Renan Santos': 'renan', 'Escritor Augusto Cury': 'cury',
       'Ronaldo Caiado': 'caiado', 'Outro': 'outro'}

def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')

def num(x):
    x = x.strip().replace('%', '').replace(',', '.')
    try: return float(x)
    except: return None

def tables(text):
    """yield (header_line_before, list of rows) for markdown tables"""
    lines = text.splitlines(); i = 0
    while i < len(lines):
        if lines[i].startswith('|') and i + 1 < len(lines) and re.match(r'^\|[-| ]+\|$', lines[i + 1].strip()):
            hdr = [c.strip() for c in lines[i].strip('|').split('|')]
            rows = []; j = i + 2
            while j < len(lines) and lines[j].startswith('|'):
                rows.append([c.strip() for c in lines[j].strip('|').split('|')]); j += 1
            ctx = '\n'.join(lines[max(0, i - 12):i])
            yield ctx, hdr, rows; i = j
        else: i += 1

def main():
    c = sqlite3.connect(DB)
    n = 0
    for fn, (inst, end) in FILES.items():
        path = os.path.join(POLLS, fn)
        if not os.path.exists(path): print('missing', fn); continue
        pid = c.execute("select id from pesquisas where instituto=? and data_fim=?", (inst, end)).fetchone()
        if not pid: print('no pesquisa row for', inst, end); continue
        pid = pid[0]
        text = open(path, encoding='utf-8').read()
        for ctx, hdr, rows in tables(text):
            if len(hdr) < 5 or hdr[0] not in ('Recorte', 'Grupo'): continue
            if 'cruzamentos' not in ctx: continue
            if 'Aprovação do Presidente' in ctx: kind = 'aprovacao_'
            elif 'Avaliação do Governo' in ctx: kind = 'avaliacao_'
            else: kind = ''
            cols = [h.lower() for h in hdr]
            for r in rows:
                if len(r) < 5: continue
                seg = SEG.get(r[0]) or slug(r[0]); cat = CAT.get(r[1]) or slug(r[1])
                vals = dict(zip(cols, r))
                lula = flavio = bn = ns = None
                if kind == '':
                    flavio = num(vals.get('flávio bolsonaro', '')); lula = num(vals.get('lula', '')); bn = num(vals.get('branco/nulo/não sei', ''))
                    fonte = f'{fn} p.9 cruzamentos (totais); branco_nulo=branco/nulo/nao sei'
                elif kind == 'aprovacao_':
                    lula = num(vals.get('aprovo', '')); flavio = num(vals.get('desaprovo', '')); ns = num(vals.get('não sei', ''))
                    fonte = f'{fn} cruzamentos aprovacao; NAO e voto: lula=aprova, flavio=desaprova'
                else:
                    lula = num(vals.get('ótimo/bom', '')); flavio = num(vals.get('ruim/péssimo', '')); bn = num(vals.get('regular', ''))
                    fonte = f'{fn} cruzamentos avaliacao; NAO e voto: lula=otimo/bom, flavio=ruim/pessimo, branco_nulo=regular'
                c.execute("insert or replace into recortes(pesquisa_id,segmento,categoria,lula,flavio,branco_nulo,nao_sabe,base,fonte) values(?,?,?,?,?,?,?,?,?)",
                          (pid, kind + seg, cat, lula, flavio, bn, ns, None, fonte)); n += 1
    # docs
    for fn in glob.glob(os.path.join(POLLS, '*_transcricao.md')):
        base = os.path.basename(fn)
        inst = 'AtlasIntel' if base.startswith('Atlas') else 'Palver' if base.startswith('Palver') else 'Vox' if base.startswith('Vox') else 'Quaest'
        c.execute("insert or ignore into docs(tipo,fonte,outlet,titulo,url,path,data,texto,criado) values('transcricao',?,?,?,NULL,?,date('now'),?,datetime('now'))",
                  (inst, inst, base.replace('_transcricao.md', ''), fn, open(fn, encoding='utf-8').read()))
    c.commit()
    print('atlas recortes upserted', n)
    for r in c.execute("select p.instituto,p.data_fim,count(*) from recortes r join pesquisas p on p.id=r.pesquisa_id where p.instituto='AtlasIntel' group by 1,2"): print(r)
    print(c.execute("select tipo,count(*) from docs group by 1").fetchall())

if __name__ == '__main__':
    main()
