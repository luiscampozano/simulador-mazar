"""DataLab Ec · registro de temperatura pública del Inamhi en la Costa cada 10 min (Luis, 15 nov). Temperatura "ahora"
(tiempo-real) de cada ciudad pública de scripts/puntos_satelite.json; no muestra nada en la página.
Guarda salida/temperaturas_estado.json: {"dia", "serie": {ciudad: [["HH:MM", °C, edad, km, n], ...]}, "ayer": {...}}
por día calendario de Ecuador (00:00–24:00)."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = "salida/temperaturas_estado.json"
COSTA = ["Guayaquil", "Samborondón", "Durán", "Daule/Nobol", "Milagro", "Babahoyo", "Quevedo", "Santo Domingo",
         "Santa Elena", "Machala", "Manta", "Portoviejo", "Esmeraldas"]


def punto(P, c):
    L = P.get(c) or []
    for n, la, lo in L:
        if n.startswith("Centro"): return la, lo
    return (L[0][1], L[0][2]) if L else None


def temp(la, lo):
    try:
        j = requests.get(f"https://servicios.inamhi.gob.ec/wp-json/inamhi/v1/tiempo-real?lat={la}&lon={lo}", timeout=10).json()
        t = j.get("temp") or {}
        v, edad = t.get("now_c"), t.get("newest_age_minutes")
        if v is None or not (5 <= v <= 45) or (edad is not None and edad > 40): return None
        return [round(v, 1), None if edad is None else round(edad), t.get("km"), t.get("stations")]
    except Exception:
        return None


def main():
    ahora = datetime.now(timezone.utc) - timedelta(hours=5)
    dia, hm = ahora.date().isoformat(), ahora.strftime("%H:%M")
    P = json.load(open(os.path.join(AQUI, "puntos_satelite.json")))
    pts = {c: punto(P, c) for c in COSTA if punto(P, c)}
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(pts, ex.map(lambda c: temp(*pts[c]), pts)))
    if os.path.exists(ESTADO):
        E = json.load(open(ESTADO))
    else:   # bucle recién arrancado: se sigue con lo publicado
        for i in range(3):   # reintentos: si no se puede leer (salvo que no exista) no se empieza de cero
            try:
                r = requests.get("https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/temperaturas_estado.json", timeout=10)
                E = {} if r.status_code == 404 else (r.raise_for_status() or r.json()); break
            except Exception:
                if i == 2: raise
                time.sleep(3)
    if E.get("dia") != dia:
        E = {"dia": dia, "serie": {}, "ayer": {"dia": E["dia"], "serie": E.get("serie", {})} if E.get("dia") else None}
    for c, v in res.items():
        if v is None: continue
        s = E["serie"].setdefault(c, [])
        if not s or s[-1][0] != hm: s.append([hm] + v)   # [hora, °C, edad del dato (min), km a la estación, nº de estaciones]
    json.dump(E, open(ESTADO + ".tmp", "w"), ensure_ascii=False, separators=(",", ":"))
    os.replace(ESTADO + ".tmp", ESTADO)   # escritura atómica
    print(f"temperaturas {hm}: {sum(v is not None for v in res.values())}/{len(pts)} ciudades")


if __name__ == "__main__":
    main()
