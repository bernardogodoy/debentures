"""Dados da aba "Juros e crédito".

1. Curva de juros americana: Daily Treasury Par Yield Curve (home.treasury.gov), desde 2000.
2. Curva de juros brasileira: ETTJ da ANBIMA (prefixada, IPCA/real e inflação implícita).
   A ANBIMA só deixa baixar ~1 mês para trás, então o histórico é acumulado em data/mercado/br.json.
3. ICE BofA US High Yield OAS (FRED BAMLH0A0HYM2). O FRED só mostra os últimos ~3 anos
   desse índice, então o histórico também é acumulado (nada é apagado).
   O download direto do FRED (fredgraph.csv) não responde a servidores do GitHub; por isso o
   robô usa a API oficial do FRED quando há a chave FRED_API_KEY (segredo do repositório).

Uso: python scripts/mercado.py [--dias-br 30]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "mercado"
BRT = dt.timezone(dt.timedelta(hours=-3))
UA = {"User-Agent": "Mozilla/5.0 (debentures-tracker)"}

US_TENORES = [  # (coluna no CSV do Tesouro, rótulo, anos)
    ("1 Mo", "1M", 1 / 12), ("3 Mo", "3M", 0.25), ("6 Mo", "6M", 0.5), ("1 Yr", "1A", 1),
    ("2 Yr", "2A", 2), ("3 Yr", "3A", 3), ("5 Yr", "5A", 5), ("7 Yr", "7A", 7), ("10 Yr", "10A", 10),
    ("20 Yr", "20A", 20), ("30 Yr", "30A", 30),
]
US_DESDE = 2000
TESOURO = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           "{a}/all?type=daily_treasury_yield_curve&field_tdr_date_value={a}&page&_format=csv")
FRED_API = "https://api.stlouisfed.org/fred/series/observations?series_id={}&api_key={}&file_type=json"
HY_SERIE = "BAMLH0A0HYM2"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
ANBIMA_ETTJ = "https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp"


def http(url: str, dados: bytes | None = None, tentativas=3, timeout=90) -> bytes | None:
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, data=dados, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            print(f"  erro em {url.split('api_key=')[0]}: {e}", file=sys.stderr)
            time.sleep(4 * (i + 1))
    return None


def ler(caminho: Path, padrao):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else padrao


def gravar(caminho: Path, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def fred(serie: str) -> dict[str, float] | None:
    chave = os.environ.get("FRED_API_KEY", "").strip()
    if chave:
        bruto = http(FRED_API.format(serie, chave), timeout=60)
        if not bruto:
            return None
        obs = json.loads(bruto).get("observations", [])
        return {o["date"]: float(o["value"]) for o in obs if o.get("value") not in (None, "", ".")}
    bruto = http(FRED.format(serie), tentativas=1, timeout=25)
    if not bruto:
        print(f"  FRED {serie}: sem resposta e sem FRED_API_KEY configurada", file=sys.stderr)
        return None
    out = {}
    for linha in csv.reader(io.StringIO(bruto.decode("utf-8"))):
        if len(linha) == 2 and linha[0][:2] in ("19", "20") and linha[1] not in ("", "."):
            try:
                out[linha[0]] = float(linha[1])
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------- EUA
def tesouro_ano(ano: int) -> dict[str, list] | None:
    bruto = http(TESOURO.format(a=ano), timeout=60)
    if not bruto:
        return None
    linhas = list(csv.reader(io.StringIO(bruto.decode("utf-8-sig"))))
    if not linhas or linhas[0][0].strip() != "Date":
        return None
    cab = [c.strip() for c in linhas[0]]
    col = [cab.index(t[0]) if t[0] in cab else None for t in US_TENORES]
    out = {}
    for l in linhas[1:]:
        try:
            m, d, a = l[0].split("/")
        except ValueError:
            continue
        vals = []
        for c in col:
            try:
                vals.append(float(l[c]) if c is not None and l[c].strip() not in ("", "N/A") else None)
            except (ValueError, IndexError):
                vals.append(None)
        if any(v is not None for v in vals):
            out[f"{a}-{m}-{d}"] = vals
    return out


def atualizar_us():
    arq = DIR / "us.json"
    atual = ler(arq, {"dados": {}})
    atual["tenores"] = [t[1] for t in US_TENORES]
    atual["anos"] = [t[2] for t in US_TENORES]
    hoje = dt.datetime.now(BRT).date()
    tem = set(int(d[:4]) for d in atual["dados"])
    # anos que faltam (primeira carga) + o ano corrente (e o anterior, no começo de janeiro)
    anos = [a for a in range(US_DESDE, hoje.year + 1) if a not in tem]
    anos += [hoje.year] + ([hoje.year - 1] if hoje.month == 1 else [])
    ok = 0
    for a in sorted(set(anos)):
        dados = tesouro_ano(a)
        if dados is None:
            print(f"  Tesouro {a}: falhou, mantendo dados salvos")
            continue
        atual["dados"].update(dados)
        ok += 1
        time.sleep(0.3)
    atual["dados"] = {d: atual["dados"][d] for d in sorted(atual["dados"])}
    gravar(arq, atual)
    if atual["dados"]:
        print(f"  EUA: {len(atual['dados'])} dias, de {min(atual['dados'])} a {max(atual['dados'])} ({ok} ano(s) baixado(s))")


# ---------------------------------------------------------------- HY OAS
def atualizar_hy():
    arq = DIR / "hy.json"
    atual = dict(ler(arq, []))
    s = fred(HY_SERIE)
    if s is None:
        print("  HY OAS: falhou, mantendo dados salvos")
        return
    atual.update(s)
    gravar(arq, [[d, atual[d]] for d in sorted(atual)])
    print(f"  HY OAS: {len(atual)} dias, de {min(atual)} a {max(atual)}")


# ---------------------------------------------------------------- Brasil
def _num(txt: str):
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_ettj(texto: str):
    """Devolve {'pre': [[du, taxa]...], 'ipca': [...], 'infl': [...]} ou None."""
    linhas = [l.strip() for l in texto.splitlines()]
    pre, ipca, infl, curto = {}, [], [], {}
    secao = None
    for l in linhas:
        if not l:
            secao = None if secao != "ettj_cab" else secao
            continue
        if l.startswith("ETTJ Infla"):
            secao = "ettj_cab"; continue
        if l.startswith("PREFIXADOS (CIRCULAR"):
            secao = "circ_cab"; continue
        if l.startswith("Erro T"):
            secao = None; continue
        if secao == "ettj_cab" and l.startswith("Vertices"):
            secao = "ettj"; continue
        if secao == "circ_cab" and l.startswith("Vertices"):
            secao = "circ"; continue
        p = l.split(";")
        if secao == "ettj" and len(p) >= 4:
            du = _num(p[0])
            if du is None:
                continue
            a, b, c = _num(p[1]), _num(p[2]), _num(p[3])
            if a is not None: ipca.append([int(du), a])
            if b is not None: pre[int(du)] = b
            if c is not None: infl.append([int(du), c])
        elif secao == "circ" and len(p) >= 2:
            du, tx = _num(p[0]), _num(p[1])
            if du is not None and tx is not None and int(du) < 252:
                curto[int(du)] = tx
    if not pre or not ipca:
        return None
    pre.update(curto)
    return {"pre": [[k, pre[k]] for k in sorted(pre)], "ipca": ipca, "infl": infl}


def baixar_ettj(d: dt.date):
    corpo = urllib.parse.urlencode({
        "escolha": "2", "Idioma": "PT", "saida": "csv",
        "Dt_Ref_Ver": d.strftime("%Y%m%d"), "Dt_Ref": d.strftime("%d/%m/%Y"),
    }).encode()
    bruto = http(ANBIMA_ETTJ, corpo, tentativas=2)
    if not bruto:
        return None
    texto = bruto.decode("latin-1")
    if not texto.startswith(d.strftime("%d/%m/%Y")):
        return None  # data indisponível (feriado ou fora da janela da ANBIMA)
    return parse_ettj(texto)


def atualizar_br(dias: int):
    arq = DIR / "br.json"
    atual = ler(arq, {"dados": {}})
    hoje = dt.datetime.now(BRT).date()
    d, vistos, novos = hoje, 0, 0
    while vistos < dias:
        if d.weekday() < 5:
            vistos += 1
            iso = d.isoformat()
            if iso not in atual["dados"]:
                curva = baixar_ettj(d)
                if curva:
                    atual["dados"][iso] = curva
                    novos += 1
                time.sleep(0.4)
        d -= dt.timedelta(days=1)
    atual["dados"] = {k: atual["dados"][k] for k in sorted(atual["dados"])}
    gravar(arq, atual)
    if atual["dados"]:
        print(f"  Brasil: {len(atual['dados'])} dias (+{novos}), de {min(atual['dados'])} a {max(atual['dados'])}")
    else:
        print("  Brasil: nenhum dia disponível")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias-br", type=int, default=30)
    args = ap.parse_args()
    for nome, f in (("EUA", atualizar_us), ("HY", atualizar_hy), ("Brasil", lambda: atualizar_br(args.dias_br))):
        try:
            f()
        except Exception as e:  # uma fonte fora do ar não derruba as outras
            print(f"  {nome}: erro inesperado: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
