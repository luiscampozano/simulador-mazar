"""Serie R · análisis por grupos G1 / G2 / G3 (1981–2026) contra la lluvia diaria CHIRPS de cada ciudad.

Datos: rama serie-r (r/g_*: rejilla por punto; r/s_*: series de superficie por punto; r/mjo.txt) y historial/chirps_diario.json.
Todo en ANOMALÍAS: cada variable menos su promedio de (ciudad, mes) en los años de entrenamiento, dividido por su desvío;
así el ciclo anual no se cuela como "importancia". La lluvia: "día fuerte" = ≥ percentil 90 de esa ciudad y mes (y ≥ 1 mm).
Validación: se aprende con 1981–2010 y se mide con 2011–2026 (fuera de muestra). Intervalos con bootstrap por AÑOS (las
ciudades del mismo día y los días del mismo año no son independientes). Comparaciones múltiples: Benjamini-Hochberg.
Ojo: ERA5 es reanálisis (lo que pasó ese día), no pronóstico: dice qué ingredientes acompañan a la lluvia, no cuánto se
puede anticipar. Lo que salga se congela y se prueba en sombra.
Uso: SERIE_DATOS=<checkout de serie-r> python3 scripts/serie_g.py [--salida r/analisis_g.json]"""
import gzip, json, math, os, subprocess, sys
from datetime import date, timedelta

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.environ.get("SERIE_DATOS") or os.path.join(AQUI, "..", "_serie_r")
RAIZ = os.path.join(AQUI, "..")

REGIONES = {
    "Costa": ["Guayaquil", "Durán", "Samborondón", "Daule/Nobol", "Esmeraldas", "Santo Domingo", "Quevedo", "Babahoyo", "Portoviejo",
              "Manta", "Santa Elena", "Machala", "Milagro", "Bahía de Caráquez", "Piñas"],
    "Sierra": ["Quito", "Ibarra", "Tulcán", "Ambato", "Latacunga", "Riobamba", "Guaranda", "Cuenca", "Paute/Mazar", "Gualaceo", "Azogues", "Loja"],
    "Amazonía": ["Macas", "Puyo", "Tena", "El Coca", "Nueva Loja", "Coca Codo/El Chaco", "Zamora"],
    "Galápagos": ["Puerto Ayora", "Puerto Baquerizo Moreno", "Puerto Villamil"],
}
# Grupos (nombres neutros). Variable: (origen, punto, clave/función). "c" = la propia ciudad.
G = {
    "G1": ["tcwv", "cape_max", "cin_min", "hr850", "hr700", "hr500", "suelo_ayer", "lcc", "td2", "t2_max", "sol_man", "lhf_ayer",
           "sst_golfo", "sst_golfo_menos_humboldt", "sst_galapagos", "tcwv_choco", "tcwv_amazonia", "tcwv_galapagos"],
    "G3": ["w500_t", "w500_d", "w700_t", "w850_t", "conv850_t", "blh_max", "zc81_max", "zc81_lat", "u850_81o", "u850_choco",
           "v850_choco", "u850_golfo"],
    "G2": ["div200_t", "div200_d", "viento200", "u200", "u200_galapagos", "u200_amazonia", "mjo_amp", "mjo_rmm1", "mjo_rmm2",
           "msl_anticiclon", "grad_anticiclon"],
}
# Segunda vuelta (verificador, 20 nov): VERDAD=sat usa CHIRPS repartido con satélite (IMERG, 1998+; el "rnl" reparte con
# ERA5 y es circular); MODO=anterior usa todas las variables del día anterior (lo que se sabe antes: anticipar, no explicar).
VERDAD = os.environ.get("VERDAD", "rnl")
MODO = os.environ.get("MODO", "mismo")
ENTRENA, PRUEBA = ((1998, 2012), (2013, 2026)) if VERDAD == "sat" else ((1981, 2010), (2011, 2026))
# Fuera: cin_min (le falta a la mitad de los días y no al azar: los días con dato llueven 2–3 veces más). Con el MISMO día
# también la radiación de la mañana, la capa de mezcla y las nubes bajas: la lluvia y sus nubes las bajan (consecuencia).
EXCLUIR = {"cin_min"} | ({"sol_man", "blh_max", "lcc"} if MODO == "mismo" else set())
G = {g: [v for v in vs if v not in EXCLUIR] for g, vs in G.items()}


def git_json(rel):
    try:
        b = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=DATOS, capture_output=True, check=True).stdout
    except Exception:
        b = open(os.path.join(DATOS, rel), "rb").read()
    return json.loads(gzip.decompress(b) if rel.endswith(".gz") else b)


def archivos():
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "r/"], cwd=DATOS, capture_output=True, text=True).stdout.split()
    return out or sorted("r/" + f for f in os.listdir(os.path.join(DATOS, "r")))


def cargar():
    chirps = json.load(open(os.path.join(RAIZ, "historial", "chirps_sat_diario.json" if VERDAD == "sat" else "chirps_diario.json"),
                            encoding="utf-8"))["ciudades"]
    ciudades = [c for v in REGIONES.values() for c in v if c in chirps]
    d0, d1 = date(1981, 1, 1), date(2026, 10, 31)
    dias = [d0 + timedelta(n) for n in range((d1 - d0).days + 1)]
    di = {d.isoformat(): i for i, d in enumerate(dias)}
    nombres = [v for g in G.values() for v in g]
    vi = {v: i for i, v in enumerate(nombres)}
    X = np.full((len(ciudades), len(dias), len(nombres)), np.nan, dtype=np.float32)
    global SUELO, LHF
    SUELO = np.full((len(ciudades), len(dias)), np.nan, dtype=np.float32); LHF = SUELO.copy()
    Y = np.full((len(ciudades), len(dias)), np.nan, dtype=np.float32)
    for a, c in enumerate(ciudades):
        for k, v in chirps[c].items():
            if k in di and v is not None: Y[a, di[k]] = v
    # rejilla por punto (s: superficie; p: niveles), puntos x_* comunes a todas las ciudades
    comun = {}   # (var, i_dia) -> valor
    lista = archivos()
    for rel in [f for f in lista if f.startswith("r/g_")]:
        d = git_json(rel)["dias"]
        for k, pts in d.items():
            i = di.get(k)
            if i is None: continue
            xc, xa, xg, xo, xg2 = (pts.get(n) or {} for n in ("x_choco", "x_amazonia", "x_galapagos", "x_81o", "x_golfo"))
            z = pts.get("x_z81") or {}
            for nom, val in (("tcwv_choco", xc.get("tcwv")), ("tcwv_amazonia", xa.get("tcwv")), ("tcwv_galapagos", xg.get("tcwv")),
                             ("u850_81o", _m(xo, "u850")), ("u850_choco", _m(xc, "u850")), ("v850_choco", _m(xc, "v850")),
                             ("u850_golfo", _m(xg2, "u850")), ("u200_galapagos", _m(xg, "u200")), ("u200_amazonia", _m(xa, "u200"))):
                if val is not None: comun[(nom, i)] = val
            if z:
                sur = {float(kk[1:]): vv for kk, vv in z.items() if -4.0 <= float(kk[1:]) <= -0.5 and vv is not None}
                if sur:
                    la = max(sur, key=sur.get); comun[("zc81_max", i)] = sur[la]; comun[("zc81_lat", i)] = la
            for a, c in enumerate(ciudades):
                p = pts.get(c)
                if not p: continue
                for k2, v2 in p.items():
                    if k2 in vi and v2 is not None: X[a, i, vi[k2]] = v2
                if p.get("suelo") is not None: SUELO[a, i] = p["suelo"]
                for nom, val in (("hr850", _m(p, "hr850")), ("hr700", _m(p, "hr700")), ("hr500", _m(p, "hr500")),
                                 ("u200", _m(p, "u200"))):
                    if val is not None: X[a, i, vi[nom]] = val
                for k2 in ("w500_t", "w500_d", "w700_t", "w850_t", "div200_t", "div200_d"):
                    if p.get(k2) is not None: X[a, i, vi[k2]] = p[k2]
                if p.get("div850_t") is not None: X[a, i, vi["conv850_t"]] = -p["div850_t"]
                if p.get("u200_t") is not None and p.get("v200_t") is not None:
                    X[a, i, vi["viento200"]] = math.hypot(p["u200_t"], p["v200_t"])
    # series de superficie por punto
    def serie(pto):
        rel = "r/s_" + pto.replace("/", "-").replace(" ", "_") + ".json.gz"
        return git_json(rel)["dias"] if rel in lista else {}
    S = {p: serie(p) for p in ("x_golfo", "x_humboldt", "x_galapagos", "x_anticiclon")}
    for k, i in di.items():
        g_, h_, ga, an = (S[p].get(k) or {} for p in ("x_golfo", "x_humboldt", "x_galapagos", "x_anticiclon"))
        if g_.get("sst") is not None:
            comun[("sst_golfo", i)] = g_["sst"]
            if h_.get("sst") is not None: comun[("sst_golfo_menos_humboldt", i)] = g_["sst"] - h_["sst"]
        if ga.get("sst") is not None: comun[("sst_galapagos", i)] = ga["sst"]
        if an.get("msl") is not None: comun[("msl_anticiclon", i)] = an["msl"]
    for a, c in enumerate(ciudades):
        sc = serie(c)
        for k, v in sc.items():
            i = di.get(k)
            if i is None: continue
            for k2 in ("td2", "t2_max", "sol_man", "blh_max"):
                if k2 in vi and v.get(k2) is not None: X[a, i, vi[k2]] = v[k2]
            if v.get("lhf") is not None: LHF[a, i] = v["lhf"]
            if v.get("msl") is not None and ("msl_anticiclon", i) in comun:
                X[a, i, vi["grad_anticiclon"]] = comun[("msl_anticiclon", i)] - v["msl"]
    # MJO
    try:
        for ln in subprocess.run(["git", "show", "HEAD:r/mjo.txt"], cwd=DATOS, capture_output=True, text=True).stdout.splitlines()[2:]:
            p = ln.split()
            if len(p) < 7: continue
            k = f"{int(p[0]):04d}-{int(p[1]):02d}-{int(p[2]):02d}"
            if k in di and float(p[6]) < 100:
                comun[("mjo_amp", di[k])] = float(p[6]); comun[("mjo_rmm1", di[k])] = float(p[3]); comun[("mjo_rmm2", di[k])] = float(p[4])
    except Exception: pass
    for (nom, i), val in comun.items(): X[:, i, vi[nom]] = val
    # Lo que la lluvia del mismo día moja o enfría (suelo, calor latente) se usa del DÍA ANTERIOR: si no, la "importancia"
    # sería la propia lluvia (circularidad). Revisión 20 nov.
    X[:, 1:, vi["suelo_ayer"]] = SUELO[:, :-1]; X[:, 0, vi["suelo_ayer"]] = np.nan
    X[:, 1:, vi["lhf_ayer"]] = LHF[:, :-1]; X[:, 0, vi["lhf_ayer"]] = np.nan
    return ciudades, dias, nombres, X, Y


def _m(p, base):
    a, b = p.get(base + "_d"), p.get(base + "_t")
    return a if b is None else (b if a is None else (a + b) / 2)


def anomalias(X, Y, dias):
    """Anomalía estandarizada por (ciudad, mes) con la climatología de los años de entrenamiento; 'día fuerte' por (ciudad, mes)."""
    mes = np.array([d.month for d in dias]); anio = np.array([d.year for d in dias])
    tr = (anio >= ENTRENA[0]) & (anio <= ENTRENA[1])
    Z = np.full_like(X, np.nan); F = np.zeros(Y.shape, dtype=bool); V = np.isfinite(Y)
    for m in range(1, 13):
        sel = mes == m; st = sel & tr
        mu = np.nanmean(X[:, st, :], axis=1, keepdims=True); sd = np.nanstd(X[:, st, :], axis=1, keepdims=True)
        sd[~np.isfinite(sd) | (sd == 0)] = np.nan
        Z[:, sel, :] = (X[:, sel, :] - mu) / sd
        p90 = np.nanpercentile(Y[:, st], 90, axis=1, keepdims=True)
        F[:, sel] = (Y[:, sel] >= np.maximum(p90, 1.0))
    return Z, F, V, anio, mes


def auc(s, y):
    ok = np.isfinite(s); s, y = s[ok], y[ok]
    n1, n0 = y.sum(), (~y).sum()
    if n1 == 0 or n0 == 0: return float("nan")
    r = np.argsort(np.argsort(s)) + 1.0
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def logit(Xm, y, l2=1.0, it=25):
    """Logística con regularización L2 (IRLS). Xm sin NaN, con columna de 1."""
    w = np.zeros(Xm.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-np.clip(Xm @ w, -30, 30)))
        g = Xm.T @ (p - y) + l2 * np.r_[0, w[1:]]
        H = (Xm * (p * (1 - p))[:, None]).T @ Xm + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
        try: w -= np.linalg.solve(H, g)
        except np.linalg.LinAlgError: break
    return w


def bh(ps):
    ps = np.asarray(ps, float); n = np.isfinite(ps).sum(); o = np.argsort(ps); q = np.full_like(ps, np.nan); prev = 1.0
    for rank, i in reversed(list(enumerate(o, 1))):
        if not np.isfinite(ps[i]): continue
        prev = min(prev, ps[i] * n / rank); q[i] = prev
    return q


def _resumen(mm, fuerte, m):
    n = int(m.sum())
    if n < 30: return None
    x = mm[m]
    return {"n": n, "mm_medio": round(float(np.nanmean(x)), 2), "llueve_1mm": round(float((x >= 1).mean()), 3),
            "moderada_10mm": round(float((x >= 10).mean()), 3), "dia_fuerte": round(float(fuerte[m].mean()), 3)}


def dosis(pun, mm, fuerte, tr, te, yr, rnd, tabla3d=False):
    """Dosis-respuesta (Luis, 20 nov: "una rama igual es combustible"): cuánta lluvia da cada vértice según su nivel.
    Nivel = percentil del puntaje del grupo respecto a los años de entrenamiento; todo se mide en los años de prueba.
    - curva: por decil del vértice, mm medio y frecuencia de lluvia (≥1 mm), moderada (≥10 mm) y día fuerte; también con los
      otros dos vértices altos (su promedio en el tercio alto) y bajos (tercio bajo).
    - piso: el decil más bajo (el vértice casi "apagado"): cuánta lluvia queda.
    - forma: ¿se suman, se multiplican o manda el más bajo? Correlación de rangos con los mm y AUC del día fuerte, fuera de
      muestra, con IC90 por años de la diferencia frente a la suma.
    - tabla 5×5×5 (solo temporada completa): mm medio por quintil de cada vértice."""
    P = {}
    for g, s in pun.items():
        ref = np.sort(s[tr & np.isfinite(s)])
        p = np.searchsorted(ref, s) / len(ref); p[~np.isfinite(s)] = np.nan; P[g] = np.clip(p, 0, 0.9999)
    gs = ("G1", "G2", "G3"); M = np.c_[[P[g] for g in gs]].T
    ok = te & np.all(np.isfinite(M), axis=1) & np.isfinite(mm)
    out = {"curva": {}, "piso": {}}
    for j, g in enumerate(gs):
        dec = np.floor(M[:, j] * 10).astype(int)
        otros = np.nanmean(np.delete(M, j, axis=1), axis=1)
        cur = {"todos": [], "otros_altos": [], "otros_bajos": []}
        for k in range(10):
            mk = ok & (dec == k)
            cur["todos"].append(_resumen(mm, fuerte, mk))
            cur["otros_altos"].append(_resumen(mm, fuerte, mk & (otros >= 2 / 3)))
            cur["otros_bajos"].append(_resumen(mm, fuerte, mk & (otros <= 1 / 3)))
        out["curva"][g] = cur
        out["piso"][g] = {"decil_mas_bajo": cur["todos"][0], "decil_mas_bajo_con_otros_altos": cur["otros_altos"][0],
                          "decil_mas_alto": cur["todos"][9]}
    out["base_prueba"] = _resumen(mm, fuerte, ok)
    # forma de la combinación
    idx = {"suma": M.mean(axis=1), "producto": M.prod(axis=1), "minimo": M.min(axis=1), "maximo": M.max(axis=1)}
    from scipy.stats import spearmanr
    def medir(m):
        r = {}
        for k, v in idx.items():
            r[k] = (float(spearmanr(v[m], mm[m]).statistic), auc(v[m], fuerte[m]))
        return r
    base = medir(ok)
    uy = np.unique(yr[ok]); bo = {k: [] for k in idx}
    for _ in range(100):
        ss = rnd.choice(uy, len(uy)); m = ok & np.isin(yr, ss)
        r = medir(m)
        for k in idx: bo[k].append((r[k][0] - r["suma"][0], r[k][1] - r["suma"][1]))
    out["forma"] = {k: {"rho_mm": round(base[k][0], 3), "auc_fuerte": round(base[k][1], 3),
                        **({"dif_rho_vs_suma_ic90": [round(float(np.percentile([b[0] for b in bo[k]], q)), 3) for q in (5, 95)],
                            "dif_auc_vs_suma_ic90": [round(float(np.percentile([b[1] for b in bo[k]], q)), 3) for q in (5, 95)]}
                           if k != "suma" else {})} for k in idx}
    if tabla3d:
        Q = np.floor(M * 5).astype(int); t = {}
        for a in range(5):
            for b in range(5):
                for c in range(5):
                    r = _resumen(mm, fuerte, ok & (Q[:, 0] == a) & (Q[:, 1] == b) & (Q[:, 2] == c))
                    if r: t[f"G1q{a + 1} G2q{b + 1} G3q{c + 1}"] = r
        out["tabla_5x5x5"] = t
    return out


def analizar(ciudades, dias, nombres, X, Y, rnd=np.random.default_rng(7), nboot=100):
    Z, F, V, anio, mes = anomalias(X, Y, dias)
    vi = {v: i for i, v in enumerate(nombres)}
    anios = np.arange(1981, 2027)
    out = {"definiciones": {"grupos": G, "regiones": REGIONES, "entrena": ENTRENA, "prueba": PRUEBA,
                            "dia_fuerte": "≥ percentil 90 de la ciudad y el mes (1981–2010) y ≥ 1 mm"}, "regiones": {}}
    for reg, lista in REGIONES.items():
        ci = [ciudades.index(c) for c in lista if c in ciudades]
        for temporada, meses in (("todo", range(1, 13)), ("ene-may", range(1, 6)), ("jun-dic", range(6, 13))):
            sm = np.isin(mes, list(meses))
            filas = [(a, i) for a in ci for i in np.where(sm)[0]]
            A = np.array([a for a, _ in filas]); I = np.array([i for _, i in filas])
            y = F[A, I]; ok = V[A, I]; Zr = Z[A, I, :]; yr = anio[I]
            tr = ok & (yr <= ENTRENA[1]); te = ok & (yr >= PRUEBA[0])
            if y[ok].mean() < 0.02:   # Galápagos de junio a diciembre: casi nunca hay día fuerte (garúa); no alcanza
                out["regiones"].setdefault(reg, {})[temporada] = {"filas": int(ok.sum()), "tasa_dia_fuerte": round(float(y[ok].mean()), 3),
                                                                   "nota": "muy pocos días fuertes: no se analiza"}
                continue
            R = {"filas": int(ok.sum()), "dias": int(len(set(I[ok]))), "tasa_dia_fuerte": round(float(y[ok].mean()), 3), "variables": {}, "grupos": {}}
            # 1) cada variable: AUC fuera de muestra (signo aprendido en entrenamiento), IC90 por años, p por permutación de años
            ps = []
            for v in nombres:
                j = vi[v]; s = Zr[:, j]
                a_tr = auc(s[tr], y[tr])
                if not np.isfinite(a_tr): ps.append(np.nan); continue
                sg = 1 if a_tr >= 0.5 else -1
                a_te = auc(sg * s[te], y[te])
                yt = yr[te]; ss = sg * s[te]; yy = y[te]; bo = []
                uy = np.unique(yt); idx = {u: np.where(yt == u)[0] for u in uy}
                for _ in range(nboot):
                    k = np.concatenate([idx[u] for u in rnd.choice(uy, len(uy))]); bo.append(auc(ss[k], yy[k]))
                bo = np.array([b for b in bo if np.isfinite(b)])
                # p: proporción de remuestreos con AUC ≤ 0,5 (unilateral, por años)
                p = float(((bo <= 0.5).sum() + 1) / (len(bo) + 1))
                ps.append(p)
                R["variables"][v] = {"grupo": next(g for g, l in G.items() if v in l), "signo": sg, "auc_entrena": round(max(a_tr, 1 - a_tr), 3),
                                     "auc_prueba": round(a_te, 3), "ic90": [round(float(np.percentile(bo, 5)), 3), round(float(np.percentile(bo, 95)), 3)],
                                     "p": round(p, 4)}
            q = bh(ps)
            for v, qq in zip(nombres, q):
                if v in R["variables"]: R["variables"][v]["q_bh"] = None if not np.isfinite(qq) else round(float(qq), 4)
            # 2) cada grupo: logística con sus variables (entrena 1981–2010) → AUC 2011–2026; quitar-una para ver qué pesa
            def ajuste(cols, devolver=False):
                Xm = Zr[:, cols]; okc = np.all(np.isfinite(Xm), axis=1)
                a, b = tr & okc, te & okc
                if a.sum() < 500 or b.sum() < 200: return None
                w = logit(np.c_[np.ones(a.sum()), Xm[a]], y[a].astype(float))
                s = np.c_[np.ones(b.sum()), Xm[b]] @ w
                r = auc(s, y[b])
                return (r, w, b, s) if devolver else r
            for g, vs in G.items():
                cols = [vi[v] for v in vs if v in R["variables"] and R["variables"][v]["auc_entrena"] >= 0.52]
                if not cols: continue
                res = ajuste(cols, True)
                if not res: continue
                base, w, b, s = res
                quita = {}
                for c in cols:
                    r2 = ajuste([x for x in cols if x != c])
                    if r2 is not None: quita[nombres[c]] = round(base - r2, 4)
                R["grupos"][g] = {"auc_prueba": round(base, 3), "variables_usadas": [nombres[c] for c in cols],
                                  "peso_al_quitar": dict(sorted(quita.items(), key=lambda kv: -kv[1])),
                                  "coef": {nombres[c]: round(float(x), 3) for c, x in zip(cols, w[1:])}}
            # 3) los tres juntos y su interacción: puntaje de cada grupo en tercios → tasa de días fuertes por combinación
            pun = {}
            for g in G:
                if g not in R["grupos"]: continue
                cols = [vi[v] for v in R["grupos"][g]["variables_usadas"]]; Xm = Zr[:, cols]; okc = np.all(np.isfinite(Xm), axis=1)
                a = tr & okc
                w = logit(np.c_[np.ones(a.sum()), Xm[a]], y[a].astype(float))
                sc = np.full(len(y), np.nan); sc[okc] = np.c_[np.ones(okc.sum()), Xm[okc]] @ w
                pun[g] = sc
            if len(pun) == 3:
                todo = np.all([np.isfinite(pun[g]) for g in pun], axis=0)
                cols3 = np.c_[[pun[g] for g in ("G1", "G2", "G3")]].T
                a, b = tr & todo, te & todo
                w3 = logit(np.c_[np.ones(a.sum()), cols3[a]], y[a].astype(float))
                inter = np.c_[cols3, cols3[:, 0] * cols3[:, 1], cols3[:, 0] * cols3[:, 2], cols3[:, 1] * cols3[:, 2], cols3.prod(axis=1)]
                w4 = logit(np.c_[np.ones(a.sum()), inter[a]], y[a].astype(float))
                R["juntos"] = {"auc_suma": round(auc(np.c_[np.ones(b.sum()), cols3[b]] @ w3, y[b]), 3),
                               "auc_con_interaccion": round(auc(np.c_[np.ones(b.sum()), inter[b]] @ w4, y[b]), 3),
                               "coef_suma": dict(zip(("G1", "G2", "G3"), [round(float(x), 3) for x in w3[1:]]))}
                cortes = {g: np.nanpercentile(pun[g][a], [33.3, 66.7]) for g in pun}
                nivel = {g: np.digitize(pun[g], cortes[g]) for g in pun}   # 0 bajo, 1 medio, 2 alto
                tabla = {}
                for k1 in (0, 2):
                    for k2 in (0, 2):
                        for k3 in (0, 2):
                            m = te & todo & (nivel["G1"] == k1) & (nivel["G2"] == k2) & (nivel["G3"] == k3)
                            if m.sum() >= 50:
                                tabla[f"G1{'+' if k1 else '-'} G2{'+' if k2 else '-'} G3{'+' if k3 else '-'}"] = {"tasa": round(float(y[m].mean()), 3), "n": int(m.sum())}
                R["juntos"]["tercios_prueba"] = tabla
            # 4) ¿hay "veto"? Para cada variable fuerte de un grupo: entre días con el RESTO del grupo parecido (mismo decil del
            #    puntaje de las otras), cuánto baja la tasa con esta en su tercio bajo frente al alto; y qué parte de los días
            #    fuertes ocurrió con esta en su tercio bajo (si fuera condición necesaria, ~0 %; si no importa, ~33 %).
            veto = {}
            for g, vs in G.items():
                usadas = [v for v in vs if v in R["variables"] and R["variables"][v]["auc_entrena"] >= 0.55]
                for v in usadas:
                    otras = [vi[x] for x in usadas if x != v]
                    xv = R["variables"][v]["signo"] * Zr[:, vi[v]]
                    okc = ok & np.isfinite(xv) & (np.all(np.isfinite(Zr[:, otras]), axis=1) if otras else True)
                    if otras:
                        a = okc & tr
                        w = logit(np.c_[np.ones(a.sum()), Zr[a][:, otras]], y[a].astype(float))
                        sc = np.full(len(y), np.nan); sc[okc] = np.c_[np.ones(okc.sum()), Zr[okc][:, otras]] @ w
                        dec = np.digitize(sc, np.nanpercentile(sc[a], np.arange(10, 100, 10)))
                    else: dec = np.zeros(len(y), int)
                    lo_c, hi_c = np.nanpercentile(xv[okc & tr], [33.3, 66.7])
                    def baja(m):
                        num = den = 0.0
                        for b in range(10):
                            mb = m & (dec == b); l, h = mb & (xv < lo_c), mb & (xv > hi_c)
                            if l.sum() >= 30 and h.sum() >= 30 and y[h].mean() > 0:
                                peso = l.sum() + h.sum(); num += peso * y[l].mean(); den += peso * y[h].mean()
                        return 1 - num / den if den > 0 else None
                    base = baja(okc & te)
                    if base is None: continue
                    uy = np.unique(yr[okc & te]); bo = []
                    for _ in range(100):
                        ss = rnd.choice(uy, len(uy)); m = okc & te & np.isin(yr, ss)
                        # remuestreo por años (aproximado: un año elegido dos veces cuenta una vez)
                        x = baja(m)
                        if x is not None: bo.append(x)
                    fuertes = okc & te & y
                    veto[v] = {"grupo": g, "baja_con_resto_parecido": round(base, 3),
                               "ic90": [round(float(np.percentile(bo, 5)), 3), round(float(np.percentile(bo, 95)), 3)] if bo else None,
                               "dias_fuertes_con_esta_baja": round(float((xv[fuertes] < lo_c).mean()), 3) if fuertes.sum() else None,
                               "n_fuertes": int(fuertes.sum())}
            # el triángulo: qué parte de los días fuertes tuvo algún grupo en su tercio bajo, y la tasa en esos días
            if "juntos" in R and len(pun) == 3:
                m = te & todo
                algun_bajo = (nivel["G1"] == 0) | (nivel["G2"] == 0) | (nivel["G3"] == 0)
                R["juntos"]["dias_fuertes_con_algun_grupo_bajo"] = round(float(algun_bajo[m & y].mean()), 3)
                R["juntos"]["esperado_si_no_importara"] = round(1 - (2 / 3) ** 3, 3)
                R["juntos"]["tasa_algun_grupo_bajo"] = round(float(y[m & algun_bajo].mean()), 3)
                R["juntos"]["tasa_ninguno_bajo"] = round(float(y[m & ~algun_bajo].mean()), 3)
                for g in ("G1", "G2", "G3"):
                    R["juntos"][f"dias_fuertes_con_{g}_bajo"] = round(float((nivel[g] == 0)[m & y].mean()), 3)
            R["veto"] = dict(sorted(veto.items(), key=lambda kv: -(kv[1]["baja_con_resto_parecido"] or 0)))
            if "juntos" in R and len(pun) == 3:
                R["dosis"] = dosis(pun, Y[A, I], y, tr & todo, te & todo, yr, rnd, tabla3d=(temporada == "todo"))
            out["regiones"].setdefault(reg, {})[temporada] = R
            print(f"{reg} {temporada}: {R['filas']} filas; grupos " + ", ".join(f"{g} {x['auc_prueba']}" for g, x in R["grupos"].items())
                  + (f"; juntos {R['juntos']['auc_suma']} / con interacción {R['juntos']['auc_con_interaccion']}" if "juntos" in R else ""), flush=True)
    return out


if __name__ == "__main__":
    sal = sys.argv[sys.argv.index("--salida") + 1] if "--salida" in sys.argv else None
    c, d, n, X, Y = cargar()
    if MODO == "anterior":   # todo del día anterior (lo que ya se sabe la víspera)
        X[:, 1:, :] = X[:, :-1, :]; X[:, 0, :] = np.nan
    print(f"VERDAD={VERDAD} MODO={MODO} entrena {ENTRENA} prueba {PRUEBA} fuera {sorted(EXCLUIR)}", flush=True)
    print(f"cargado: {len(c)} ciudades × {len(d)} días × {len(n)} variables; con dato {np.isfinite(X).mean():.0%}", flush=True)
    for v in n:
        f = np.isfinite(X[:, :, n.index(v)]).mean()
        if f < 0.5: print(f"  ojo: {v} con dato en {f:.0%}", flush=True)
    r = analizar(c, d, n, X, Y)
    if sal:
        os.makedirs(os.path.dirname(sal) or ".", exist_ok=True)
        json.dump(r, open(sal, "w"), ensure_ascii=False, indent=1)
