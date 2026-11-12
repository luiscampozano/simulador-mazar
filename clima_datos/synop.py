"""DataLab Clima · lluvia medida en milímetros por las estaciones sinópticas (SYNOP) del Ecuador que siguen transmitiendo
(Luis, 2 nov: "haz lo del aeropuerto"). Es el mensaje que cada estación manda a la red mundial de la OMM; lo leemos de
OGIMET (público, sin clave), una sola consulta por corrida para todo el bloque 84.

Trae la lluvia acumulada por periodos (grupo 6RRRt: 1, 3, 6, 12 o 24 h) y, en la sección 333, el total de 24 h (7RRRR).
No es hora a hora: sirve para mostrar lo medido (p. ej. el aeropuerto de Guayaquil, el dato que cita la prensa) y para
contrastar con el Inamhi. NO entra en la calibración (la prueba del 28 oct mostró que no la mejora).
Salida: clima/registro/synop/ultimo.json y una copia diaria."""
import json, os, re, sys, urllib.request
from datetime import datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(AQUI, "registro", "synop")
EC = timezone(timedelta(hours=-5))
UA = {"User-Agent": "DataLab Ec (clima; datalabecuador.com)"}
# Solo estaciones que están junto a una ciudad nuestra (Baltra queda lejos de Puerto Ayora; Izobamba no es Quito)
ESTACIONES = {"84203": ("Guayaquil", "Aeropuerto de Guayaquil"), "84270": ("Loja", "La Argelia (Loja)"), "84179": ("Puyo", "El Puyo")}
HORAS_T = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}


def rrr(v):
    """Cantidad del grupo 6RRRt: 000–988 mm; 990 = trazas; 991–999 = 0,1–0,9 mm. Devuelve (mm, trazas)."""
    if not v.isdigit(): return None, False
    n = int(v)
    if n <= 988: return float(n), False
    if n == 990: return 0.0, True
    return round((n - 990) / 10, 1), False


def decodificar(msg):
    """Devuelve [(horas, mm, trazas, fuente)] de la sección 1 y de la 333. En la 333 solo se lee el primer 6RRRt y el
    primer 7RRRR (24 h en décimas) antes de los grupos de radiación/insolación (55xxx), que pueden empezar con 6."""
    g = msg.replace("=", "").split()
    if "AAXX" not in g: return []
    i = g.index("AAXX") + 3          # AAXX YYGGi IIiii → primer grupo de la sección 1 (iRixhVV)
    if i >= len(g) or g[i] == "NIL": return []
    s3 = g.index("333") if "333" in g else len(g)
    s5 = g.index("555") if "555" in g else len(g)
    out = []
    # Sección 1: hasta la 333 o la 555, lo que venga primero. Un 6RRRt presente se acepta aunque iR diga "omitido"
    # (la estación a veces codifica mal iR, p. ej. 31 oct 12Z: iR=3 con 60054).
    for x in g[i + 2:min(s3, s5)]:
        if len(x) == 5 and x[0] == "6" and x[4] in HORAS_T:
            mm, tr = rrr(x[1:4])
            if mm is not None: out.append((HORAS_T[x[4]], mm, tr, 1)); break
    visto6 = visto7 = False
    for x in g[s3 + 1:s5] if s3 < len(g) else []:
        if len(x) != 5: continue
        if x[:2] == "55": break       # 55SSS / 553SS: lo que sigue son grupos de radiación (j5FFFF)
        if x[0] == "6" and x[4] in HORAS_T and not visto6:
            mm, tr = rrr(x[1:4]); visto6 = True
            if mm is not None: out.append((HORAS_T[x[4]], mm, tr, 3))
        elif x[0] == "7" and x[1:].isdigit() and not visto7:
            v = int(x[1:]); visto7 = True
            out.append((24, 0.0 if v == 9999 else round(v / 10, 1), v == 9999, 7))
    return out


def main():
    ahora = datetime.now(timezone.utc)
    t0 = ahora - timedelta(hours=54)
    url = f"https://www.ogimet.com/cgi-bin/getsynop?block=84&begin={t0:%Y%m%d%H}00&end={ahora:%Y%m%d%H}00"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        txt = r.read().decode("utf-8", "replace")
    out = {}
    for linea in txt.splitlines():
        p = linea.split(",", 6)
        if len(p) < 7 or p[0] not in ESTACIONES: continue
        try:
            t = datetime(int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), tzinfo=timezone.utc).astimezone(EC)
        except ValueError:
            continue                  # línea malformada o encabezado
        ciudad, nombre = ESTACIONES[p[0]]
        e = out.setdefault(p[0], {"ciudad": ciudad, "nombre": nombre, "reportes": []})
        for h, mm, tr, fu in decodificar(p[6]):
            # mm caídos en las h horas que terminan a la hora del reporte (hora de Ecuador)
            e["reportes"].append({"fin": t.isoformat(timespec="minutes"), "horas": h, "mm": mm, "trazas": tr, "_f": fu})
    for e in out.values():
        # sin duplicados (un mismo periodo puede venir en dos grupos): se prefiere el 7RRRR (décimas) y luego la sección 1
        mejor = {}
        for x in e["reportes"]:
            k = (x["fin"], x["horas"]); pr = {7: 0, 1: 1, 3: 2}[x["_f"]]
            if k not in mejor or pr < mejor[k][0]: mejor[k] = (pr, x)
        rep = [x for _, x in sorted(mejor.values(), key=lambda v: (v[1]["fin"], v[1]["horas"]))]
        for x in rep: x.pop("_f", None)
        e["reportes"] = rep
        d24 = [x for x in rep if x["horas"] == 24]
        e["ultimo_24h"] = d24[-1] if d24 else None
        # el periodo de 6 h con más lluvia dentro de esas 24 h (para "lo más fuerte cayó entre…")
        if e["ultimo_24h"]:
            fin = datetime.fromisoformat(e["ultimo_24h"]["fin"]); ini = fin - timedelta(hours=24)
            seis = [x for x in rep if x["horas"] == 6 and ini + timedelta(hours=6) <= datetime.fromisoformat(x["fin"]) <= fin]
            e["max_6h"] = max(seis, key=lambda x: x["mm"]) if seis else None
        else:
            e["max_6h"] = None
    if not any(e["reportes"] for e in out.values()):
        # OGIMET respondió sin datos (cuota, caída): no se pisa el último dato bueno
        sys.exit("SYNOP: sin reportes de lluvia en esta consulta; se conserva el último archivo")
    res = {"actualizado": datetime.now(EC).isoformat(timespec="minutes"), "fuente": "SYNOP de la OMM vía OGIMET (ogimet.com)",
           "estaciones": out}
    os.makedirs(D, exist_ok=True)
    for f in (os.path.join(D, "ultimo.json"), os.path.join(D, datetime.now(EC).date().isoformat() + ".json")):
        with open(f, "w", encoding="utf-8") as fh: json.dump(res, fh, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: (v["nombre"], v["ultimo_24h"], v["max_6h"]) for k, v in out.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
