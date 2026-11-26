"""Sombra de PARDIG (Luis, 26 nov 2026): lluvia del día según PARDIG-NRT (Google DeepMind / Google Research, CC BY 4.0)
comparada con lo que midió el Inamhi y con nuestra lluvia del día 3D (satélite GOES-19), ciudad por ciudad.

No cambia nada visible: solo registra. Se decide tras >= 14 días (idealmente 20) contando DÍAS, no filas.

Día = día calendario de Ecuador (00:00–24:00 local = 05:00–05:00 UTC), igual que el reporte diario del Inamhi y la
lluvia del día 3D. PARDIG da intensidad instantánea (m/h) cada 15 min en celdas de 0,1°; el total del día es
sum(intensidad) × 0,25 h × 1000.

Guarda:
  registro/sombra_pardig.json      una fila por día y ciudad + resumen (error medio por fuente, días contados)
  registro/pardig/<día>.json       total del día de PARDIG sobre Ecuador (malla 0,1°, décimas de mm en uint16, base64)

Fuente: © Google LLC, PARDIG (Precipitation AI Reanalysis – Densely Inferred GPM), CC BY 4.0. Experimental:
"no es una observación oficial ni un aviso".
"""
import base64, datetime as D, json, math, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

CONGELADO = "2026-11-26"   # la comparación (ciudades, celda más cercana y 3×3) no se cambia durante la prueba
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F_SOMBRA = os.path.join(RAIZ, "registro", "sombra_pardig.json")
D_MALLA = os.path.join(RAIZ, "registro", "pardig")
B = "https://storage.googleapis.com/pardig_1/NRT/zarr/2026_to_present/"
# Ecuador continental y Galápagos: latitud -5,0…+2,1 (filas 850–920), longitud -92,0…-75,0 (columnas 2680–2850)
I0, I1, J0, J1 = 850, 922, 2680, 2851
# Nombres del reporte del Inamhi → punto público (ciudades que no están igual en puntos_satelite.json)
EXTRA = {"Salinas": (-2.21, -80.97), "Quito Norte": (-0.13, -78.48), "Quito Sur": (-0.27, -78.54),
         "Cumbayá – Tumbaco": (-0.20, -78.43), "Valle de los Chillos": (-0.31, -78.45), "Shell–Mera": (-1.50, -78.06),
         "San Cristóbal": (-0.90, -89.61), "Santa Cruz": (-0.74, -90.31), "Isabela": (-0.96, -90.97),
         "Santa Rosa": (-3.45, -79.96), "Gualaquiza": (-3.40, -78.58)}
RADIO_CORR_KM = 45   # revisor: 3 × σ (15 km) de la corrección con estaciones de la lluvia 3D: ahí el satélite no es independiente
LICENCIA = ("CC BY 4.0 https://creativecommons.org/licenses/by/4.0/ — modificado por DataLab Ec: total diario "
            "05–05 UTC recortado a Ecuador")


def _json(url, t=60):
    req = urllib.request.Request(url, headers={"User-Agent": "DataLabEc-sombra-pardig"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode("utf-8"))


def ciudades():
    p = json.load(open(os.path.join(RAIZ, "scripts", "puntos_satelite.json"), encoding="utf-8"))
    out = {}
    for c, pts in p.items():
        cen = next((x for x in pts if x[0] == "Centro"), pts[0])
        out[c] = (cen[1], cen[2])
    out.update(EXTRA)
    return out


def leer_marco(t):
    import zarr
    try:
        g = zarr.open_group(B + t.strftime("%Y%m%dT%H%M%S") + "/predictions.zarr", mode="r")
        a = g["precipitation"][I0:I1, J0:J1]
        return None if np.isnan(a).any() else a   # revisor: un marco con huecos cuenta como faltante
    except Exception:
        return None


def pardig_dia(dia):
    """Total del día (mm) sobre la caja de Ecuador y cuántos de los 96 cuartos de hora había."""
    t0 = D.datetime.fromisoformat(dia) + D.timedelta(hours=5)
    with ThreadPoolExecutor(16) as ex:
        F = list(ex.map(leer_marco, [t0 + D.timedelta(minutes=15 * k) for k in range(96)]))
    ok = [f for f in F if f is not None]
    if not ok:
        return None, 0
    tot = np.array(ok, dtype=np.float32).sum(0) * 0.25 * 1000.0
    return np.clip(tot, 0, None), len(ok)


def en_punto(tot, la, lo):
    lat0, lon0 = -90 + 0.1 * I0, 0.1 * J0 - 360   # celda (i, j) = (lat0 + 0,1 i, lon0 + 0,1 j)
    i, j = int(round((la - lat0) / 0.1)), int(round((lo - lon0) / 0.1))
    if not (1 <= i < tot.shape[0] - 1 and 1 <= j < tot.shape[1] - 1):
        return None, None
    return round(float(tot[i, j]), 1), round(float(tot[i - 1:i + 2, j - 1:j + 2].mean()), 1)


def inamhi(dia):
    j = _json(f"https://servicios.inamhi.gob.ec/wp-json/inamhi/v1/reporte-diario?fecha={dia}")
    out = {}
    for c in j.get("ciudades") or []:
        l = c.get("lluvia") or {}
        mm, h = l.get("total_mm"), l.get("horas")
        if isinstance(mm, (int, float)) and 0 <= mm <= 400 and isinstance(h, (int, float)):
            out[c.get("ciudad")] = {"mm": float(mm), "horas": int(h)}
    return out


def satelite(dia):
    """Nuestra lluvia del día 3D por ciudad (solo si la página ya publicó ese día)."""
    try:
        a = _json("https://datalabecuador.com/3d/d/acumulada.json")
    except Exception as e:
        print("acumulada.json:", str(e)[:80]); return None
    if a.get("dia") != dia:
        return None
    C, est = ciudades(), (a.get("estaciones") or {})
    def cerca(c):   # a menos de RADIO_CORR_KM de alguna ciudad que corrigió la lluvia 3D ese día
        if c not in C: return True   # sin coordenada no se puede saber: se trata como no independiente
        la, lo = C[c]
        for e in est:
            if e in C:
                la2, lo2 = C[e]
                if math.hypot((la - la2) * 110.6, (lo - lo2) * 111.3 * math.cos(math.radians(la))) <= RADIO_CORR_KM:
                    return True
        return False
    out = {c: {"mm": v, "corregido": cerca(c)} for c, v in (a.get("ciudades") or {}).items()}
    for e, v in est.items():   # en la propia ciudad corregida se usa el valor del satélite antes de corregir
        if e in out and isinstance((v or {}).get("satelite"), (int, float)):
            out[e] = {"mm": v["satelite"], "corregido": False}
    meta = {"desde": a.get("desde"), "imagenes": a.get("imagenes"), "horas_con_datos": a.get("horas_con_datos")}
    return out, meta


def guardar(ruta, obj):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


def resumen(dias):
    """Revisor 26 nov: comparación PAREADA (solo filas donde las dos fuentes y el Inamhi tienen valor, PARDIG con los 96
    cuartos de hora y satélite no corregido), error absoluto medio de CADA DÍA y luego mediana entre días, más los días
    que gana cada una. Criterio de decisión (congelado): con >= 14 días pareados, PARDIG reemplaza al satélite como base
    si gana la mediana diaria y gana en >= 60 % de los días; si no, sigue solo como complemento."""
    def par(a, b, filtro_sat):
        por_dia = []
        for d, filas in sorted(dias.items()):
            m = filas.get("_") or {}
            if m.get("marcos") != 96: continue
            if filtro_sat and sum((m.get("satelite_info") or {}).get("horas_con_datos") or []) < 24: continue   # satélite completo
            ea, eb = [], []
            for c, f in filas.items():
                if c == "_" or f.get("inamhi") is None: continue
                va, vb = f.get(a), f.get(b)
                if filtro_sat and f.get("satelite_corregido"): vb = None
                if va is None or vb is None: continue
                ea.append(abs(va - f["inamhi"])); eb.append(abs(vb - f["inamhi"]))
            if ea:
                por_dia.append((d, sum(ea) / len(ea), sum(eb) / len(eb), len(ea)))
        if not por_dia:
            return {"dias": 0}
        med = lambda xs: round(float(np.median(xs)), 1)
        return {"dias": len(por_dia), "filas": sum(x[3] for x in por_dia),
                "mediana_diaria_mae_mm": {a: med([x[1] for x in por_dia]), b: med([x[2] for x in por_dia])},
                "dias_gana": {a: sum(x[1] < x[2] for x in por_dia), b: sum(x[2] < x[1] for x in por_dia)}}
    solo = []
    for d, filas in dias.items():
        if (filas.get("_") or {}).get("marcos") != 96: continue
        e = [abs(f["pardig"] - f["inamhi"]) for c, f in filas.items()
             if c != "_" and f.get("pardig") is not None and f.get("inamhi") is not None]
        if e: solo.append(sum(e) / len(e))
    return {"criterio": "mediana diaria del error pareado y días ganados; decidir con >= 14 días pareados",
            "pardig_vs_satelite": par("pardig", "satelite", True),
            "pardig_vs_pardig_3x3": par("pardig", "pardig_3x3", False),
            "pardig_todas_las_ciudades": {"dias": len(solo), "mediana_diaria_mae_mm": round(float(np.median(solo)), 1) if solo else None}}


def main():
    ahora = D.datetime.now(D.timezone.utc) - D.timedelta(hours=5)
    hoy = ahora.date()
    pedidos = sys.argv[1:] or [(hoy - D.timedelta(k)).isoformat() for k in (1, 2, 3)]   # completa días a medias
    for d in pedidos:   # revisor: solo fechas AAAA-MM-DD pasadas
        if len(d) != 10 or D.date.fromisoformat(d).isoformat() != d or D.date.fromisoformat(d) >= hoy:
            sys.exit(f"día inválido: {d!r}")
    S = json.load(open(F_SOMBRA, encoding="utf-8")) if os.path.exists(F_SOMBRA) else {}
    S.setdefault("congelado", CONGELADO)
    S["fuente"] = ("PARDIG-NRT © Google LLC (Google DeepMind / Google Research), CC BY 4.0, experimental; "
                   "Inamhi reporte diario; lluvia del día 3D de DataLab Ec (GOES-19)")
    dias = S.setdefault("dias", {})
    C = ciudades()
    for dia in sorted(pedidos):
        fila = dias.get(dia) or {}
        meta = fila.get("_") or {}
        if meta.get("marcos") != 96:
            tot, n = pardig_dia(dia)
            print(f"{dia}: PARDIG {n}/96 cuartos de hora")
            meta["marcos"] = n
            if tot is not None and n == 96:   # la malla solo se guarda con el día completo
                q = np.clip(np.rint(tot * 10), 0, 65535).astype("<u2")
                guardar(os.path.join(D_MALLA, dia + ".json"), {
                    "dia": dia, "fuente": S["fuente"], "licencia": LICENCIA, "unidad": "décimas de mm (uint16 little-endian, base64)",
                    "lat0": round(-90 + 0.1 * I0, 2), "lon0": round(0.1 * J0 - 360, 2), "paso": 0.1,
                    "filas": int(q.shape[0]), "cols": int(q.shape[1]), "b64": base64.b64encode(q.tobytes()).decode()})
            for c, (la, lo) in (C.items() if tot is not None else []):
                p1, p3 = en_punto(tot, la, lo)
                if p1 is not None:
                    f = fila.setdefault(c, {})
                    f["pardig"], f["pardig_3x3"] = (p1, p3) if n == 96 else (None, None)
        if not meta.get("inamhi"):
            try:
                ina = inamhi(dia)
                if ina:
                    for f in fila.values():   # revisor: lo que ya no venga en el reporte nuevo no se queda viejo
                        if isinstance(f, dict): f.pop("inamhi", None); f.pop("inamhi_horas", None)
                for c, v in ina.items():
                    if c in fila or c in C:
                        f = fila.setdefault(c, {})
                        f["inamhi"] = v["mm"] if v["horas"] >= 20 else None
                        f["inamhi_horas"] = v["horas"]
                meta["inamhi"] = bool(ina) and (hoy - D.date.fromisoformat(dia)).days >= 2   # se rehace al día siguiente
            except Exception as e:
                print(f"{dia}: Inamhi falló: {str(e)[:80]}")
        if not meta.get("satelite"):
            r = satelite(dia)
            if r:
                sat, sm = r
                for c, v in sat.items():
                    f = fila.setdefault(c, {})
                    f["satelite"] = v["mm"]; f["satelite_corregido"] = v["corregido"]
                meta["satelite"] = True; meta["satelite_info"] = sm
        fila["_"] = meta
        dias[dia] = fila
    S["resumen"] = resumen(dias)
    S["actualizado"] = ahora.strftime("%Y-%m-%d %H:%M")
    guardar(F_SOMBRA, S)
    print(json.dumps(S["resumen"], ensure_ascii=False))


if __name__ == "__main__":
    main()
