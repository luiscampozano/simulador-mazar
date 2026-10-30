"""Gasto de Gemini en el simulador de Mazar (revisor + segundo auditor), con tope mensual propio.
Luis (30 oct): "iterar a lo loco cuidando el gasto de Gemini". Topes: desde US$ 2 en el mes solo Flash (más barato);
desde US$ 4 no se llama a Gemini (el ciclo sigue con Claude). Separado del tope del clima (datalab-ec: US$ 5 / 8).
Archivo: laboratorio/gasto_gemini.json {"AAAA-MM": {"usd", "llamadas", "por_quien": {...}}}."""
import json, os
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(RAIZ, "laboratorio", "gasto_gemini.json")
PRECIO = {"gemini-4-argon": (2.00, 10.00), "gemini-3.8-flash": (0.75, 3.75)}   # US$ por millón de tokens (entrada, salida)
SOLO_FLASH, PARAR = 2.0, 4.0
EC = timezone(timedelta(hours=-5))


def _mes():
    return datetime.now(EC).strftime("%Y-%m")


def _leer():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def gasto_mes():
    return float((_leer().get(_mes()) or {}).get("usd", 0))


def modelos(lista):
    """Filtra la lista de modelos según el gasto del mes."""
    g = gasto_mes()
    if g >= PARAR:
        print(f"Gemini: tope del mes alcanzado (US$ {g:.2f} ≥ {PARAR}); no se llama")
        return []
    if g >= SOLO_FLASH:
        print(f"Gemini: US$ {g:.2f} este mes → solo Flash")
        return [m for m in lista if "flash" in m]
    return list(lista)


def anotar(quien, modelo, uso):
    pe, ps = PRECIO.get(modelo, (2.0, 10.0))
    usd = (uso.get("promptTokenCount", 0) * pe + (uso.get("candidatesTokenCount", 0) + uso.get("thoughtsTokenCount", 0)) * ps) / 1e6
    d = _leer(); m = d.setdefault(_mes(), {"usd": 0.0, "llamadas": 0, "por_quien": {}})
    m["usd"] = round(m["usd"] + usd, 5); m["llamadas"] += 1
    q = m["por_quien"].setdefault(quien, {"usd": 0.0, "llamadas": 0})
    q["usd"] = round(q["usd"] + usd, 5); q["llamadas"] += 1
    os.makedirs(os.path.dirname(F), exist_ok=True)
    json.dump(d, open(F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Gemini ({modelo}): US$ {usd:.4f} · Mazar en el mes US$ {m['usd']:.2f}")
    return usd
