"""DataLab Ec · cuadros del satélite y datos del video diario de tormentas (Luis, 15 nov).
Día calendario de AYER (Ecuador): imágenes GOES-19 banda 13 de 06:00 a 23:50 recortadas a la Costa, con los límites de
provincias, y las tormentas del día con su pista (rama satelite, tormentas_estado.json → "ayer").
Uso: python3 scripts/videos/cuadros.py <carpeta del proyecto Remotion> [AAAA-MM-DD]"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import satelite_ahora as S

PRO = sys.argv[1]
DIA = sys.argv[2] if len(sys.argv) > 2 else ((datetime.now(timezone.utc) - timedelta(hours=5)).date() - timedelta(days=1)).isoformat()
RAW = "https://raw.githubusercontent.com/luiscampozano/simulador-mazar/satelite/"
O, E, N, SS = -82.0, -77.0, 1.6, -4.2
W = 1080; ESC = W / (E - O); H = int(round((N - SS) * ESC))
X = lambda lo: (lo - O) * ESC; Y = lambda la: (N - la) * ESC


def color(k):
    if k >= 290: return (8, 13, 18)
    if k > 245: g = int(20 + (290 - k) / 45 * 90); return (g, g + 6, g + 12)
    st = [(245, (70, 120, 170)), (235, (60, 170, 200)), (225, (80, 200, 110)), (215, (245, 215, 60)), (205, (255, 140, 40)), (195, (240, 50, 50)), (185, (200, 60, 255))]
    for (k1, c1), (k2, c2) in zip(st, st[1:]):
        if k >= k2:
            f = (k1 - k) / (k1 - k2); return tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))
    return st[-1][1]


def main():
    E_ = requests.get(RAW + "tormentas_estado.json", timeout=60).json().get("ayer") or {}
    if E_.get("dia") != DIA:
        raise SystemExit(f"las tormentas de {DIA} no están (ayer guardado: {E_.get('dia')})")
    G = (requests.get(RAW + "tormentas_galapagos_estado.json", timeout=60).json().get("ayer") or {})
    R = requests.get("https://datalabecuador.com/3d/d/ecuador.json", timeout=120).json()
    try:
        A = requests.get("https://datalabecuador.com/3d/d/acumulada.json", timeout=120).json()
        A = A if A.get("dia") == DIA else None
    except Exception:
        A = None
    lut = np.array([color(i + 150) for i in range(255)] + [(8, 13, 18)], dtype=np.uint8)
    j0, j1 = int(round((O + 82) / 0.05)), int(round((E + 82) / 0.05)); i0, i1 = int(round((2 - N) / 0.05)), int(round((2 - SS) / 0.05))
    ini = datetime.fromisoformat(DIA).replace(hour=11, tzinfo=timezone.utc)   # 06:00 Ecuador
    ks = []
    for h in range(18):
        ks += [k for k in S.listar("ABI-L2-CMIPF", ini + timedelta(hours=h)) if "M6C13" in k]

    def una(k):
        for _ in range(3):
            try:
                T, t, _ = S.escena(k)
                return t, np.where(np.isfinite(T), np.clip(np.rint(T - 150), 0, 254), 255).astype(np.uint8)
            except Exception:
                time.sleep(2)
    with ThreadPoolExecutor(6) as ex:
        r = sorted([x for x in ex.map(una, ks) if x], key=lambda x: x[0])
    os.makedirs(os.path.join(PRO, "public", "cuadros"), exist_ok=True)
    fr = []
    for t, a in r:
        hl = t - timedelta(hours=5)
        im = Image.fromarray(lut[a[i0:i1, j0:j1]]).resize((W, H), Image.BICUBIC)
        d = ImageDraw.Draw(im)
        for ring in R["limites"]:
            d.line([(X(lo), Y(la)) for lo, la in ring], fill=(170, 190, 205), width=2)
        n = hl.strftime("%H%M"); im.save(os.path.join(PRO, "public", "cuadros", n + ".jpg"), quality=86); fr.append(hl.strftime("%H:%M"))
    T = E_.get("tormentas") or []
    tor = [{"id": s["id"], "fuerte": s.get("nivel_max") == "tormenta fuerte",
            "p": [[round(X(lo), 1), round(Y(la), 1), h] for la, lo, h in s.get("pista") or [] if O < lo < E and SS < la < N]} for s in T]
    grande = max(T, key=lambda s: s.get("area_max_km2") or 0) if T else None
    notas = []
    for s in sorted(T, key=lambda s: -(s.get("area_max_km2") or 0))[:4]:   # la más grande primero: gana si dos nacen a la misma hora
        if s.get("ya_estaba"): continue
        notas.append([s["nace"], f"Nace la tormenta #{s['id']} {s.get('nace_donde', '')}".strip()])
    if grande:
        txt = f"La #{grande['id']} fue la más grande del día: {grande['area_max_km2']:,} km²".replace(",", ".") + (f" y {grande['rayos_max_15min']} rayos en 15 min" if grande.get("rayos_max_15min") else "")
        hora_fin = max(fr) if fr else "23:50"
        notas.append([min(hora_fin, max((p[2] for p in grande.get("pista") or [["", "", "12:00"]]), default="12:00")), txt])
    vistas = {}
    for n_ in notas: vistas.setdefault(n_[0], n_)
    notas = sorted(vistas.values())
    ciudades = sorted({c for s in T for c in s.get("encima") or []})
    ciu = {"Guayaquil": (-2.19, -79.89), "Quevedo": (-1.03, -79.46), "Santo Domingo": (-0.25, -79.17), "Babahoyo": (-1.80, -79.53), "Milagro": (-2.13, -79.59),
           "Daule": (-1.87, -79.98), "Esmeraldas": (0.96, -79.65), "Manta": (-0.95, -80.73), "Santa Elena": (-2.23, -80.86), "Machala": (-3.26, -79.96)}
    out = {"dia": DIA, "W": W, "H": H, "cuadros": fr, "tormentas": tor, "grande": grande and grande["id"], "notas": notas,
           "ciudades": {k: [round(X(lo)), round(Y(la))] for k, (la, lo) in ciu.items()},
           "resumen": {"continente": len(T), "fuertes": sum(1 for s in T if s.get("nivel_max") == "tormenta fuerte"),
                       "galapagos": len(G.get("tormentas") or []) if G.get("dia") == DIA else None,
                       "ciudades": ciudades, "desde": E_.get("desde", "00:00"),
                       "nucleos": [[x["lugar"], x["mm"]] for x in (A or {}).get("nucleos", [])[:3]]}}
    json.dump(out, open(os.path.join(PRO, "src", "datos.json"), "w"), ensure_ascii=False)
    print(DIA, len(fr), "cuadros,", len(T), "tormentas; notas:", notas)


if __name__ == "__main__":
    main()
