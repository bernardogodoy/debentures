"""Histórico de negócios do SND (debentures.com.br) — Preços de Negociação.

Para cada ativo e período, o SND devolve um dia por linha com:
quantidade negociada, número de negócios, PU mínimo, médio e máximo e % do PU da curva.
São preços de negócios efetivamente registrados (não preços indicativos).
"""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.parse
import urllib.request

URL = "https://www.debentures.com.br/exploreosnd/consultaadados/mercadosecundario/precosdenegociacao_r.asp"
_RE_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_RE_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _num(txt: str):
    txt = txt.strip()
    if not txt or txt in ("-", "--"):
        return None
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _iso(data_br: str) -> str:
    d, m, a = data_br.split("/")
    return f"{a}-{m}-{d}"


def parse(texto: str, codigo: str) -> list[list]:
    """Retorna [[data_iso, qtd, n_negocios, pu_min, pu_medio, pu_max, pct_curva], ...] em ordem cronológica."""
    linhas = {}
    for tr in _RE_TR.findall(texto):
        cels = [html.unescape(_RE_TAG.sub("", td)).strip() for td in _RE_TD.findall(tr)]
        cels = [c for c in cels if c]
        if len(cels) < 10 or not _RE_DATA.match(cels[0]) or cels[2].upper() != codigo.upper():
            continue
        # data, emissor, ativo, isin, qtd, negócios, mín, médio, máx, %curva
        linhas[_iso(cels[0])] = [
            _iso(cels[0]), _num(cels[4]), _num(cels[5]), _num(cels[6]), _num(cels[7]), _num(cels[8]), _num(cels[9]),
        ]
    return [linhas[k] for k in sorted(linhas)]


def baixar(codigo: str, dt_ini: str, dt_fim: str) -> list[list] | None:
    """dt_ini/dt_fim no formato DD/MM/AAAA. Retorna None se a consulta falhar."""
    corpo = urllib.parse.urlencode({
        "op_exc": "Nada", "emissor": "", "ativo": codigo, "ISIN": "", "dt_ini": dt_ini, "dt_fim": dt_fim,
    }).encode()
    req = urllib.request.Request(URL, data=corpo, headers={
        "User-Agent": "Mozilla/5.0 (debentures-tracker)",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return parse(r.read().decode("latin-1"), codigo)
        except Exception as e:
            print(f"  SND {codigo}: erro ({e})", file=sys.stderr)
            time.sleep(4 * (tentativa + 1))
    return None
