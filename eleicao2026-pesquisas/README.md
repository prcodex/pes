# eleicao2026-pesquisas — base de pesquisas e análise de probabilidade (2º turno 2026)

Banco de dados, scripts e relatório usados para estimar a chance de Lula vencer o 2º turno
presidencial de 25/10/2026 (Lula × Flávio Bolsonaro), a partir de **todas** as pesquisas registradas
no TSE, dos recortes por segmento, dos resultados oficiais do 1º turno e do perfil de comparecimento
do eleitorado. Snapshot de 23/10/2026, 12h BRT.

Nenhuma chave de API está neste diretório. Os scripts que precisam de credenciais leem de
variáveis de ambiente (`ANTHROPIC_API_KEY`, `ZENROWS_API_KEY`) ou de um arquivo fora do repositório.

## O que tem aqui

```
data/
  pesquisas.db                 SQLite — 34 rodadas, 17 institutos, 1.416 recortes, 57 relatórios (texto), 172 transcrições, 1.065 matérias
  datafolha_db/                CSVs do banco interativo da Folha (3 ondas de 2º turno + série do 1º turno, 9 recortes × 7 perguntas)
  transcricoes/                relatórios oficiais transcritos página a página por modelo de visão (Quaest, Atlas, PoderData, Palver, CNT, Ipespe, Real Time, Gerp, Vox, Nexus)
  tse_perfil/                  perfil de comparecimento/abstenção TSE 2026 (1º turno) e 2022 (1º e 2º), agregado nacional × sexo × idade × escolaridade × cor
  consistencia_regional_2026-10-23.json   nacional implícito pelos recortes regionais vs manchete, por rodada
  pdf_data_2026-10-23.json     extrato do banco usado nos gráficos do relatório
scripts/
  pesquisas_db.py              cria o banco e ingere JSON de rodadas / documentos
  df_db_ingest.py              baixa-e-carrega o banco interativo da Datafolha em `recortes`
  atlas_ingest.py              parser das tabelas de cruzamento das transcrições (Atlas) → `recortes`
  transcribe.py                transcrição por visão de PDFs de relatório (pdftoppm + Claude Sonnet), com cache por página
  tools/zr_df_batch.py         download em lote do banco Datafolha via ZenRows (chave por env/arquivo externo)
  tools/pdf_batch_dl.py        download em lote de íntegras (direto, com fallback ZenRows)
  micro/tse_perfil_agg.py      agrega o CSV de 3 GB do TSE em parquet por município × demografia
  c50.py / c50_rej.py          modelo c50 do projeto (média ponderada de pesquisas, com e sem rejeição)
report/
  Lula_pode_virar_tres_vozes_2026-10-23.pdf   relatório final (11 pp, 7 gráficos)
  voz1_fable.md / voz2_opus.md / voz3_sonnet.md   os três textos (análise, cético adversarial, árbitro)
  charts.py / build.py         geração dos gráficos (matplotlib) e do PDF (reportlab)
  img/                         os 7 gráficos em PNG
```

## Como a análise é feita (a "tecnologia")

1. **Coleta exaustiva, não amostral.** Todas as rodadas nacionais com registro no TSE entram em `pesquisas`
   (instituto, campo, n, totais, válidos, rejeição, registro). A fonte de cada número fica em `fonte`.
   As íntegras (PDF) são baixadas (`tools/pdf_batch_dl.py`), o texto extraído entra em `docs`, e os relatórios
   em imagem são transcritos por visão (`transcribe.py`) para recuperar os cruzamentos por segmento.
   A Datafolha publica um banco interativo (arte.folha); `df_db_ingest.py` lê a API dele
   (`.../databases/eleicoes/2026/pesquisa-eleitoral/{instituto}/{turno}/{local}/{cargo}/{pergunta}/{cenário}/{recorte}.csv`)
   e carrega 9 recortes × 7 perguntas por onda.

2. **Recortes normalizados.** Tudo vai para `recortes(pesquisa_id, segmento, categoria, lula, flavio, branco_nulo, nao_sabe, fonte)`.
   Convenções: `regiao`, `sexo`, `idade`, `escolaridade`, `renda`, `religiao`, `cor_raca`, `identificacao_politica`,
   `voto_1turno` (matriz de transferência), `voto_2t_2022`; prefixos `validos_`, `espontanea_`, `rejeicao_lula_`,
   `rejeicao_flavio_`, `aprovacao_`, `avaliacao_`. Para perguntas que não são voto, `lula`/`flavio` guardam
   a resposta favorável/desfavorável e `fonte` diz qual.

3. **Consistência interna.** Para cada rodada com recorte regional, o nacional implícito
   (Σ peso TSE da região × bipartidário Lula na região) é comparado à manchete
   (`data/consistencia_regional_2026-10-23.json`). Diferenças acima de ~1 pp indicam recorte mal transcrito ou
   ponderação atípica.

4. **Calibração contra a urna.** Tabelas `calibracao_1t_totais` (13 institutos) e `calibracao_1t_regiao`
   (6 institutos, por região): erro das pesquisas finais do 1º turno no bipartidário Lula contra o resultado
   oficial (TSE, 48,99). É isso que separa "o que as pesquisas dizem" de "o que vale a pena acreditar".

5. **Abstenção com dado real.** `micro/tse_perfil_agg.py` agrega o perfil de comparecimento do TSE; o teste
   reponderada cada recorte pelo comparecimento real do 1º turno (em vez da população) e mede a mudança
   de composição 1º → 2º turno em 2022. Resultado: efeito < 0,1 pp.

6. **Probabilidade.** Resultado de Lula em válidos ~ Normal(média das últimas rodadas + tendência até o
   domingo − viés assumido, DP 1,5–2,0). P(Lula) = área acima de 50. A tabela de cenários varia o viés
   (0, ⅓, ½, pleno, correção regional) e deixa a escolha explícita.

7. **Três vozes.** O relatório é escrito por três modelos sobre o mesmo brief de dados: uma análise
   principal, um cético adversarial instruído a atacar a conclusão nos dois sentidos, e um árbitro que
   reafirma, corrige ou rejeita ponto a ponto. Os três números e as divergências ficam no PDF.

## Reproduzir

```bash
pip install pandas pyarrow matplotlib reportlab anthropic
sqlite3 data/pesquisas.db "select instituto,data_fim,lula_validos,flavio_validos from pesquisas order by data_fim"
python3 report/charts.py && python3 report/build.py      # regenera gráficos e PDF a partir dos .md e do json
ANTHROPIC_API_KEY=... python3 scripts/transcribe.py relatorio.pdf saida.md   # transcrever um PDF novo
```

## Resultado (23/10/2026)

| Voz | Modelo | P(Lula vence) |
|---|---|---|
| Análise principal | Claude Fable 5.1 | 18% (10–25) |
| Cético adversarial | Claude Opus | 24% (15–32) |
| Árbitro | Claude Sonnet | 21% (13–29) |

Pontos estabelecidos pelas três: tendência real de +1 pp/semana mas Lula nunca medido à frente em válidos;
retenção 94–97% (sem vira-voto); o ganho veio de branco/nulo, não de Flávio; abstenção não é fator;
as pesquisas superestimaram Lula em +2,2 pp no 1º turno, com todo o erro no Sudeste/Sul.

Fontes: TSE (resultados por município, perfil de comparecimento), registro Arko Advice 20/10, íntegras dos
institutos, banco interativo Datafolha/Folha, transcrições de JN/GloboNews/g1/Folha/UOL/CNN.
