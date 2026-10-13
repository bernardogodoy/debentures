"""Atualiza os dados do site.

1. ANBIMA — taxas indicativas diárias (arquivo público dbAAMMDD.txt, disponível só por ~20 dias úteis).
   Cada pregão baixado é guardado para sempre em data/historico.json.
2. SND — histórico completo de negócios de cada série (preço efetivamente negociado).

Saídas:
- data/debentures.json      foto do último dia + últimos pontos para o mini-gráfico (lido pela página)
- data/series/CODIGO.json   histórico completo da série (ANBIMA + negócios SND), lido ao abrir a série
- data/historico.json       base acumulada da ANBIMA
- data/negocios/CODIGO.json base acumulada do SND

Uso:
    python scripts/update.py                     # rotina diária
    python scripts/update.py --dias 40           # janela maior na ANBIMA
    python scripts/update.py --snd-completo      # rebaixa o histórico inteiro do SND
    python scripts/update.py --sem-snd           # pula o SND (teste)
    python scripts/update.py --arquivo db261009.txt --sem-snd   # arquivo local (teste)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snd  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
EMISSORES = RAIZ / "emissores.json"
HISTORICO = DADOS / "historico.json"
SAIDA = DADOS / "debentures.json"
DIR_SERIES = DADOS / "series"
DIR_NEGOCIOS = DADOS / "negocios"
URL = "https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{}.txt"
PONTOS_MINI = 60          # pontos no mini-gráfico da lista
SND_REJANELA_DIAS = 15    # na rotina diária, rebaixa os últimos N dias do SND (correções/atrasos)
BRT = dt.timezone(dt.timedelta(hours=-3))

COLUNAS = [
    "codigo", "nome", "vencimento", "indice", "taxa_compra", "taxa_venda",
    "taxa_indicativa", "desvio_padrao", "int_min", "int_max", "pu", "pct_par",
    "duration", "pct_reune", "ref_ntnb",
]


def numero(txt: str):
    txt = (txt or "").strip()
    if txt in ("", "--", "N/D"):
        return None
    try:
        return float(txt.replace(".", "").replace(",", ".")) if "," in txt else float(txt)
    except ValueError:
        return None


def baixar_anbima(data: dt.date) -> str | None:
    url = URL.format(data.strftime("%y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (debentures-tracker)"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                texto = r.read().decode("latin-1")
            return texto if "@" in texto and "digo@" in texto else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  HTTP {e.code} em {url}", file=sys.stderr)
        except Exception as e:
            print(f"  erro em {url}: {e}", file=sys.stderr)
        time.sleep(3 * (tentativa + 1))
    return None


def parse_anbima(texto: str) -> list[dict]:
    linhas = []
    for linha in texto.splitlines():
        partes = linha.split("@")
        if len(partes) < 13 or (partes[0].strip().startswith("C") and "digo" in partes[0]):
            continue
        reg = dict(zip(COLUNAS, [p.strip() for p in partes] + [""] * (len(COLUNAS) - len(partes))))
        if not reg["codigo"]:
            continue
        reg["nome"] = reg["nome"].replace("(*)", "").replace("(**)", "").strip()
        for k in ("taxa_compra", "taxa_venda", "taxa_indicativa", "desvio_padrao", "int_min",
                  "int_max", "pu", "pct_par", "duration", "pct_reune"):
            reg[k] = numero(reg[k])
        linhas.append(reg)
    return linhas


def carregar_emissores():
    lista = json.loads(EMISSORES.read_text(encoding="utf-8"))
    mapa = {p.upper(): e["nome"] for e in lista for p in e["prefixos"]}
    return lista, mapa


def dias_uteis_recentes(n: int) -> list[dt.date]:
    hoje = dt.datetime.now(BRT).date()
    dias, d = [], hoje
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d -= dt.timedelta(days=1)
    return sorted(dias)


def ler_json(caminho: Path, padrao):
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else padrao


def gravar_json(caminho: Path, obj, compacto=True):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compacto else \
        json.dumps(obj, ensure_ascii=False, indent=1)
    caminho.write_text(txt, encoding="utf-8")


def atualizar_snd(codigos: list[str], completo: bool) -> dict[str, list]:
    """Atualiza data/negocios/*.json e devolve {codigo: linhas}."""
    hoje = dt.datetime.now(BRT).date()
    fim = hoje.strftime("%d/%m/%Y")
    saida = {}
    for cod in codigos:
        arq = DIR_NEGOCIOS / f"{cod}.json"
        atuais = ler_json(arq, [])
        if atuais and not completo:
            ultimo = dt.date.fromisoformat(atuais[-1][0])
            ini = (ultimo - dt.timedelta(days=SND_REJANELA_DIAS)).strftime("%d/%m/%Y")
        else:
            ini = "01/01/2000"
        novos = snd.baixar(cod, ini, fim)
        if novos is None:
            print(f"  SND {cod}: falhou, mantendo {len(atuais)} dias já salvos")
            saida[cod] = atuais
            continue
        por_data = {l[0]: l for l in atuais}
        por_data.update({l[0]: l for l in novos})
        linhas = [por_data[k] for k in sorted(por_data)]
        if linhas != atuais:
            gravar_json(arq, linhas)
        print(f"  SND {cod}: {len(linhas)} dias com negócios (+{len(linhas) - len(atuais)})")
        saida[cod] = linhas
        time.sleep(1)
    return saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=8)
    ap.add_argument("--arquivo", action="append", help="arquivo local dbAAMMDD.txt (teste)")
    ap.add_argument("--sem-snd", action="store_true")
    ap.add_argument("--snd-completo", action="store_true")
    args = ap.parse_args()

    lista, mapa = carregar_emissores()
    hist = ler_json(HISTORICO, {})
    fichas: dict = hist.pop("_fichas", {})

    def registrar(data_iso: str, linhas: list[dict]):
        dia = {}
        for r in linhas:
            em = mapa.get(r["codigo"][:4].upper())
            if not em:
                continue
            dia[r["codigo"]] = [r["taxa_indicativa"], r["pu"], r["pct_par"], r["duration"]]
            ficha = fichas.get(r["codigo"])
            if not ficha or ficha.get("_data", "") <= data_iso:
                fichas[r["codigo"]] = {
                    "_data": data_iso, "emissor": em, "nome": r["nome"], "vencimento": r["vencimento"],
                    "indice": r["indice"], "ref_ntnb": r["ref_ntnb"],
                    "taxa_compra": r["taxa_compra"], "taxa_venda": r["taxa_venda"],
                    "int_min": r["int_min"], "int_max": r["int_max"], "pct_reune": r["pct_reune"],
                }
        hist[data_iso] = dia
        print(f"  ANBIMA {data_iso}: {len(dia)} séries dos emissores acompanhados")

    if args.arquivo:
        for caminho in args.arquivo:
            data = dt.datetime.strptime(Path(caminho).stem[2:8], "%y%m%d").date()
            registrar(data.isoformat(), parse_anbima(Path(caminho).read_text(encoding="latin-1")))
    else:
        for d in dias_uteis_recentes(args.dias):
            iso = d.isoformat()
            if hist.get(iso):
                continue
            texto = baixar_anbima(d)
            if texto is None:
                continue
            registrar(iso, parse_anbima(texto))

    datas = sorted(k for k in hist if hist[k])  # sem limite: o histórico só cresce
    if not datas:
        print("Nenhum dado da ANBIMA disponível.", file=sys.stderr)
        sys.exit(1)
    ultima = datas[-1]
    anterior = datas[-2] if len(datas) > 1 else None
    semana = datas[-6] if len(datas) > 5 else datas[0]

    # séries acompanhadas = as que aparecem no último dia da ANBIMA (mais as que já tinham ficha)
    codigos = sorted(set(hist[ultima]) | {c for c, f in fichas.items() if f.get("emissor")})
    codigos = [c for c in codigos if mapa.get(c[:4].upper())]

    negocios = {} if args.sem_snd else atualizar_snd(codigos, args.snd_completo)
    if args.sem_snd:
        negocios = {c: ler_json(DIR_NEGOCIOS / f"{c}.json", []) for c in codigos}

    def var(cod, base, idx):
        if not base:
            return None
        a, b = hist[ultima].get(cod), hist[base].get(cod)
        if not a or not b or a[idx] is None or b[idx] is None:
            return None
        return round(a[idx] - b[idx], 4)

    series = []
    for cod in codigos:
        if cod not in hist[ultima]:
            continue
        f = fichas.get(cod, {})
        taxa, pu, pct, dur = hist[ultima][cod]
        anbima = [[d, *hist[d][cod]] for d in datas if cod in hist[d]]  # [data, taxa, pu, pct_par, duration]
        neg = negocios.get(cod, [])
        gravar_json(DIR_SERIES / f"{cod}.json", {
            "codigo": cod, "emissor": f.get("emissor"), "atualizado": ultima,
            "anbima": anbima, "negocios": neg,
        })
        ult_neg = neg[-1] if neg else None
        series.append({
            "codigo": cod, "emissor": f.get("emissor"), "nome": f.get("nome"),
            "vencimento": f.get("vencimento"), "indice": f.get("indice"), "ref_ntnb": f.get("ref_ntnb"),
            "taxa_indicativa": taxa, "taxa_compra": f.get("taxa_compra"), "taxa_venda": f.get("taxa_venda"),
            "pu": pu, "pct_par": pct,
            "duration_anos": round(dur / 252, 2) if dur else None,
            "var_taxa_1d": var(cod, anterior, 0), "var_taxa_5d": var(cod, semana, 0),
            "var_pct_par_1d": var(cod, anterior, 2), "var_pct_par_5d": var(cod, semana, 2),
            "historico": [[a[0], a[1], a[3]] for a in anbima[-PONTOS_MINI:]],
            "negocios_dias": len(neg),
            "negocios_desde": neg[0][0] if neg else None,
            "ultimo_negocio": {"data": ult_neg[0], "qtd": ult_neg[1], "n": ult_neg[2],
                               "pu_medio": ult_neg[4], "pct_curva": ult_neg[6]} if ult_neg else None,
        })

    ordem = {e["nome"]: i for i, e in enumerate(lista)}
    series.sort(key=lambda s: (ordem.get(s["emissor"], 99), s["codigo"]))
    gravar_json(SAIDA, {
        "data_referencia": ultima, "data_anterior": anterior,
        "anbima_desde": datas[0],
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "fonte": "ANBIMA (taxas indicativas) e SND/debentures.com.br (negócios)",
        "emissores": [e["nome"] for e in lista], "series": series,
    }, compacto=False)
    hist["_fichas"] = fichas
    gravar_json(HISTORICO, hist)
    print(f"OK: {len(series)} séries em {ultima}; ANBIMA desde {datas[0]} ({len(datas)} pregões)")


if __name__ == "__main__":
    main()
