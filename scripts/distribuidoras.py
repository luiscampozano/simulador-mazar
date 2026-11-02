"""Demanda en tiempo real por empresa distribuidora (CNEL Guayaquil, E.E. Quito, …) desde la página pública de
información operativa del Cenace (datos preliminares del SCADA, se actualizan cada 30 min). El Cenace solo muestra el
valor del momento, así que se guarda cada lectura para armar la curva del día (Luis, 1 nov: tormenta en Guayaquil,
"necesitamos una pestaña de demanda real nacional y por unidad de negocio").
Salida: registro/demanda_distribuidoras.json {"lecturas": [{"ts", "total", "anterior", "cnel", "empresas", "d": {nombre: MW}}]},
últimos 35 días."""
import html, json, os, re, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from robot import CENACE, EC, get

F = os.path.join("registro", "demanda_distribuidoras.json")


def num(s):
    s = re.sub(r"[^\d,.]", "", s or "")
    return float(s.replace(".", "").replace(",", ".")) if s else None


def leer_pagina():
    t = get(CENACE, intermedio_cenace=True, timeout=60).decode("utf-8", "replace")
    dist = {html.unescape(n).strip(): num(v) for n, v in re.findall(r"<title>([^<&]+)&#10;([\d\s.,]+)\s*MW</title>", t)}
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    i = txt.find("DEMANDAS EMPRESAS ELÉCTRICAS DE DISTRIBUCIÓN")
    bloque = txt[i:i + 400] if i >= 0 else ""
    def campo(et):
        m = re.search(et + r"\s+([\d\s]{1,7}\d)", bloque)
        return num(m.group(1)) if m else None
    return {"total": campo("DEMANDA TOTAL"), "anterior": campo("ANTERIOR"), "cnel": campo("DEMANDA CNEL"),
            "empresas": campo("EMPRESAS ELÉCTRICAS"), "d": {k: v for k, v in dist.items() if v is not None}}


def main():
    ahora = datetime.now(EC)
    try:
        x = leer_pagina()
    except Exception as e:
        print("Cenace no respondió:", str(e)[:150]); return
    if not x["d"] or not x["total"]:
        print("La página del Cenace no trae las distribuidoras ahora"); return
    try:
        reg = json.load(open(F, encoding="utf-8"))
    except Exception:
        reg = {"lecturas": []}
    ult = reg["lecturas"][-1] if reg["lecturas"] else None
    if ult and ult.get("d") == x["d"] and ult.get("total") == x["total"]:
        print("Sin cambios desde la lectura anterior"); return
    x["ts"] = ahora.isoformat(timespec="minutes")
    reg["lecturas"].append(x)
    lim = (ahora - timedelta(days=35)).isoformat()
    reg["lecturas"] = [r for r in reg["lecturas"] if r["ts"] >= lim]
    json.dump(reg, open(F, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{x['ts']}: total {x['total']} MW · CNEL Guayaquil {x['d'].get('CNEL GUAYAQUIL')} MW · {len(x['d'])} distribuidoras")


if __name__ == "__main__":
    main()
