"""Atlas · "medio de propagación" (Luis, 20 nov 2026): ¿por qué tormentas grandes se frenan antes de entrar a Guayaquil?
Días con lluvia fuerte en una vecina (Daule/Nobol, Samborondón, Durán, Milagro) y dos desenlaces en Guayaquil:
  ENTRÓ  = Guayaquil ≥ 10 mm;   SE FRENÓ = Guayaquil < 1 mm.
Se compara el aire de Guayaquil a las 13 h (antes de las tormentas de la tarde y la noche) y la diferencia Guayaquil − vecina:
estabilidad, humedad a media altura, cizalla, viento que arrastra (850–500 hPa), CAPE, agua precipitable y superficie.
Anomalías por mes (climatología de todos los años); IC90 por años; p por remuestreo de años; Benjamini-Hochberg.
Lluvia: CHIRPS (VERDAD=sat → repartido con satélite, 1998+; rnl → repartido con ERA5). Un día = una fila (independientes).
Diagnóstico, no pronóstico: describe el ambiente del mismo día.
Uso: SERIE_DATOS=<rama serie-r> VERDAD=sat python3 scripts/serie_propaga.py --salida f.json
"""
import json, math, os, sys
from datetime import date, timedelta
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serie_g as S   # noqa: E402

VECINAS = ["Daule/Nobol", "Samborondón", "Durán", "Milagro"]
CIUD = ["Guayaquil"] + VECINAS
VARS = ["cape_max", "tcwv", "hr850", "hr700", "hr500", "estab_850_500", "cizalla_850_200", "cizalla_850_500",
        "arrastre_u", "arrastre_v", "arrastre_vel", "div850", "w500", "t2_max", "td2", "deficit_rocio", "v10", "blh_max",
        "sol_man", "msl"]


def cargar():
    chirps = json.load(open(os.path.join(S.RAIZ, "historial", "chirps_sat_diario.json" if S.VERDAD == "sat" else "chirps_diario.json"),
                            encoding="utf-8"))["ciudades"]
    d0, d1 = date(1981, 1, 1), date(2026, 10, 31)
    dias = [d0 + timedelta(n) for n in range((d1 - d0).days + 1)]
    di = {d.isoformat(): i for i, d in enumerate(dias)}
    X = np.full((len(CIUD), len(dias), len(VARS)), np.nan, dtype=np.float32)
    Y = np.full((len(CIUD), len(dias)), np.nan, dtype=np.float32)
    vi = {v: i for i, v in enumerate(VARS)}
    for a, c in enumerate(CIUD):
        for k, v in (chirps.get(c) or {}).items():
            if k in di and v is not None: Y[a, di[k]] = v
    for rel in [f for f in S.archivos() if f.startswith("r/g_")]:
        for k, pts in S.git_json(rel)["dias"].items():
            i = di.get(k)
            if i is None: continue
            for a, c in enumerate(CIUD):
                p = pts.get(c)
                if not p: continue
                for nom in ("cape_max", "tcwv"):
                    if p.get(nom) is not None: X[a, i, vi[nom]] = p[nom]
                g = lambda n: p.get(n + "_d")   # 18 UTC = 13 h
                for nom, val in (("hr850", g("hr850")), ("hr700", g("hr700")), ("hr500", g("hr500")),
                                 ("div850", g("div850")), ("w500", g("w500"))):
                    if val is not None: X[a, i, vi[nom]] = val
                if g("t850") is not None and g("t500") is not None: X[a, i, vi["estab_850_500"]] = g("t850") - g("t500")
                if None not in (g("u850"), g("v850"), g("u200"), g("v200")):
                    X[a, i, vi["cizalla_850_200"]] = math.hypot(g("u200") - g("u850"), g("v200") - g("v850"))
                if None not in (g("u850"), g("v850"), g("u500"), g("v500")):
                    X[a, i, vi["cizalla_850_500"]] = math.hypot(g("u500") - g("u850"), g("v500") - g("v850"))
                    us = [g(f"u{l}") for l in (850, 700, 500)]; vs = [g(f"v{l}") for l in (850, 700, 500)]
                    if None not in us + vs:
                        X[a, i, vi["arrastre_u"]] = sum(us) / 3; X[a, i, vi["arrastre_v"]] = sum(vs) / 3
                        X[a, i, vi["arrastre_vel"]] = math.hypot(sum(us) / 3, sum(vs) / 3)
    lista = S.archivos()
    for a, c in enumerate(CIUD):
        rel = "r/s_" + c.replace("/", "-").replace(" ", "_") + ".json.gz"
        if rel not in lista: continue
        for k, v in S.git_json(rel)["dias"].items():
            i = di.get(k)
            if i is None: continue
            for nom in ("t2_max", "td2", "v10", "blh_max", "sol_man", "msl"):
                if v.get(nom) is not None: X[a, i, vi[nom]] = v[nom]
            if v.get("t2_max") is not None and v.get("td2") is not None: X[a, i, vi["deficit_rocio"]] = v["t2_max"] - v["td2"]
    return dias, X, Y


def anom(X, dias):
    mes = np.array([d.month for d in dias]); Z = np.full_like(X, np.nan)
    for m in range(1, 13):
        s = mes == m
        mu = np.nanmean(X[:, s, :], axis=1, keepdims=True); sd = np.nanstd(X[:, s, :], axis=1, keepdims=True)
        sd[~np.isfinite(sd) | (sd == 0)] = np.nan
        Z[:, s, :] = (X[:, s, :] - mu) / sd
    return Z


def comparar(zg, zdif, entro, freno, anio, rnd, nboot=500):
    """Diferencia de medias (ENTRÓ − SE FRENÓ) en anomalías, con IC90 y p por remuestreo de años."""
    res, ps = {}, []
    for nom, z in [(v, zg[:, j]) for j, v in enumerate(VARS)] + [(v + " (GYE−vecina)", zdif[:, j]) for j, v in enumerate(VARS)]:
        e, f = entro & np.isfinite(z), freno & np.isfinite(z)
        if e.sum() < 15 or f.sum() < 15: continue
        dif = float(z[e].mean() - z[f].mean())
        uy = np.unique(anio[e | f]); idx = {u: np.where(anio == u)[0] for u in uy}; bo = []
        for _ in range(nboot):
            k = np.concatenate([idx[u] for u in rnd.choice(uy, len(uy))])
            ek, fk = k[e[k]], k[f[k]]
            if len(ek) and len(fk): bo.append(z[ek].mean() - z[fk].mean())
        bo = np.array(bo); p = float(min(1, 2 * min((bo <= 0).mean(), (bo >= 0).mean()) + 1 / len(bo)))
        sgn = np.r_[np.ones(e.sum()), np.zeros(f.sum())].astype(bool)
        a = S.auc(np.r_[z[e], z[f]], sgn)
        res[nom] = {"dif_entro_menos_freno": round(dif, 3), "ic90": [round(float(np.percentile(bo, 5)), 3), round(float(np.percentile(bo, 95)), 3)],
                    "p": round(p, 4), "auc": round(max(a, 1 - a), 3), "n_entro": int(e.sum()), "n_freno": int(f.sum())}
        ps.append((nom, p))
    q = S.bh([p for _, p in ps])
    for (nom, _), qq in zip(ps, q): res[nom]["q_bh"] = round(float(qq), 4)
    return dict(sorted(res.items(), key=lambda kv: kv[1]["p"]))


def correr():
    dias, X, Y = cargar()
    Z = anom(X, dias); anio = np.array([d.year for d in dias]); mes = np.array([d.month for d in dias])
    desde = 1998 if S.VERDAD == "sat" else 1981
    rnd = np.random.default_rng(11)
    # vecina fuerte: ≥ 10 mm y ≥ su percentil 90 del mes; se toma la vecina más lluviosa del día
    p90 = np.full(Y.shape, np.nan)
    for m in range(1, 13):
        s = mes == m; p90[:, s] = np.nanpercentile(Y[:, s], 90, axis=1, keepdims=True)
    fuerte = (Y >= np.maximum(p90, 10))
    yv = np.where(np.isfinite(Y[1:]), Y[1:], -1); kmax = yv.argmax(axis=0)
    vec_fuerte = fuerte[1:][kmax, np.arange(len(dias))]
    gye = Y[0]; base = (anio >= desde) & np.isfinite(gye) & vec_fuerte
    entro, freno = base & (gye >= 10), base & (gye < 1)
    zg = Z[0]; zv = Z[1:][kmax, np.arange(len(dias))]; zdif = zg - zv
    out = {"definiciones": {"vecinas": VECINAS, "entro": "Guayaquil ≥ 10 mm", "se_freno": "Guayaquil < 1 mm",
                            "vecina_fuerte": "≥ 10 mm y ≥ su percentil 90 del mes", "hora_aire": "13 h (18 UTC) para niveles; superficie del día",
                            "verdad": S.VERDAD, "desde": desde}, "temporadas": {}}
    for nom, meses in (("todo", range(1, 13)), ("ene-may", range(1, 6)), ("jun-dic", range(6, 13))):
        sm = np.isin(mes, list(meses)); e, f = entro & sm, freno & sm
        T = {"dias_vecina_fuerte": int((base & sm).sum()), "entro": int(e.sum()), "se_freno": int(f.sum()),
             "parcial_1_10mm": int((base & sm & ~entro & ~freno).sum()),
             "vecina_que_llovio_al_frenar": {VECINAS[k]: int(((kmax == k) & f).sum()) for k in range(len(VECINAS))}}
        if e.sum() >= 15 and f.sum() >= 15: T["comparacion"] = comparar(zg, zdif, e, f, anio, rnd)
        out["temporadas"][nom] = T
        top = list((T.get("comparacion") or {}).items())[:6]
        print(f"{nom}: vecina fuerte {T['dias_vecina_fuerte']} días; entró {T['entro']}, se frenó {T['se_freno']}", flush=True)
        for k, x in top: print(f"   {k:32s} dif {x['dif_entro_menos_freno']:+.2f} IC90 {x['ic90']} q {x['q_bh']} AUC {x['auc']}", flush=True)
    return out


if __name__ == "__main__":
    sal = sys.argv[sys.argv.index("--salida") + 1] if "--salida" in sys.argv else None
    r = correr()
    if sal: json.dump(r, open(sal, "w"), ensure_ascii=False, indent=1)
