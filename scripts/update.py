"""Baixa as taxas indicativas de debêntures da ANBIMA e gera data/debentures.json.

Fonte: arquivo diário público do Mercado Secundário de Debêntures
https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/dbAAMMDD.txt

Uso:
    python scripts/update.py              # busca os dias úteis recentes que faltam
    python scripts/update.py --dias 40    # janela maior (backfill)
    python scripts/update.py --arquivo db261009.txt   # usa um arquivo local (teste)
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

RAIZ = Path(__file__).resolve().parent.parent
EMISSORES = RAIZ / "emissores.json"
HISTORICO = RAIZ / "data" / "historico.json"
SAIDA = RAIZ / "data" / "debentures.json"
URL = "https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{}.txt"
MAX_DIAS_HISTORICO = 90  # dias de pregão guardados no histórico

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


def baixar(data: dt.date) -> str | None:
    url = URL.format(data.strftime("%y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (debentures-tracker)"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                bruto = r.read()
            texto = bruto.decode("latin-1")
            return texto if "@" in texto and "digo@" in texto else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  HTTP {e.code} em {url}", file=sys.stderr)
        except Exception as e:  # rede instável
            print(f"  erro em {url}: {e}", file=sys.stderr)
        time.sleep(3 * (tentativa + 1))
    return None


def parse(texto: str) -> list[dict]:
    linhas = []
    for linha in texto.splitlines():
        partes = linha.split("@")
        if len(partes) < 13 or partes[0].strip().startswith("C") and "digo" in partes[0]:
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
    mapa = {}
    for e in lista:
        for p in e["prefixos"]:
            mapa[p.upper()] = e["nome"]
    return lista, mapa


def emissor_de(codigo: str, mapa: dict) -> str | None:
    return mapa.get(codigo[:4].upper())


def dias_uteis_recentes(n: int) -> list[dt.date]:
    hoje = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()
    dias, d = [], hoje
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d -= dt.timedelta(days=1)
    return sorted(dias)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=8)
    ap.add_argument("--arquivo", action="append", help="arquivo local dbAAMMDD.txt (teste)")
    args = ap.parse_args()

    lista, mapa = carregar_emissores()
    hist = json.loads(HISTORICO.read_text(encoding="utf-8")) if HISTORICO.exists() else {}
    fichas: dict = hist.pop("_fichas", {})  # dados cadastrais mais recentes por código

    def registrar(data_iso: str, linhas: list[dict]):
        dia = {}
        for r in linhas:
            em = emissor_de(r["codigo"], mapa)
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
        print(f"  {data_iso}: {len(dia)} séries dos emissores acompanhados")

    if args.arquivo:
        for caminho in args.arquivo:
            nome = Path(caminho).stem  # dbAAMMDD
            data = dt.datetime.strptime(nome[2:8], "%y%m%d").date()
            registrar(data.isoformat(), parse(Path(caminho).read_text(encoding="latin-1")))
    else:
        for d in dias_uteis_recentes(args.dias):
            iso = d.isoformat()
            if iso in hist and hist[iso]:
                continue
            print(f"Baixando {iso}…")
            texto = baixar(d)
            if texto is None:
                print("  sem arquivo (feriado ou ainda não publicado)")
                continue
            registrar(iso, parse(texto))

    datas = sorted(k for k in hist if hist[k])[-MAX_DIAS_HISTORICO:]
    hist = {k: hist[k] for k in datas}
    if not datas:
        print("Nenhum dado disponível.", file=sys.stderr)
        sys.exit(1)

    ultima = datas[-1]
    anterior = datas[-2] if len(datas) > 1 else None
    semana = datas[-6] if len(datas) > 5 else datas[0]

    def var(cod, base, idx):
        if not base:
            return None
        a, b = hist[ultima].get(cod), hist[base].get(cod)
        if not a or not b or a[idx] is None or b[idx] is None:
            return None
        return round(a[idx] - b[idx], 4)

    series = []
    for cod, valores in hist[ultima].items():
        f = fichas.get(cod, {})
        taxa, pu, pct, dur = valores
        series.append({
            "codigo": cod, "emissor": f.get("emissor"), "nome": f.get("nome"),
            "vencimento": f.get("vencimento"), "indice": f.get("indice"),
            "ref_ntnb": f.get("ref_ntnb"),
            "taxa_indicativa": taxa, "taxa_compra": f.get("taxa_compra"), "taxa_venda": f.get("taxa_venda"),
            "pu": pu, "pct_par": pct,
            "duration_anos": round(dur / 252, 2) if dur else None,
            "var_taxa_1d": var(cod, anterior, 0), "var_taxa_5d": var(cod, semana, 0),
            "var_pct_par_1d": var(cod, anterior, 2), "var_pct_par_5d": var(cod, semana, 2),
            "historico": [[d, hist[d][cod][0], hist[d][cod][2]] for d in datas if cod in hist[d]],
        })

    ordem = {e["nome"]: i for i, e in enumerate(lista)}
    series.sort(key=lambda s: (ordem.get(s["emissor"], 99), s["codigo"]))
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps({
        "data_referencia": ultima, "data_anterior": anterior,
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "fonte": "ANBIMA — Mercado Secundário de Debêntures (taxas indicativas)",
        "emissores": [e["nome"] for e in lista], "series": series,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    hist["_fichas"] = fichas
    HISTORICO.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {len(series)} séries em {ultima}")


if __name__ == "__main__":
    main()
