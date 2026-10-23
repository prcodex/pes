import re, os, datetime as dt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

D = os.path.dirname(os.path.abspath(__file__))
pdfmetrics.registerFont(TTFont('DV', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DVB', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
pdfmetrics.registerFont(TTFont('DVI', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily('DV', normal='DV', bold='DVB', italic='DVI', boldItalic='DVB')

ss = getSampleStyleSheet()
BODY = ParagraphStyle('b', parent=ss['Normal'], fontName='DV', fontSize=9.2, leading=13, spaceAfter=5, alignment=4)
H1 = ParagraphStyle('h1', parent=BODY, fontName='DVB', fontSize=15, leading=19, spaceBefore=4, spaceAfter=8, textColor=colors.HexColor('#1f2d3d'))
H2 = ParagraphStyle('h2', parent=BODY, fontName='DVB', fontSize=11, leading=14, spaceBefore=9, spaceAfter=4, textColor=colors.HexColor('#2c5aa0'))
SMALL = ParagraphStyle('s', parent=BODY, fontSize=7.6, leading=10, textColor=colors.HexColor('#555555'))
CAP = ParagraphStyle('c', parent=SMALL, alignment=1, spaceAfter=8)
VOICE = ParagraphStyle('v', parent=BODY, fontName='DVI', fontSize=8.6, leading=12, textColor=colors.HexColor('#444444'), backColor=colors.HexColor('#f3f5f8'), borderPadding=5, spaceAfter=8)
BIG = ParagraphStyle('big', parent=BODY, fontName='DVB', fontSize=22, leading=26, alignment=1, textColor=colors.HexColor('#b03a2e'))

def inline(s):
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', s)
    return s

def md_to_flow(text, width):
    out = []; lines = text.splitlines(); i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip(): i += 1; continue
        if ln.startswith('### '): out.append(Paragraph(inline(ln[4:]), ParagraphStyle('h3', parent=H2, fontSize=9.8, textColor=colors.HexColor('#1f2d3d')))); i += 1; continue
        if ln.startswith('## '): out.append(Paragraph(inline(ln[3:]), H2)); i += 1; continue
        if ln.startswith('# '): out.append(Paragraph(inline(ln[2:]), H1)); i += 1; continue
        if ln.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not re.match(r'^[-: ]+$', cells[0]): rows.append(cells)
                i += 1
            ncol = max(len(r) for r in rows)
            rows = [r + [''] * (ncol - len(r)) for r in rows]
            data = [[Paragraph(inline(c), SMALL) for c in r] for r in rows]
            cw = [width / ncol] * ncol
            if ncol >= 3: cw[0] = width * 0.34; rest = (width - cw[0]) / (ncol - 1); cw = [cw[0]] + [rest] * (ncol - 1)
            t = Table(data, colWidths=cw, repeatRows=1)
            t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8edf3')), ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#c9d1da')),
                                   ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
            out.append(t); out.append(Spacer(1, 5)); continue
        if ln.lstrip().startswith(('- ', '* ')) or re.match(r'^\d+\. ', ln.lstrip()):
            while i < len(lines) and (lines[i].lstrip().startswith(('- ', '* ')) or re.match(r'^\d+\. ', lines[i].lstrip())):
                txt = re.sub(r'^(\s*)([-*]|\d+\.)\s+', '', lines[i])
                out.append(Paragraph('• ' + inline(txt), ParagraphStyle('li', parent=BODY, leftIndent=10, spaceAfter=2))); i += 1
            out.append(Spacer(1, 3)); continue
        para = [ln]; i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(('#', '|', '- ', '* ')) and not re.match(r'^\d+\. ', lines[i]):
            para.append(lines[i].rstrip()); i += 1
        out.append(Paragraph(inline(' '.join(para)), BODY))
    return out

def img(name, w, cap):
    im = Image(D + '/img/' + name); r = im.imageHeight / im.imageWidth; im.drawWidth = w; im.drawHeight = w * r
    return [im, Paragraph(cap, CAP)]

def build(out):
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=1.7 * cm, rightMargin=1.7 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title='Lula pode virar? Três vozes sobre o 2º turno', author='Pulse Eleição 2026')
    W = A4[0] - 3.4 * cm
    v1 = open(D + '/voz1_fable.md', encoding='utf-8').read(); v2 = open(D + '/voz2_opus.md', encoding='utf-8').read(); v3 = open(D + '/voz3_sonnet.md', encoding='utf-8').read()
    def footer(c, d):
        c.saveState(); c.setFont('DV', 7); c.setFillColor(colors.HexColor('#777777'))
        c.drawString(1.7 * cm, 0.9 * cm, 'Pulse Eleição 2026 · pesquisas.db (34 rodadas, 17 institutos, 1.416 recortes, 57 relatórios, 172 transcrições) · TSE munzona e perfil de comparecimento · 23/10/2026')
        c.drawRightString(A4[0] - 1.7 * cm, 0.9 * cm, f'{d.page}'); c.restoreState()
    s = []
    s.append(Paragraph('Lula pode virar? A probabilidade, de onde vêm os votos e o que as pesquisas valem', H1))
    s.append(Paragraph('Relatório em três vozes — 23 de outubro de 2026, 13h BRT, dois dias antes do 2º turno (Lula × Flávio Bolsonaro). Voz 1: Claude Fable 5.1 (análise principal). Voz 2: Claude Opus (cético adversarial, instruído a atacar a conclusão nos dois sentidos). Voz 3: Claude Sonnet (árbitro, instruído a reafirmar, corrigir ou rejeitar ponto a ponto). As três trabalharam sobre o mesmo brief de dados e não viram os números uma da outra antes de escrever, exceto a voz 3, que leu as duas.', SMALL))
    s.append(Spacer(1, 6))
    box = [[Paragraph('<b>Voz 1 (Fable)</b><br/>18%<br/><font size=7>faixa 10–25%</font>', ParagraphStyle('x', parent=BODY, alignment=1, fontSize=12, leading=15)),
            Paragraph('<b>Voz 2 (Opus, cético)</b><br/>24%<br/><font size=7>faixa 15–32%</font>', ParagraphStyle('x', parent=BODY, alignment=1, fontSize=12, leading=15)),
            Paragraph('<b>Voz 3 (Sonnet, árbitro)</b><br/>' + re.search(r'\*\*P\(Lula vence\)\s*=\s*([^*]+)\*\*', v3).group(1).strip() if re.search(r'\*\*P\(Lula vence\)\s*=\s*([^*]+)\*\*', v3) else '<b>Voz 3 (Sonnet, árbitro)</b><br/>ver seção 3', ParagraphStyle('x', parent=BODY, alignment=1, fontSize=12, leading=15)),
            Paragraph('<b>Referências</b><br/><font size=8>Polymarket 20/10: 23%<br/>c50 do projeto: 42%<br/>c50 + rejeição: 47%</font>', ParagraphStyle('x', parent=BODY, alignment=1, fontSize=10, leading=13))]]
    t = Table(box, colWidths=[W / 4] * 4); t.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#2c5aa0')), ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#c9d1da')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7f9fb'))]))
    s.append(t); s.append(Spacer(1, 8))
    s.append(Paragraph('<b>Probabilidade de Lula vencer, em uma frase:</b> as pesquisas medem 49 × 51 e sobem um ponto por semana; as mesmas pesquisas superestimaram Lula em 2,2 pontos há três semanas, com todo o erro no Sudeste e no Sul; descontando metade desse erro, Lula chega a domingo em 48–48,5, e a chance de cruzar 50 fica entre 15% e 25%. O que decide é o Sudeste — onde está o ganho medido de Lula e onde esteve o erro medido das pesquisas.', BODY))
    s += img('c1_polls.png', W, 'Figura 1 — As 34 rodadas de 2º turno com registro no TSE, válidos de Lula, e a tendência linear. Fonte: pesquisas.db.')
    s += img('c6_prob.png', W, 'Figura 2 — Distribuição do resultado de Lula sob cada hipótese de viés das pesquisas (DP 1,8, calibrado no histórico de 2º turno). A probabilidade é a área à direita de 50.')
    s.append(Paragraph('Voz 1 — Fable: a análise principal', H1)); s.append(Paragraph('Claude Fable 5.1, com acesso a todo o banco (pesquisas, recortes, transcrições, TSE). Instrução: análise honesta, dar a probabilidade.', VOICE))
    s += md_to_flow(v1, W)
    s.append(PageBreak())
    s += img('c2_segmentos.png', W, 'Figura 3 — Datafolha, válidos de Lula por segmento, 7/10 → 22/10 (banco interativo da Folha; BR-02949 e BR-09709). Subamostras têm margem de 4–6 pontos.')
    s += img('c3_transfer.png', W, 'Figura 4 — Matriz de transferência, Atlas/Bloomberg 13–18/10 (BR-02418). Lula precisa de 56–62% dos terceiros para empatar só com transferência; tem 26–37% nas três casas que mediram.')
    s += img('c4_calib.png', W, 'Figura 5 — Erro das pesquisas finais do 1º turno (bipartidário Lula, pesquisa − urna 48,99), 13 institutos. Fonte: registro Arko Advice 20/10 + TSE.')
    s += img('c5_regional.png', W, 'Figura 6 — O mesmo erro, por região, nos seis institutos com recorte regional publicado (íntegras transcritas). Pesos de válidos: NE 28,3%, SE 40,6%, S 14,7%, CO+N 16,1%.')
    s.append(PageBreak())
    s += img('c7_corr.png', W, 'Figura 7 — Últimas rodadas dos cinco maiores institutos: manchete e correção pelo erro regional do 1º turno (média dos seis institutos). Palver, sem viés a corrigir, fica em 49,7–49,9.')
    s.append(Paragraph('Voz 2 — Opus: o cético adversarial', H1)); s.append(Paragraph('Claude Opus, instruído a atacar a conclusão da voz 1 nos dois sentidos: detalhar o crescimento de Lula, construir o caso mais forte de como ele pode vencer, e apontar onde a voz 1 é generosa demais. Escreveu sem ver o texto da voz 1, só sabendo o número dela.', VOICE))
    s += md_to_flow(v2, W)
    s.append(PageBreak())
    s.append(Paragraph('Voz 3 — Sonnet: o árbitro', H1)); s.append(Paragraph('Claude Sonnet, com o brief e os dois textos: reafirmar, corrigir ou rejeitar ponto a ponto, e fechar a probabilidade.', VOICE))
    s += md_to_flow(v3, W)
    s.append(Spacer(1, 10)); s.append(Paragraph('Metodologia e fontes', H2))
    s.append(Paragraph('Banco <b>pesquisas.db</b>: 34 rodadas nacionais de 2º turno (5–22/10, 17 institutos, todas com registro TSE), 1.416 recortes por segmento (banco interativo da Datafolha para as três ondas; Atlas, Quaest, PoderData, Palver, CNT, Ipespe, Real Time, Gerp via transcrição por visão dos relatórios oficiais), 57 relatórios em PDF, 172 transcrições de vídeo e relatório, 1.065 matérias. Calibração do 1º turno: pesquisas finais de 13 institutos (registro Arko Advice de 20/10) contra a urna do TSE (Flávio 47,03 / Lula 45,16); erro regional a partir das íntegras de seis institutos. Abstenção: TSE, perfil de comparecimento 2026 (1º turno) e 2022 (1º e 2º), por município × sexo × idade × escolaridade. Modelo de probabilidade: resultado de Lula em válidos ~ Normal(média corrigida + 0,3 de tendência, DP 1,5–2,0); P = área acima de 50. Limitações: não há microdados individuais das pesquisas; o viés do 1º turno mistura voto envergonhado (persistente) e colapso de terceiros (não persistente), e a proporção entre os dois não é identificável antes de domingo; subamostras da Datafolha (n 2.520) têm margem de 4–6 pontos.', SMALL))
    doc.build(s, onFirstPage=footer, onLaterPages=footer)

if __name__ == '__main__':
    build(D + '/Lula_pode_virar_tres_vozes_2026-10-23.pdf'); print('built')
