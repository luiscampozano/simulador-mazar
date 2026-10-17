"""Robot de GitHub: lee la cota de Mazar y el caudal de entrada desde el
servicio de datos del panel de Celec Sur y actualiza datos.json.

Solo toca: cota, fecha, etiqueta, el punto de hoy en historico,
hoy.qMazar (promedio de las últimas 24 lecturas) y el bloque "robot".
La calibración completa la hace la tarea diaria de Claude.
"""
import json, sys, urllib.request
from datetime import datetime, timedelta, timezone

EC = timezone(timedelta(hours=-5))
BASE = "https://generacioncsr.celec.gob.ec:8443/ords/csr/sardomcsr/pointValues"
MRID_COTA = 30031      # cota embalse Mazar (msnm)
MRID_CAUDAL = 30538    # caudal de entrada a Mazar (m³/s)
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def lecturas(mrid, dia):
    """Valores horarios de un día local de Ecuador: [(datetime_ec, valor)]."""
    ini = datetime(dia.year, dia.month, dia.day, 1, tzinfo=EC).astimezone(timezone.utc)
    fin = ini + timedelta(hours=23)
    url = (f"{BASE}?mrid={mrid}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
           f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={dia:%d/%m/%Y}%2001:00:00")
    req = urllib.request.Request(url, headers={"User-Agent": "simulador-mazar-robot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r).get("items", [])
    out = []
    for it in items:
        v = it.get("valueedit")
        if v is None:
            continue
        t = datetime.strptime(it["loctimestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        out.append((t.astimezone(EC), float(v)))
    return sorted(out)


def serie(mrid, ahora):
    hoy = ahora.date()
    return lecturas(mrid, hoy - timedelta(days=1)) + lecturas(mrid, hoy)


def main():
    ahora = datetime.now(EC)
    cotas = serie(MRID_COTA, ahora)
    if not cotas:
        print("Celec no devolvió lecturas de cota; no se cambia nada.")
        return 0
    t, cota = cotas[-1]
    if not (2090 < cota < 2160):
        print(f"Cota fuera de rango ({cota}); no se cambia nada.")
        return 0

    with open("datos.json", encoding="utf-8") as f:
        datos = json.load(f)

    previa = datetime.fromisoformat(datos["fecha"])
    if t <= previa:
        print(f"Sin lectura nueva (última {t:%Y-%m-%d %H:%M}, datos.json {previa:%Y-%m-%d %H:%M}).")
        return 0

    caudales = serie(MRID_CAUDAL, ahora)
    ult24 = [v for (tt, v) in caudales if tt > t - timedelta(hours=24) and 0 <= v < 2000]
    q24 = round(sum(ult24) / len(ult24)) if len(ult24) >= 12 else None

    cota = round(cota, 2)
    datos["cota"] = cota
    datos["fecha"] = t.isoformat()
    datos["etiqueta"] = (f"cota al {DIAS[t.weekday()]} {t.day} {MESES[t.month-1]} {t.year}, "
                         f"{t:%H:%M} (lectura automática de Celec Sur)")
    hoy_txt = t.strftime("%Y-%m-%d")
    hist = [p for p in datos.get("historico", []) if p[0] != hoy_txt]
    hist.append([hoy_txt, cota])
    datos["historico"] = sorted(hist)[-45:]

    hace24 = [v for (tt, v) in cotas if abs((tt - (t - timedelta(hours=24))).total_seconds()) <= 1800]
    variacion = round(cota - hace24[0], 2) if hace24 else None

    if q24 is not None:
        datos["hoy"]["qMazar"] = max(5, min(120, q24))
        datos.setdefault("notas", {})["mazar"] = (
            f"Promedio de las últimas 24 h: {q24} m³/s (panel Celec Sur, lectura de las {t:%H:%M}). "
            "Promedio histórico de octubre: 66 m³/s.")

    datos["robot"] = {
        "ultima_lectura": t.isoformat(),
        "caudal_entrada_24h": q24,
        "variacion_cota_24h": variacion,
        "fuente": "generacioncsr.celec.gob.ec (mrid 30031 cota, 30538 caudal)",
    }

    with open("datos.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Actualizado: cota {cota} msnm a las {t:%Y-%m-%d %H:%M}, caudal 24 h {q24}, variación 24 h {variacion}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
