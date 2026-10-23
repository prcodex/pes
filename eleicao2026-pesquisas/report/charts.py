import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, numpy as np, datetime as dt, os
from math import erf, sqrt
OUT = os.path.dirname(os.path.abspath(__file__)) + '/img'; os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.spines.top': False, 'axes.spines.right': False})
RED = '#c0392b'; BLUE = '#2c5aa0'; GREY = '#7f8c8d'; L = '#b03a2e'; F = '#1f4e79'

polls = [('PoderData','2026-10-07',47.0),('Datafolha','2026-10-07',48.0),('Vox','2026-10-07',50.9),('Atlas','2026-10-08',47.2),('Ipespe','2026-10-08',47.3),('DataTrends','2026-10-09',46.9),('Futura','2026-10-10',48.2),('Gerp','2026-10-12',45.0),('PoderData','2026-10-12',49.0),('Nexus','2026-10-12',48.0),('Quaest','2026-10-13',49.0),('Palver','2026-10-13',49.5),('Indexa','2026-10-14',49.0),('Datafolha','2026-10-14',49.0),('CNT','2026-10-15',49.5),('Ipespe','2026-10-15',48.8),('PoderData','2026-10-15',50.0),('Futura','2026-10-15',49.2),('Gerp','2026-10-16',48.0),('Veritá','2026-10-16',48.93),('Vox','2026-10-17',51.0),('Futura','2026-10-17',49.6),('DataTrends','2026-10-17',48.5),('PoderData','2026-10-18',48.0),('Nexus','2026-10-18',49.7),('Atlas','2026-10-18',48.9),('Real Time','2026-10-19',48.0),('Meio/Ideia','2026-10-19',48.9),('Alfa','2026-10-19',48.5),('Quaest','2026-10-20',49.4),('Palver','2026-10-20',49.0),('PoderData','2026-10-21',49.5),('Indexa','2026-10-21',49.4),('Gerp','2026-10-21',47.0),('Datafolha','2026-10-22',50.0)]
d0 = dt.date(2026,10,5)
# 1. all polls + trend
fig, ax = plt.subplots(figsize=(7.2,3.4))
xs = np.array([(dt.date.fromisoformat(d)-d0).days for _,d,_ in polls]); ys = np.array([v for *_,v in polls])
big = {'Datafolha':L,'Quaest':'#8e44ad','PoderData':'#16a085','Atlas':'#d35400'}
for (i,d,v),x in zip(polls,xs):
    ax.scatter(x, v, s=28 if i in big else 14, color=big.get(i,GREY), alpha=0.9 if i in big else 0.5, zorder=3)
a,b = np.polyfit(xs, ys, 1); xx = np.linspace(0,20,50)
ax.plot(xx, a*xx+b, color='black', lw=1.2, ls='--', label=f'tendência {a:+.2f} pp/dia')
ax.axhline(50, color=RED, lw=0.8); ax.axhline(48.99, color=BLUE, lw=0.8, ls=':')
ax.text(0.2, 50.15, '50% — virada', color=RED, fontsize=8); ax.text(0.2, 48.6, '48,99 — bipartidário do 1º turno', color=BLUE, fontsize=8)
for k,c in big.items(): ax.scatter([],[],color=c,label=k,s=28)
ax.scatter([],[],color=GREY,label='outros (13 institutos)',s=14)
ax.set_xticks([0,5,10,15,20]); ax.set_xticklabels(['5/10','10/10','15/10','20/10','25/10'])
ax.set_ylim(44,52); ax.set_ylabel('Lula, % dos votos válidos'); ax.legend(fontsize=7, ncol=3, loc='lower right', frameon=False)
ax.set_title('34 rodadas de 2º turno (5–22/10): Lula sobe ~1 pp/semana e não cruzou 50', fontsize=10, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c1_polls.png', dpi=200); plt.close()

# 2. Datafolha segment deltas 7/10 -> 22/10
seg = [('Nordeste',63,68),('CO/Norte',39,44),('16–24 anos',46,53),('25–34 anos',46,50),('Brancos',41,45),('Ensino médio',43,47),('Homens',43,46),('Católicos',56,59),('Não alinhados',42,44),('Até 2 SM',56,58),('Evangélicos',27,27),('Fundamental',58,57),('Sudeste',46,44),('Sul',38,36),('35–44 anos',47,44)]
seg.sort(key=lambda s: s[2]-s[1])
fig, ax = plt.subplots(figsize=(7.2,4.2))
y = np.arange(len(seg))
for i,(n,a0,a1) in enumerate(seg):
    ax.plot([a0,a1],[i,i], color=L if a1>=a0 else F, lw=2.2); ax.scatter([a0],[i], color='white', edgecolor=GREY, zorder=3, s=30); ax.scatter([a1],[i], color=L if a1>=a0 else F, zorder=3, s=30)
    ax.text(max(a0,a1)+0.8, i, f'{a1-a0:+d}', va='center', fontsize=8, color=L if a1>=a0 else F)
ax.set_yticks(y); ax.set_yticklabels([s[0] for s in seg]); ax.axvline(50, color=GREY, lw=0.7, ls=':')
ax.set_xlabel('Lula, % válidos (○ 7/10 → ● 22/10)'); ax.set_xlim(22,74)
ax.set_title('Datafolha, 7/10 → 22/10: ganho no Nordeste, jovens e CO/Norte; recuo no SE e Sul', fontsize=9.5, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c2_segmentos.png', dpi=200); plt.close()

# 3. transfer matrix (Atlas 18/10)
rows = [('Lula (45%)',98.3,0.5,1.2),('Flávio (47%)',0,100,0),('Renan Santos',31.9,33.5,34.6),('Augusto Cury',52.1,42.4,5.6),('Ronaldo Caiado',24.5,69.8,5.7),('Outro',30.7,61.3,8.0),('Branco/nulo',21.1,38.7,40.2),('Não votou',55.7,40.2,4.2)]
fig, ax = plt.subplots(figsize=(7.2,3.2))
y = np.arange(len(rows))[::-1]
for (n,l,f,bn),yy in zip(rows,y):
    ax.barh(yy, l, color=L); ax.barh(yy, f, left=l, color=F); ax.barh(yy, bn, left=l+f, color='#bdc3c7')
    ax.text(l/2, yy, f'{l:.0f}', va='center', ha='center', color='white', fontsize=8) if l>8 else None
    ax.text(l+f/2, yy, f'{f:.0f}', va='center', ha='center', color='white', fontsize=8) if f>8 else None
    ax.text(l+f+bn/2, yy, f'{bn:.0f}', va='center', ha='center', color='black', fontsize=8) if bn>8 else None
ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows]); ax.set_xlim(0,100); ax.set_xlabel('% — Lula | Flávio | branco/nulo/não sei')
ax.set_title('Voto do 1º turno → 2º turno (Atlas 13–18/10, n 4.998): retenção ~100%, terceiros dividem', fontsize=9.5, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c3_transfer.png', dpi=200); plt.close()

# 4. calibration 1T by institute
cal = [('Palver',-1.2),('Futura',-0.7),('Gerp',0.4),('PoderData',1.6),('Meio/Ideia',1.7),('Datafolha',2.2),('Quaest',2.3),('Atlas',2.6),('Vox',3.1),('Real Time',3.5),('CNT/MDA',4.2),('Nexus',4.2),('Indexa',4.4)]
fig, ax = plt.subplots(figsize=(7.2,3.3))
ax.bar([c[0] for c in cal], [c[1] for c in cal], color=[F if v<0 else L for _,v in cal])
ax.axhline(0,color='black',lw=0.8); ax.axhline(2.2,color=GREY,lw=0.8,ls='--'); ax.text(12.4,2.3,'média +2,2',fontsize=8,ha='right',color=GREY)
ax.set_ylabel('erro sobre Lula (pp, bipartidário)'); plt.setp(ax.get_xticklabels(), rotation=35, ha='right')
ax.set_title('Erro na véspera do 1º turno: 10 de 13 superestimaram Lula; só Palver e Futura não', fontsize=9.5, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c4_calib.png', dpi=200); plt.close()

# 5. regional bias
regs = ['Nordeste','Sudeste','Sul','CO+N']
inst = {'Datafolha':[0.0,3.5,2.8,4.4],'PoderData':[-6.5,5.8,4.3,4.3],'Atlas':[-3.5,4.9,9.6,2.8],'Quaest':[-1.9,7.1,1.2,-3.3],'CNT/MDA':[3.2,3.9,13.9,-1.3],'Real Time':[3.1,4.5,-0.1,3.9]}
fig, ax = plt.subplots(figsize=(7.2,3.3))
w = 0.13; x = np.arange(4)
for i,(k,v) in enumerate(inst.items()):
    ax.bar(x+(i-2.5)*w, v, w, label=k)
ax.axhline(0,color='black',lw=0.8); ax.set_xticks(x); ax.set_xticklabels(regs); ax.set_ylabel('erro sobre Lula (pp)')
ax.legend(fontsize=7, ncol=6, frameon=False, loc='upper left'); ax.set_ylim(-8,15)
ax.set_title('Erro regional no 1º turno: Sudeste +3,5 a +7,1 nos seis institutos; Nordeste média zero', fontsize=9.5, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c5_regional.png', dpi=200); plt.close()

# 6. probability curves
P = lambda m,s: 0.5*(1-erf((50-m)/(s*sqrt(2))))
fig, ax = plt.subplots(figsize=(7.2,3.2))
xx = np.linspace(43,54,400)
for m,lab,c in [(49.4,'pesquisas certas (49,4)',GREY),(48.4,'metade do viés (48,4)',L),(47.4,'viés pleno (47,4)',F),(46.1,'correção regional plena (46,1)','#555')]:
    s=1.8; ax.plot(xx, np.exp(-(xx-m)**2/(2*s*s))/(s*sqrt(2*np.pi)), color=c, label=f'{lab}: P(Lula>50) = {100*P(m,s):.0f}%')
ax.axvline(50,color=RED,lw=1); ax.set_yticks([]); ax.set_xlabel('Lula, % válidos no domingo'); ax.legend(fontsize=7.5, frameon=False)
ax.set_title('Distribuição do resultado de Lula sob cada hipótese de viés (DP 1,8)', fontsize=10, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c6_prob.png', dpi=200); plt.close()

# 7. corrected vs headline per institute
inst2 = [('Datafolha 22/10',50.0,46.5,48.0),('PoderData 21/10',49.5,46.4,47.9),('Quaest 20/10',49.4,45.9,47.4),('Nexus 18/10',49.7,46.9,48.4),('Atlas 18/10',48.9,45.6,47.1),('Palver 13/10*',49.5,49.9,49.7)]
fig, ax = plt.subplots(figsize=(7.2,3.0))
x=np.arange(len(inst2)); w=0.26
ax.bar(x-w,[i[1] for i in inst2],w,color=GREY,label='manchete'); ax.bar(x,[i[3] for i in inst2],w,color=L,label='metade do viés regional'); ax.bar(x+w,[i[2] for i in inst2],w,color=F,label='viés regional pleno')
ax.axhline(50,color=RED,lw=0.8); ax.set_ylim(44,51); ax.set_xticks(x); ax.set_xticklabels([i[0] for i in inst2], fontsize=8); ax.legend(fontsize=7.5, frameon=False, ncol=3, loc='upper right')
ax.set_title('Últimas rodadas: manchete vs. corrigida pelo erro regional do 1º turno (*Palver: sem viés a corrigir)', fontsize=8.5, loc='left')
fig.tight_layout(); fig.savefig(OUT+'/c7_corr.png', dpi=200); plt.close()
print('ok')
