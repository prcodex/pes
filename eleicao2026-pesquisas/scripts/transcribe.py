import os, sys, json, base64, subprocess, re, time, concurrent.futures as cf
# usage: transcribe.py <pdf> <out.md> [dpi]
pdf, out = sys.argv[1], sys.argv[2]; dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 110
work = out + ".pages"; os.makedirs(work, exist_ok=True)
log = open(out + ".log", "a")
def L(m): log.write(time.strftime("%H:%M:%S ") + m + "\n"); log.flush()
n = int([l for l in subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout.splitlines() if l.startswith("Pages")][0].split()[-1])
L(f"pages {n}")
subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, work + "/p"], check=True)
pngs = sorted(f for f in os.listdir(work) if f.endswith(".png"))
import anthropic
client = anthropic.Anthropic()
MODELS = ["claude-sonnet-5-5", "claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-3-7-sonnet-latest"]
PROMPT = ("Você é um transcritor de relatórios de pesquisa eleitoral. Transcreva INTEGRALMENTE esta página em Markdown, em português, "
          "sem resumir e sem omitir nenhum número, rótulo, nota ou base. Regras: (1) comece com o título/pergunta exatamente como está; "
          "(2) gráficos de barras/linhas viram tabelas Markdown com todas as categorias e valores (em %), na ordem da página; séries históricas viram uma tabela data × candidato; "
          "(3) páginas de recorte (região, sexo, idade, escolaridade, renda, religião, cor/raça, Bolsa Família, identificação política, voto no 1º turno) viram UMA tabela com uma linha por segmento e uma coluna por resposta; inclua a coluna 'Total' se existir; "
          "(4) copie notas de rodapé, bases (n), margens e textos explicativos literalmente; (5) se um número estiver ilegível, escreva [ilegível] em vez de inventar; "
          "(6) nΣo comente, não interprete. Se a página for só capa, separador ou legenda, transcreva o texto que houver.")
def one(fn):
    i = int(re.search(r"(\d+)\.png$", fn).group(1))
    cache = f"{work}/p{i:03d}.md"
    if os.path.exists(cache): return i, open(cache).read()
    b64 = base64.b64encode(open(f"{work}/{fn}", "rb").read()).decode()
    last = None
    for model in MODELS:
        for attempt in range(3):
            try:
                r = client.messages.create(model=model, max_tokens=12000, messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": PROMPT}]}])
                txt = "".join(getattr(b, "text", "") for b in r.content)
                open(cache, "w").write(txt); L(f"p{i} ok {model} {r.usage.input_tokens}/{r.usage.output_tokens}")
                return i, txt
            except anthropic.NotFoundError as e:
                last = e; L(f"p{i} model {model} not found"); break
            except Exception as e:
                last = e; L(f"p{i} err {type(e).__name__} {str(e)[:120]}"); time.sleep(5 * (attempt + 1))
    return i, f"[ERRO NA TRANSCRIÇÃO: {last}]"
res = {}
with cf.ThreadPoolExecutor(max_workers=5) as ex:
    for i, txt in ex.map(one, pngs): res[i] = txt
title = os.path.basename(pdf)
with open(out, "w") as f:
    f.write(f"# Transcrição integral — {title}\n\nFonte: relatório oficial da Quaest (PDF, {n} páginas). Transcrição página a página por modelo de visão; gráficos convertidos em tabelas; números em % salvo indicação. Marcadores `[ilegível]` indicam valores não legíveis na imagem.\n\n")
    for i in sorted(res):
        f.write(f"\n\n---\n\n## Página {i}\n\n{res[i].strip()}\n")
L("done"); print("done", out, os.path.getsize(out))
