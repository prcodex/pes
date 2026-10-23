#!/usr/bin/env python3
"""Ingest Datafolha interactive database (arte.folha CSVs) into data/pesquisas.db recortes.
usage: python3 df_db_ingest.py [--round segundo-turno]
"""
import csv, glob, json, os, sqlite3, sys, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'data', 'pesquisas.db')
SRC = os.path.join(BASE, 'out', 'polls', 'datafolha_db')

SEG = {'sexo': 'sexo', 'idadef': 'idade', 'esc': 'escolaridade', 'rendaf': 'renda', 'regiao': 'regiao',
       'cor': 'cor_raca', 'relig2': 'religiao', 'identificacaopol': 'identificacao_politica', 'total': 'total'}
CAT = {'Masculino': 'homens', 'Feminino': 'mulheres', '16 a 24 anos': '16-24', '25 a 34 anos': '25-34',
       '35 a 44 anos': '35-44', '45 a 59 anos': '45-59', '60 anos ou mais': '60+', 'Fundamental': 'fundamental',
       'Médio': 'medio', 'Superior': 'superior', 'Até 2 salários mínimos': 'ate_2sm',
       'Mais de 2 a 5 salários mínimos': '2_5sm', 'Mais de 5 salários mínimos': 'mais_5sm',
       'Centro-Oeste/ Norte': 'centro_oeste_norte', 'Nordeste': 'nordeste', 'Sudeste': 'sudeste', 'Sul': 'sul',
       'Branca': 'branca', 'Preta': 'preta', 'Parda': 'parda', 'Católica': 'catolicos', 'Evangélica': 'evangelicos',
       'Bolsonaristas': 'bolsonaristas', 'Não alinhados': 'nao_alinhados', 'Petistas': 'petistas', 'total': 'total'}
LULA = 'CAND-76-PRE-2026-002'; FLAVIO = 'CAND-76-PRE-2026-001'

def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return ''.join(ch if ch.isalnum() else '_' for ch in s).strip('_')

def main():
    rnd = 'segundo-turno'
    if '--round' in sys.argv: rnd = sys.argv[sys.argv.index('--round') + 1]
    c = sqlite3.connect(DB)
    pid_by_end = {r[1]: r[0] for r in c.execute("select id,data_fim from pesquisas where instituto='Datafolha'")}
    pref = os.path.join(SRC, f'datafolha__{rnd}__brasil__presidente__')
    n_ins = 0; n_new_poll = 0; unmatched = set()
    for f in sorted(glob.glob(pref + '*.csv')):
        parts = os.path.basename(f)[:-4].split('__')
        q, hyp, grp = parts[4], parts[5], parts[6]
        meta = json.load(open(f[:-4] + '_metadata.json'))
        rows = list(csv.DictReader(open(f)))
        by = {}
        for r in rows:
            by.setdefault((r['date'], r['subgroup']), {})[r['candidatura_id']] = float(r['value'])
        for (date, sub), v in by.items():
            m = meta.get(date, {})
            end = m.get('dates', {}).get('end', date)
            pid = pid_by_end.get(end)
            if pid is None:
                # create minimal poll row
                c.execute("insert or ignore into pesquisas(instituto,contratante,data_inicio,data_fim,n,margem,registro_tse,modo,fonte,criado) values(?,?,?,?,?,?,?,?,?,datetime('now'))",
                          ('Datafolha', 'Folha/Globo', m.get('dates', {}).get('start'), end, m.get('voters'), m.get('margin'), m.get('code'), m.get('type'), 'arte.folha databases ' + rnd))
                pid = c.execute("select id from pesquisas where instituto='Datafolha' and data_fim=?", (end,)).fetchone()[0]
                pid_by_end[end] = pid; n_new_poll += 1
            seg = SEG.get(grp, grp); cat = CAT.get(sub) or slug(sub)
            if sub not in CAT: unmatched.add(sub)
            fonte = f"arte.folha databases/eleicoes/2026 {rnd} {q}/{hyp} {grp} ({m.get('code','')}); "
            lula = flavio = bn = ns = None
            if q == 'intencao-de-voto-estimulada':
                segn = seg; lula, flavio, bn, ns = v.get(LULA), v.get(FLAVIO), v.get('0'), v.get('-1'); fonte += 'totais'
            elif q == 'intencao-de-voto-estimulada-votos-validos':
                segn = 'validos_' + seg; lula, flavio = v.get(LULA), v.get(FLAVIO); fonte += 'votos validos'
            elif q == 'intencao-de-voto-espontanea':
                segn = 'espontanea_' + seg; lula, flavio = v.get(LULA), v.get(FLAVIO)
                bn = v.get('0'); ns = v.get('-1'); fonte += 'espontanea totais (outros excluidos)'
            elif q == 'rejeicao-lula':
                segn = 'rejeicao_lula_' + seg; lula = v.get('-10'); bn = v.get('-11'); ns = v.get('-9')
                fonte += 'lula=nao votaria de jeito nenhum; branco_nulo=votaria com certeza; nao_sabe=talvez'
            elif q == 'rejeicao-flavio-bolsonaro':
                segn = 'rejeicao_flavio_' + seg; flavio = v.get('-10'); bn = v.get('-11'); ns = v.get('-9')
                fonte += 'flavio=nao votaria de jeito nenhum; branco_nulo=votaria com certeza; nao_sabe=talvez'
            elif q == 'aprovacao-lula':
                segn = 'aprovacao_' + seg; lula = v.get('511'); flavio = v.get('510'); ns = v.get('0')
                fonte += 'NAO e voto: lula=aprova, flavio=desaprova'
            elif q == 'avaliacao-lula':
                segn = 'avaliacao_' + seg; lula = v.get('522'); flavio = v.get('520'); bn = v.get('521'); ns = v.get('0')
                fonte += 'NAO e voto: lula=otimo/bom, flavio=ruim/pessimo, branco_nulo=regular'
            else:
                segn = q + '_' + seg; lula = v.get(LULA); flavio = v.get(FLAVIO)
            c.execute("insert or replace into recortes(pesquisa_id,segmento,categoria,lula,flavio,branco_nulo,nao_sabe,base,fonte) values(?,?,?,?,?,?,?,?,?)",
                      (pid, segn, cat, lula, flavio, bn, ns, None, fonte))
            n_ins += 1
    # register the source as doc
    for f in glob.glob(pref + '*_metadata.json'):
        pass
    c.execute("insert or ignore into docs(tipo,fonte,outlet,titulo,url,path,data,texto,criado) values('dataset','arte.folha','Folha',?,?,?,date('now'),?,datetime('now'))",
              (f'Datafolha banco interativo {rnd} presidente', 'https://arte.folha.uol.com.br/databases/eleicoes/2026/pesquisa-eleitoral/index.json', SRC, f'{n_ins} linhas de recortes importadas'))
    c.commit()
    print('recortes upserted', n_ins, 'new polls', n_new_poll, 'unmatched cats', unmatched)
    for r in c.execute("select p.data_fim,count(*) from recortes r join pesquisas p on p.id=r.pesquisa_id where instituto='Datafolha' group by 1"): print(r)

if __name__ == '__main__':
    main()
