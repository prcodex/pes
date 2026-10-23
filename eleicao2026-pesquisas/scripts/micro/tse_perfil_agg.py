#!/usr/bin/env python3
"""Aggregate TSE perfil_comparecimento_abstencao (zip, BRASIL csv) to parquet by
(ano, turno, uf, cd_municipio, genero, faixa_etaria, grau_instrucao, cor_raca). usage: tse_perfil_agg.py <ano>"""
import sys, zipfile, pandas as pd, time
ano = sys.argv[1]
D = '/home/prjr/scrapers/eleicao2026/micro/data/tse_perfil/'
z = zipfile.ZipFile(D + f'perfil_{ano}.zip')
name = f'perfil_comparecimento_abstencao_{ano}_BRASIL.csv'
cols = ['ANO_ELEICAO', 'NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'DS_GENERO', 'CD_FAIXA_ETARIA', 'DS_FAIXA_ETARIA',
        'DS_GRAU_INSTRUCAO', 'DS_COR_RACA', 'QT_APTOS', 'QT_COMPARECIMENTO', 'QT_ABSTENCAO']
keys = cols[:9]
acc = None; t = time.time(); n = 0
hdr=z.open(name).readline().decode('latin-1'); esc='DS_GRAU_ESCOLARIDADE' if 'DS_GRAU_ESCOLARIDADE' in hdr else 'DS_GRAU_INSTRUCAO'
cols=[esc if c=='DS_GRAU_INSTRUCAO' else c for c in cols]; keys=cols[:9]
with z.open(name) as f:
    for ch in pd.read_csv(f, sep=';', encoding='latin-1', usecols=cols, chunksize=2_000_000, dtype={'CD_MUNICIPIO': str}):
        g = ch.groupby(keys, as_index=False)[['QT_APTOS', 'QT_COMPARECIMENTO', 'QT_ABSTENCAO']].sum()
        acc = g if acc is None else pd.concat([acc, g]).groupby(keys, as_index=False).sum()
        n += len(ch); print(n, len(acc), round(time.time() - t), flush=True)
acc=acc.rename(columns={esc:'DS_GRAU_INSTRUCAO'}); acc.to_parquet(D + f'perfil_{ano}_mun.parquet', index=False)
# also a national × demographic cut
nat = acc.groupby(['ANO_ELEICAO', 'NR_TURNO', 'DS_GENERO', 'CD_FAIXA_ETARIA', 'DS_FAIXA_ETARIA', 'DS_GRAU_INSTRUCAO', 'DS_COR_RACA'], as_index=False)[['QT_APTOS', 'QT_COMPARECIMENTO', 'QT_ABSTENCAO']].sum()
nat.to_parquet(D + f'perfil_{ano}_nat.parquet', index=False)
print('done', len(acc), len(nat))
