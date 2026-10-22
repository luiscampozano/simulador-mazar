"""Robot del simulador Mazar (GitHub Actions, cada 2 horas).

Actualiza datos.json con datos que se publican en formato legible por máquina:
  - Celec Sur (servicio de datos del panel): cota de Mazar y caudal de entrada.
  - Cenace (página "Información Operativa"): generación térmica, importación,
    demanda nacional y energía de Coca Codo Sinclair, cada media hora.
  - Open-Meteo: temperatura máxima en Guayaquil y lluvia prevista en las
    cuencas del Paute y del Coca.
"Otras hidroeléctricas" es la generación medida por Cenace de todas las centrales
hidráulicas menos Coca Codo y el complejo Paute (Mazar, Molino, Sopladora). Paute
queda como la central que cubre lo que falta, igual que en la operación real.

Lo que no se publica como dato (los cortes a empresas) lo fija Claude en el
bloque "manual" de datos.json. El robot respeta siempre ese bloque:
  cut (MW de ahorro en un día con cortes), cut_dias (domingo a sábado, días con
  cortes en adelante) y cortes_registro ({"AAAA-MM-DD": MW}, lo que se aplicó
  de verdad cada día pasado; sirve para calcular la demanda de la semana medida) y
  cortes_plan ({"AAAA-MM-DD": MW}, cortes ya anunciados o de emergencia para hoy y días
  siguientes; mandan sobre cut_dias en esas fechas).
Si una fuente falla, el robot conserva el valor anterior de lo que depende de
ella y sigue con el resto.
"""
import base64, html as htmllib, json, math, os, re, ssl, struct, sys, urllib.request
from datetime import datetime, timedelta, timezone

EC = timezone(timedelta(hours=-5))
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGO = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
               "septiembre", "octubre", "noviembre", "diciembre"]

CELEC = "https://generacioncsr.celec.gob.ec:8443/ords/csr/sardomcsr/pointValues"
MRID_COTA, MRID_CAUDAL = 30031, 30538
CENACE = "https://www.cenace.gob.ec/info-operativa/InformacionOperativa.htm"
# Puntos de pronóstico: Guayaquil; cuenca alta del Paute (2); cuenca del Coca (2)
METEO = ("https://api.open-meteo.com/v1/forecast?latitude=-2.19,-2.75,-2.55,-0.20,-0.05"
         "&longitude=-79.89,-78.85,-78.60,-77.70,-77.55"
         "&daily=temperature_2m_max,precipitation_sum&past_days=7&forecast_days=7"
         "&timezone=America%2FGuayaquil")

SERIE = "serie_cenace.json"
LOG = []


def log(msg):
    LOG.append(msg)
    print(msg)


# El servidor de Cenace no envía su certificado intermedio (Sectigo DV R36). Se descarga desde la
# dirección que indica el propio certificado y se agrega a la lista de confianza; la verificación
# completa de la cadena hasta una raíz reconocida sigue activa.
INTERMEDIO_CENACE = "http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt"
_CTX = {}


def contexto(con_intermedio):
    if con_intermedio not in _CTX:
        ctx = ssl.create_default_context()
        if con_intermedio:
            der = urllib.request.urlopen(INTERMEDIO_CENACE, timeout=30).read()
            ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
        _CTX[con_intermedio] = ctx
    return _CTX[con_intermedio]


def get(url, intermedio_cenace=False, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (simulador-mazar-robot)"})
    with urllib.request.urlopen(req, timeout=timeout, context=contexto(intermedio_cenace)) as r:
        return r.read()


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def r10(v):
    return int(round(v / 10.0) * 10)


def corte_del_dia(manual, cut, fecha):
    """MW de ahorro por cortes a empresas en una fecha (date).
    1) manual["cortes_registro"]["AAAA-MM-DD"]: lo que Claude verificó que se aplicó ese día;
    2) si no está, manual["cut_dias"] (domingo a sábado) decide si hubo cortes (cut o 0);
    3) si tampoco hay cut_dias, se asume cut todos los días."""
    reg = manual.get("cortes_registro") or {}
    v = reg.get(fecha.isoformat()) if isinstance(reg, dict) else None
    if v is None:
        pl = manual.get("cortes_plan") or {}
        v = pl.get(fecha.isoformat()) if isinstance(pl, dict) else None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(clamp(v, 0, 700))
    cd = manual.get("cut_dias")
    if isinstance(cd, list) and len(cd) == 7:
        return float(cut) if cd[(fecha.weekday() + 1) % 7] else 0.0
    return float(cut)


def corte_promedio(manual, cut, dias, pesos=None):
    """Ahorro medio por cortes en una lista de fechas 'AAAA-MM-DD' (los días medidos de Paute), con los mismos
    pesos que el promedio de Paute cuando se dan."""
    vals = [corte_del_dia(manual, cut, datetime.strptime(d, "%Y-%m-%d").date()) for d in dias]
    if not vals:
        return float(cut)
    w = pesos if pesos and len(pesos) == len(vals) else [1.0] * len(vals)
    return sum(v * x for v, x in zip(vals, w)) / sum(w)


# ---------------------------------------------------------------- Física de Paute (Celec Sur)
# Cuánto baja Mazar por cada MW que genera el complejo Paute no es un número fijo: Molino y
# Sopladora también usan el agua que llega a Amaluza entre las dos presas. Por eso se calcula
# con datos reales: energía diaria de Mazar, Molino y Sopladora, caudal de entrada y variación
# de la cota de los últimos días completos.
CELEC_ORDS = "https://generacioncsr.celec.gob.ec:8443/ords/csr/"
ENERGIA_PAUTE = ("sardommaz/mazEnerDia", "sardommol/molEnerDia", "sardomsop/sopEnerDia")


def _celec_items(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (simulador-mazar)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("items", [])


def _celec_puntos(mrid, dia):
    ini = datetime(dia.year, dia.month, dia.day, 1, tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
    fin = ini + timedelta(hours=23)
    url = (f"{CELEC_ORDS}sardomcsr/pointValues?mrid={mrid}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
           f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={dia:%d/%m/%Y}%2001:00:00")
    return sorted((i["loctimestamp"], float(i["valueedit"])) for i in _celec_items(url) if i.get("valueedit") is not None)


def fisica_paute(hoy_local, dias_k=10, dias_p=7):
    """Devuelve k (MW por m³/s que sale de Mazar), Paute medio de los últimos días y el detalle."""
    area = lambda c: 3.758 + 0.2177 * (c - 2115)   # hm³ por metro de cota
    filas = []
    for n in range(dias_k, 0, -1):
        d = hoy_local - timedelta(days=n)
        cota_fin = _celec_puntos(30031, d)
        cota_ini = _celec_puntos(30031, d - timedelta(days=1))
        caudal = _celec_puntos(30538, d)
        horas = []
        energia = 0.0
        for ep in ENERGIA_PAUTE:
            vals = [float(i["valueedit"]) for i in _celec_items(f"{CELEC_ORDS}{ep}?fecha={d:%d/%m/%Y}%2000:00:00")
                    if i.get("valueedit") is not None]
            horas.append(len(vals))
            energia += sum(vals)
        if len(cota_fin) < 20 or len(cota_ini) < 20 or len(caudal) < 20 or min(horas) < 20:
            continue  # día incompleto
        c0, c1 = cota_ini[-1][1], cota_fin[-1][1]
        q = sum(v for _, v in caudal) / len(caudal)
        p = energia / 24.0
        salida = q - (c1 - c0) * area((c0 + c1) / 2) * 1e6 / 86400   # m³/s que salieron de Mazar
        filas.append({"dia": d.isoformat(), "paute_mw": round(p), "caudal": round(q, 1),
                      "cota": round(c1, 2), "variacion": round(c1 - c0, 2), "salida": round(salida, 1)})
    if len(filas) < 5:
        raise ValueError(f"solo {len(filas)} días completos en Celec")
    k = sum(f["paute_mw"] for f in filas) / max(1.0, sum(f["salida"] for f in filas))
    ult = filas[-dias_p:]
    p7 = sum(f["paute_mw"] for f in ult) / len(ult)
    # Cada día pesa según su antigüedad: ayer pesa 1 y el peso se reduce a la mitad cada 3 días. Probado con
    # 1.356 días de Celec (2023–2026): predice mejor lo que Paute generará en los próximos 3, 7 y 14 días que el
    # promedio simple de 7 días, sobre todo después de un día atípico (−15 % de error), sin que un día lo cambie todo.
    for f in filas:
        edad = (hoy_local - datetime.strptime(f["dia"], "%Y-%m-%d").date()).days - 1
        f["peso"] = round(0.5 ** (edad / 3.0), 3)
    pp = sum(f["paute_mw"] * f["peso"] for f in filas) / sum(f["peso"] for f in filas)
    return {"k_mw_por_m3s": round(min(20.0, max(7.0, k)), 2), "paute_prom_mw": round(pp), "paute_prom7_mw": round(p7),
            "ponderado": "vida media 3 días", "dias_pond": len(filas),
            "dias_k": len(filas), "dias_p": len(ult), "desde": filas[0]["dia"], "hasta": filas[-1]["dia"],
            "detalle": filas}


# ---------------------------------------------------------------- Celec Sur
def celec_dia(mrid, dia):
    ini = datetime(dia.year, dia.month, dia.day, 1, tzinfo=EC).astimezone(timezone.utc)
    fin = ini + timedelta(hours=23)
    url = (f"{CELEC}?mrid={mrid}&fechaInicio={ini:%Y-%m-%dT%H:%M:%S.000Z}"
           f"&fechaFin={fin:%Y-%m-%dT%H:%M:%S.000Z}&fecha={dia:%d/%m/%Y}%2001:00:00")
    items = json.loads(get(url)).get("items", [])
    out = []
    for it in items:
        v = it.get("valueedit")
        if v is None:
            continue
        t = datetime.strptime(it["loctimestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        out.append((t.astimezone(EC), float(v)))
    return out


def celec_serie(mrid, ahora):
    hoy = ahora.date()
    return sorted(celec_dia(mrid, hoy - timedelta(days=2)) + celec_dia(mrid, hoy - timedelta(days=1))
                  + celec_dia(mrid, hoy))


def valor_en(serie, t, tol_h=0.75):
    cand = [(abs((tt - t).total_seconds()), v) for tt, v in serie]
    cand = [c for c in cand if c[0] <= tol_h * 3600]
    return min(cand)[1] if cand else None


# ---------------------------------------------------------------- Cenace
FMT = {"f8": "d", "f4": "f", "i1": "b", "u1": "B", "i2": "h", "u2": "H", "i4": "i", "u4": "I"}


def plotly_y(y):
    if isinstance(y, dict) and "bdata" in y:
        dt = y.get("dtype", "f8").lstrip("<|")
        raw = base64.b64decode(y["bdata"])
        n = len(raw) // struct.calcsize(FMT[dt])
        vals = struct.unpack("<" + FMT[dt] * n, raw)
    else:
        vals = y
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in vals]


def cenace():
    page = get(CENACE, intermedio_cenace=True).decode("utf-8", "replace")
    texto = htmllib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", page, flags=re.S)))
    texto = re.sub(r"\s+", " ", texto)
    m = re.search(r"PRODUCCIÓN EN TIEMPO REAL \w+, (\d{1,2}) de (\w+) de (\d{4})", texto)
    if not m:
        raise ValueError("no se encontró la fecha de 'Producción en tiempo real'")
    fecha = datetime(int(m.group(3)), MESES_LARGO.index(m.group(2).lower()) + 1, int(m.group(1))).date()

    dec = json.JSONDecoder()
    plots = []
    for mm in re.finditer(r'Plotly\.newPlot\(\s*"[^"]+",\s*', page):
        obj, _ = dec.raw_decode(page, mm.end())
        plots.append(obj)
    curvas = [p for p in plots if any(tr.get("name") == "DEMANDA NACIONAL" for tr in p)]
    plantas = next(p for p in plots if any(tr.get("name") == "Coca Codo" for tr in p))
    hoy_filas = filas(curvas[0])
    # Segundo bloque: "Información operativa diaria" (último día completo que publica Cenace)
    md = re.search(r"INFORMACIÓN OPERATIVA DIARIA \w+, (\d{1,2}) de (\w+) de (\d{4})", texto)
    perfil, fecha_perfil = {}, None
    if md and len(curvas) > 1:
        fecha_perfil = datetime(int(md.group(3)), MESES_LARGO.index(md.group(2).lower()) + 1, int(md.group(1))).date()
        perfil = filas(curvas[1])
    mwh = {tr["name"].strip(): float(tr["y"][0]) for tr in plantas if isinstance(tr.get("y"), list) and tr["y"]}
    # Energía hidráulica total (tortas) y por central (barras): [0] = hoy, [1] = último día completo
    tortas = [p for p in plots if any("HIDROELÉCTRICA" in (tr.get("labels") or []) for tr in p)]
    barras = [p for p in plots if any(tr.get("name") == "Coca Codo" for tr in p)]
    def hidro_total(torta):
        tr = torta[0]
        return float(tr["values"][tr["labels"].index("HIDROELÉCTRICA")])
    def por_central(barra):
        return {tr["name"].strip(): float(tr["y"][0]) for tr in barra if isinstance(tr.get("y"), list) and tr["y"]}
    energia = {}
    if tortas and barras:
        energia["hoy"] = {"hidro": hidro_total(tortas[0]), **por_central(barras[0])}
    if len(tortas) > 1 and len(barras) > 1:
        energia["perfil"] = {"hidro": hidro_total(tortas[1]), **por_central(barras[1])}
    mwh["_energia"] = energia
    puntos = {f"{fecha.isoformat()}T{hh}": f for hh, f in hoy_filas.items()}
    return fecha, puntos, mwh, perfil, fecha_perfil


def otras_mw(e, horas):
    """MW medios de las hidroeléctricas que no son Coca Codo ni el complejo Paute."""
    paute = sum(e.get(k, 0.0) for k in ("Paute", "Sopladora", "Mazar"))
    return (e["hidro"] - e.get("Coca Codo", 0.0) - paute) / horas, paute / horas


CLAVE = {"Hidráulica": "h", "Térmica": "t", "Importación": "i", "Renovable": "r",
         "Exportación": "e", "DEMANDA NACIONAL": "d"}


def filas(curva):
    """{'HH:MM': {h,t,i,r,e,d}} a partir de una curva de generación de Cenace."""
    series = {tr["name"]: plotly_y(tr["y"]) for tr in curva}
    out = {}
    for k, hh in enumerate(curva[0]["x"]):
        fila = {}
        for nombre, c in CLAVE.items():
            arr = series.get(nombre)
            if arr is None or k >= len(arr) or arr[k] is None:
                fila = None
                break
            fila[c] = arr[k]
        if fila and fila["d"] > 1000:  # descarta medias horas aún sin dato
            out[hh] = fila
    return out


# ---------------------------------------------------------------- Open-Meteo
def pronostico(ahora):
    locs = json.loads(get(METEO))
    hoy = ahora.date().isoformat()
    gye = locs[0]["daily"]
    i_hoy = gye["time"].index(hoy)
    i_t = i_hoy + 1 if ahora.hour >= 18 else i_hoy  # en la noche se usa el pronóstico de mañana
    tmax = gye["temperature_2m_max"][i_t]

    def cuenca(idx):
        pas, fut = [], []
        for j in idx:
            d = locs[j]["daily"]
            k = d["time"].index(hoy)
            pas.append(sum(x or 0 for x in d["precipitation_sum"][k - 7:k]))
            fut.append(sum(x or 0 for x in d["precipitation_sum"][k:k + 7]))
        return sum(pas) / len(pas), sum(fut) / len(fut)

    return tmax, cuenca([1, 2]), cuenca([3, 4]), gye["time"][i_t]


def categoria(pasado, futuro):
    """Regla fija: seco < 15 mm en 7 días; lluvia sostenida ('nino') solo si
    se esperan > 70 mm y ya llovieron > 40 mm la semana anterior; lo demás es
    un pulso de lluvia ('inamhi')."""
    if futuro < 15:
        return "seco"
    if futuro > 70 and pasado > 40:
        return "nino"
    return "inamhi"


NOMBRE_CAT = {"seco": "seco", "inamhi": "pulso de lluvia", "nino": "lluvia sostenida"}


def manual_activo(manual, clave, hoy):
    v = manual.get(clave)
    if v is None:
        return None
    hasta = manual.get(clave + "_hasta")
    if hasta and hoy > hasta:
        return None
    return v



# ---------------------------------------------------------------- Modelo calibrado con el historial
# Los parámetros los calcula scripts/calibrar.py una vez al día con todo el historial de Celec Sur.
# Aquí se preparan las entradas del día para modelo.js (que usan las dos páginas) y se repite el mismo
# cálculo en Python para guardar la predicción del día y medir después cuánto acertó.
F_PARAM = "parametros_modelo.json"
F_HIST = os.path.join("historial", "celec_diario.json")
F_CLIM = os.path.join("historial", "clima_lluvia_paute.json")
F_REG = os.path.join("registro", "predicciones.json")
F_VER = os.path.join("registro", "verificacion.json")
F_COCA_PRED = os.path.join("registro", "coca_predicciones.json")   # pronóstico GloFAS del río Coca en cada corrida
F_TRAY = os.path.join("registro", "trayectorias.json")             # trayectoria sin memoria de cada corrida (para la memoria de 48 h)
F_COCA_RIO = os.path.join("registro", "coca_rio.json")             # caudal REAL horario del río Coca en Coca Codo Sinclair (Celec, punto 100037)
MRID_COCA = 100037
# Coca Codo Sinclair: MW ≈ 5,25 × (caudal − 21 m³/s), con tope continuo de 1.200 MW (≈ 250 m³/s). Ajustado con la
# generación diaria de Cenace y el caudal de Celec (18–20 oct 2026); coincide con "240–250 m³/s para 1.200 MW".
CCS_K, CCS_E, CCS_CAP = 5.25, 21.0, 1200.0
RIO = None   # caché de caudales reales del río Coca (se llena en main)
# Cuánto se parece el río de los próximos días al caudal de AHORA; el resto lo pone su nivel NORMAL = mediana de los
# últimos 7 días (una crecida no la infla, a diferencia del promedio de 72 h). Desde el día 11 el río vuelve a ese nivel.
# Aprendido con el caudal horario de Celec (400 días, 1.448 casos; 597 tras crecidas): frente a la regla anterior
# (promedio de 72 h fijo) el sesgo optimista tras una crecida baja de +77/+75/+116 a +36/+14/+56 MW (días 4–10/11–20/21–30)
# y en días normales queda en ~0. Tras una crecida súbita los pesos aprendidos son casi iguales, así que no hace falta otra regla.
W_RIO = [0.565, 0.235, 0.158, 0.12, 0.147, 0.117, 0.084, 0.101, 0.108, 0.183]
F_COCA_OBS = os.path.join("registro", "coca_observado.json")       # caudal equivalente de Coca Codo (Cenace) en cada corrida   # cada predicción comparada con la cota real a la misma hora
HORIZ_VER = (1, 2, 3, 5, 7, 10, 14, 20, 30)


def _json_url(url, timeout=60, intentos=4):
    import time
    for k in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (simulador-mazar)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if k == intentos - 1:
                raise
            time.sleep(5 * (k + 1))


def _vol_amaluza(h, am_par):
    piso = am_par["piso"]; a, b = am_par["area"]
    if h <= piso:
        return 0.0
    return a * (h - piso) + b * ((h - 1971) ** 2 - (piso - 1971) ** 2) / 2


def serie_caudal_paute(par, q0, hoy_d, dias=61, semana_seca=False):
    """Caudal de entrada a Mazar día a día (relativo al de hoy) con el modelo lluvia–caudal calibrado.
    Lluvia: pronóstico ECMWF corregido por su sesgo medido en la cuenca (pronostica de más); desde el día 5
    se mezcla poco a poco con la lluvia normal de la fecha, que es la única que se usa desde el día 15."""
    locs = _json_url("https://api.open-meteo.com/v1/forecast?latitude=-2.75,-2.55&longitude=-78.85,-78.60"
                     "&daily=precipitation_sum&past_days=31&forecast_days=16&models=ecmwf_ifs025"
                     "&timezone=America%2FGuayaquil")
    sesgo = par.get("sesgo_lluvia_pronostico", 0.72)
    lluvia = {}
    for loc in locs:
        for t, v in zip(loc["daily"]["time"], loc["daily"]["precipitation_sum"]):
            if v is not None:
                lluvia.setdefault(t, []).append(v * sesgo)
    lluvia = {t: sum(v) / len(v) for t, v in lluvia.items()}
    if semana_seca:
        # Escenario "semana seca": los próximos 7 días llueve lo mismo que en los 7 anteriores
        pasada = [lluvia.get((hoy_d - timedelta(days=k)).isoformat()) for k in range(1, 8)]
        pasada = [x for x in pasada if x is not None]
        media = sum(pasada) / len(pasada) if pasada else 0.0
        for j in range(0, 8):
            lluvia[(hoy_d + timedelta(days=j)).isoformat()] = media
    clim = json.load(open(F_CLIM, encoding="utf-8"))
    def p(d):
        normal = clim[d.timetuple().tm_yday - 1]
        k = d.isoformat()
        if k not in lluvia:
            return normal
        j = (d - hoy_d).days
        w = 1.0 if j <= (7 if semana_seca else 5) else max(0.0, 1 - (j - 5) / 10)
        return w * lluvia[k] + (1 - w) * normal
    co = par["caudal_coef"]
    # caudal de los últimos 30 días (memoria de la sequía): historial de Celec + el de hoy
    H = json.load(open(F_HIST, encoding="utf-8"))
    hq = [H[k]["q"] for k in sorted(H) if k < hoy_d.isoformat()][-29:] + [q0]
    q = q0; serie = [1.0]
    for j in range(1, dias):
        d = hoy_d + timedelta(days=j)
        p36 = sum(p(d - timedelta(days=k)) for k in range(3, 7)) / 4
        p730 = sum(p(d - timedelta(days=k)) for k in range(7, 31)) / 24
        q = math.exp(co[0] + co[1] * math.log(max(q, 1.0)) + co[2] * math.log(max(sum(hq[-30:]) / len(hq[-30:]), 1.0))
                     + co[3] * p(d) + co[4] * p(d - timedelta(days=1)) + co[5] * p(d - timedelta(days=2))
                     + co[6] * p36 + co[7] * p730)
        hq.append(q)
        serie.append(round(q / q0, 4))
    previstos = sum(lluvia.get((hoy_d + timedelta(days=j)).isoformat(), 0) for j in range(1, 8))
    return serie, previstos


def serie_caudal_coca(dias=61):
    """Caudal del río Coca relativo al de hoy según el pronóstico hidrológico GloFAS (Open-Meteo)."""
    f = _json_url("https://flood-api.open-meteo.com/v1/flood?latitude=-0.2&longitude=-77.7"
                  f"&daily=river_discharge&past_days=1&forecast_days={dias}")
    v = [x for x in f["daily"]["river_discharge"]][1:1 + dias]
    if not v or not v[0]:
        raise ValueError("GloFAS sin datos para el río Coca")
    # Después de 10 días el pronóstico pierde precisión: su efecto se atenúa hacia el caudal de hoy
    out = []
    for j, x in enumerate(v):
        rel = min(2.5, max(0.4, (x or v[0]) / v[0]))
        w = 1.0 if j <= 10 else max(0.3, 1 - (j - 10) / 20)
        out.append(round(1 + (rel - 1) * w, 4))
    return out


def perfil_py(kind, t, q0, target, serie):
    if kind == "auto" and serie and len(serie) > 1:
        i = min(len(serie) - 2, int(math.floor(t))); f = min(1.0, t - i)
        return q0 * (serie[i] + (serie[i + 1] - serie[i]) * f)
    if kind == "seco":
        return q0 * max(0.7, 1 - 0.01 * t)
    if kind in ("inamhi", "auto"):
        b0 = math.exp(-1.6)
        return q0 * (1 + 0.45 * max(0.0, math.exp(-((t - 2) ** 2) / 2.5) - b0) / (1 - b0))
    return q0 + (target - q0) * (1 - math.exp(-t / 7))


def simular_py(P, ctx, par, horizonte=60):
    """Mismo cálculo que modelo.js → simular()."""
    dt = 0.25
    a, b = par["curva_mazar"]["a"], par["curva_mazar"]["b"]
    vol = lambda x: a * x + b * x * x / 2
    xo = lambda v: 0.0 if v <= 0 else (-a + math.sqrt(a * a + 2 * b * v)) / b
    kms, beta, eta = par["k_molino_sopladora"], par["beta_cuenca_intermedia"], par["eficiencia_mazar"]
    amC = ctx["amaluzaCota"]; am_rest = _vol_amaluza(amC, par["amaluza"]); am_ritmo = max(0.0, ctx["amaluzaRitmo"])
    V = vol(ctx["cota"] - 2115); VMAX = vol(2153 - 2115); Vv = V
    kA = float(ctx.get("ajuste") or 1.0)
    mem = ctx.get("memoria") or None
    mem_at = (lambda t: float(mem[min(len(mem) - 1, int(math.floor(t)))] or 0.0)) if mem else (lambda t: 0.0)
    diarios, cruce = [], None
    for step in range(int(horizonte / dt) + 1):
        t = step * dt
        dia = (ctx["diaSemana0"] + int(math.floor(t))) % 7
        qin = perfil_py(P["wPaute"], t, P["qMazar"], 66, ctx["serieMazar"])
        qc = perfil_py(P["wCoca"], t, P["qCoca"], 280, ctx["serieCoca"])
        rf = min(1.35, max(0.8, qc / P["qCoca"]))
        plan = (ctx.get("cutPlan") or [])
        kd = int(math.floor(t))
        if kd < len(plan) and isinstance(plan[kd], (int, float)) and not isinstance(plan[kd], bool):
            cut = plan[kd]
        else:
            cut = P["cut"] if (not ctx.get("cutDias") or ctx["cutDias"][dia]) else 0
        demanda = P["demanda"] + ctx["deltaDia"][dia] - cut
        ccs = min(5 * qc, 1200) * (0.5 if qc > 450 else 1)
        req = demanda - ccs - P["other"] * rf - P["therm"] - P["imp"]
        cota_ahora = 2115 + xo(V)
        kmz = 0.00981 * eta * max(20.0, cota_ahora - amC)
        saque = min(am_ritmo * dt, am_rest); am_rest -= saque
        inter = beta * qin + saque / dt / 0.0864
        pv = min(max(req, 0), 1757)
        kmzv = 0.00981 * eta * max(20.0, 2115 + (xo(Vv) if Vv > 0 else Vv / a) - amC)
        dqv = qin - max(0.0, (pv - kms * inter) / (kmzv + kms))
        if dqv < 0:
            dqv *= kA
        dqv += mem_at(t)
        Vv = min(VMAX, Vv + dqv * 86400 * dt / 1e6)
        if V > 0:
            paute = min(max(req, 0), 1757)
            qt = max(0.0, (paute - kms * inter) / (kmz + kms))
            dq = qin - qt
            if dq < 0:
                dq *= kA                      # autoajuste: corrige la bajada según los aciertos recientes
            dq += mem_at(t)                   # memoria de las corridas de las últimas 48 h
            Vp = V; V += dq * 86400 * dt / 1e6
            V = min(V, VMAX)
            if V <= 0 and cruce is None:
                cruce = t + dt * (Vp / (Vp - V)); V = 0.0
        else:
            filo = qin * (kmz + kms) + kms * inter
            paute = min(max(req, 0), filo, 1757)
            qt = max(0.0, (paute - kms * inter) / (kmz + kms))
            V += max(0.0, qin - qt) * 86400 * dt / 1e6
        if abs(t - round(t)) < 1e-9:
            diarios.append({"t": t, "cota": 2115 + xo(V), "cotaV": 2115 + (xo(Vv) if Vv > 0 else Vv / a),
                            "paute": paute, "qturb": qt, "qin": qin})
    return diarios, cruce


def memoria_corridas(ts, cota0, diarios, par, horas=48, tope=40.0):
    """Ladrillo a ladrillo: guarda la trayectoria de esta corrida (sin memoria) y calcula cuánto difiere de ella
    el promedio de las corridas de las últimas `horas` (cada una anclada a su propia cota). Devuelve la diferencia
    como caudal de corrección diario (m³/s) para que ningún dato suelto mueva sola la proyección."""
    t_now = datetime.fromisoformat(ts)
    cv = [round(d["cotaV"], 3) for d in diarios]
    reg = [e for e in _leer_json(F_TRAY, []) if e.get("ts") != ts]
    reg.append({"ts": ts, "cota": cota0, "cv": cv})
    reg = [e for e in reg if (t_now - datetime.fromisoformat(e["ts"])).total_seconds() <= 72 * 3600]
    reg.sort(key=lambda e: e["ts"])
    os.makedirs("registro", exist_ok=True)
    with open(F_TRAY, "w", encoding="utf-8") as fo:
        json.dump(reg, fo, ensure_ascii=False, separators=(",", ":"))
    def en(a, x):
        n = len(a) - 1
        if x >= n:
            return a[n] + (a[n] - a[n - 1]) * (x - n)
        i = int(math.floor(x)); return a[i] + (a[i + 1] - a[i]) * (x - i)
    usadas = []
    for e in reg:
        o = (t_now - datetime.fromisoformat(e["ts"])).total_seconds() / 86400
        if 0 <= o < horas / 24:
            usadas.append((e, o))
    if len(usadas) < 3:
        return None, len(usadas), None
    # Peso de cada corrida: (1) antigüedad, la mitad cada 24 h; (2) acierto, comparando lo que dijo con la cota REAL de
    # las corridas que vinieron después (error de 0,5 m → pesa 60 % menos). La corrida más nueva, que aún no se puede
    # comparar, recibe el mejor acierto del grupo. Probado con 52 corridas: mismo error a 1–3 días que pesos iguales,
    # pero el número responde a lo que la realidad confirma (p. ej. una crecida) sin saltar más de ~5 días por corrida.
    def acierto(e, o):
        err = []
        for f, of in usadas:
            if of < o:
                err.append(en(e["cv"], o - of) - f["cota"])
        if not err:
            return None
        rmse = math.sqrt(sum(x * x for x in err) / len(err))
        return math.exp(-0.5 * (rmse / 0.5) ** 2), rmse
    ac = [acierto(e, o) for e, o in usadas]
    mejor = max([x[0] for x in ac if x], default=1.0)
    pesos = [(0.5 ** o) * (x[0] if x else mejor) for (e, o), x in zip(usadas, ac)]
    sw = sum(pesos)
    a, b = par["curva_mazar"]["a"], par["curva_mazar"]["b"]
    V = lambda c: (a * (c - 2115) + b * (c - 2115) ** 2 / 2) if c >= 2115 else (c - 2115) * a
    cb = lambda t: cota0 + sum(w * (en(e["cv"], o + t) - en(e["cv"], o)) for (e, o), w in zip(usadas, pesos)) / sw
    mem = []
    for d in range(len(cv) - 1):
        v = ((V(cb(d + 1)) - V(cb(d))) - (V(cv[d + 1]) - V(cv[d]))) * 1e6 / 86400
        mem.append(max(-tope, min(tope, v)))
    # Número grande: promedio PONDERADO de las fechas que dio cada corrida (2.116 entrada a la zona crítica y
    # 2.115 parada de Mazar). Una corrida nueva solo lo mueve en proporción a su peso.
    def cruce(c, U):
        for k in range(1, len(c)):
            if c[k] <= U:
                return k - 1 + (c[k - 1] - U) / max(1e-6, c[k - 1] - c[k])
        return None
    def num(U):
        vals = []
        for (e, o), w in zip(usadas, pesos):
            c = cruce(e["cv"], U)
            vals.append((max(0.0, (c if c is not None else 60.0) - o), w, c is not None))
        dias = sum(v * w for v, w, _ in vals) / sw
        orden = sorted(vals)
        acum, lo, hi = 0.0, None, None
        for v, w, _ in orden:
            acum += w / sw
            if lo is None and acum >= 0.1:
                lo = v
            if hi is None and acum >= 0.9:
                hi = v
        return {"dias": round(dias, 1), "rango": [round(lo, 1), round(hi, 1)],
                "entran": round(sum(w for _, w, x in vals if x) / sw, 2)}
    numero = {"critica": num(2116.0), "parada": num(2115.0), "corridas": len(usadas),
              "peso_ultima": round(pesos[-1] / sw, 3),
              "nota": "promedio ponderado de las fechas de las corridas de las últimas 48 h (antigüedad y acierto)"}
    return mem, len(usadas), numero


def rango_py(diarios, cuant, cota0, umbral=2115):
    """Mismo cálculo que modelo.js → rango()."""
    if not cuant:
        return None
    hs = sorted(int(h) for h in cuant)
    def q(t, i):
        h = hs[0]
        for k in hs:
            if abs(k - t) < abs(h - t):
                h = k
        return cuant[str(h)][i]
    def cruza(i):
        for k in range(1, len(diarios)):
            c1 = cota0 - q(diarios[k]["t"], i) * (cota0 - diarios[k]["cotaV"])
            if c1 <= umbral:
                c0 = cota0 - q(diarios[k - 1]["t"], i) * (cota0 - diarios[k - 1]["cotaV"])
                return diarios[k - 1]["t"] + (c0 - umbral) / max(1e-6, c0 - c1)
        return None
    if cota0 <= umbral:
        return 0.0, 0.0
    return cruza(1), cruza(0)


def date_from(txt):
    from datetime import date as _d
    return _d.fromisoformat(txt)



def zona_critica_py(diarios, cruce, cota0, umbral=2116.0):
    """Mismo cálculo que modelo.js → zonaCritica(): entrada y salida de la zona crítica (2.116 m),
    punto más bajo de ese episodio y si la parada (2.115 m) ocurre dentro de él."""
    entrada = 0.0 if cota0 <= umbral else None
    salida = None
    for k in range(1, len(diarios)):
        a, b = diarios[k - 1], diarios[k]
        if entrada is None:
            if b["cota"] <= umbral:
                entrada = a["t"] + (a["cota"] - umbral) / max(1e-6, a["cota"] - b["cota"])
        elif b["cota"] > umbral:
            salida = a["t"] + (umbral - a["cota"]) / max(1e-6, b["cota"] - a["cota"])
            break
    minimo = None
    if entrada is not None:
        for r in diarios:
            if r["t"] >= math.floor(entrada) and (salida is None or r["t"] <= math.ceil(salida)) \
                    and (minimo is None or r["cota"] < minimo["cota"]):
                minimo = {"t": r["t"], "cota": round(r["cota"], 2)}
    en_ventana = cruce is not None and entrada is not None and (salida is None or cruce <= salida)
    return {"entrada": entrada, "salida": salida, "parada": cruce, "parada_en_ventana": en_ventana, "minimo": minimo}

def probabilidades_py(diarios, perc, cota0, umbral, horizontes=(7, 14, 30)):
    """Mismo cálculo que modelo.js → probabilidades()."""
    if not perc:
        return None
    hs = sorted(int(h) for h in perc)
    n = len(perc[str(hs[0])])
    def r(t, i):
        h = hs[0]
        for k in hs:
            if abs(k - t) < abs(h - t):
                h = k
        return perc[str(h)][i]
    tiempos = []
    for i in range(n):
        tc = 0.0 if cota0 <= umbral else None
        for k in range(1, len(diarios)):
            if tc is not None:
                break
            c1 = cota0 - r(diarios[k]["t"], i) * (cota0 - diarios[k]["cotaV"])
            if c1 <= umbral:
                c0 = cota0 - r(diarios[k - 1]["t"], i) * (cota0 - diarios[k - 1]["cotaV"])
                tc = diarios[k - 1]["t"] + (c0 - umbral) / max(1e-6, c0 - c1)
        tiempos.append(tc)
    return {str(H): round(sum(1 for t in tiempos if t is not None and t <= H) / n, 3) for H in horizontes}



def _leer_json(ruta, defecto):
    try:
        return json.load(open(ruta, encoding="utf-8"))
    except Exception:
        return defecto


def autoajuste(ver, hoy_d):
    """Factor que corrige la bajada del modelo según cómo le fue de verdad (verificaciones a 1 y 2 días de los
    últimos 21 días). Se acerca a 1 cuando hay pocos datos (cada día distinto cuenta como un caso), y se limita
    a 0,80–1,30. Con menos de 3 días distintos no corrige."""
    desde = (hoy_d - timedelta(days=21)).isoformat()
    rat, dias = [], set()
    for v in ver:
        if v["h"] in (1, 2) and v["pred_ts"][:10] >= desde and v.get("cota0") is not None:
            cp = v["cota0"] - v["pred"]; cr = v["cota0"] - v["real"]
            if cp > 0.2:
                rat.append(cr / cp); dias.add(v["pred_ts"][:10])
    n = len(dias)
    if n < 3 or not rat:
        return {"factor": 1.0, "dias": n, "casos": len(rat), "ratio_mediana": None,
                "nota": "todavía pocos días comparados; sin corrección"}
    rat.sort(); med = rat[len(rat) // 2] if len(rat) % 2 else (rat[len(rat) // 2 - 1] + rat[len(rat) // 2]) / 2
    f = 1 + (med - 1) * n / (n + 10)
    f = max(0.80, min(1.30, f))
    return {"factor": round(f, 3), "dias": n, "casos": len(rat), "ratio_mediana": round(med, 3),
            "nota": f"la realidad bajó {med:.2f} veces lo predicho; se corrige {f:.3f} (con {n} días)"}


def verificar(ahora_lectura, cota_ahora):
    """Compara cada predicción guardada con la cota REAL de Celec Sur a la misma hora, 1–30 días después.
    Lee los puntos horarios de hoy y de los 2 días anteriores, así recupera lo que no alcanzó a ver antes."""
    reg = _leer_json(F_REG, [])
    ver = _leer_json(F_VER, [])
    hechas = {(v["pred_ts"], v["h"]) for v in ver}
    pts = {}
    d0 = ahora_lectura.date()
    for k in range(0, 3):
        try:
            for ts, val in _celec_puntos(30031, d0 - timedelta(days=k)):
                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ahora_lectura.tzinfo)
                pts[t.strftime("%Y-%m-%dT%H")] = val
        except Exception as e:
            log(f"Verificación: no se pudieron leer las cotas horarias ({e})")
    pts[ahora_lectura.strftime("%Y-%m-%dT%H")] = cota_ahora
    nuevas = 0
    for e in reg:
        ts = e.get("ts") or f"{e['fecha']}T{e.get('hora', '07:00')}:00-05:00"
        t0 = datetime.fromisoformat(ts)
        for h in HORIZ_VER:
            if (ts, h) in hechas:
                continue
            if e.get("traj") and len(e["traj"]) >= h:
                pred = e["traj"][h - 1]
            elif e.get("cota_pred", {}).get(str(h)) is not None:
                pred = e["cota_pred"][str(h)]
            else:
                continue
            obj = t0 + timedelta(days=h)
            real = pts.get(obj.strftime("%Y-%m-%dT%H"))
            if real is None:
                continue
            ver.append({"pred_ts": ts, "h": h, "obj_ts": obj.isoformat(timespec="minutes"), "cota0": e.get("cota"),
                        "pred": round(pred, 2), "real": round(real, 2), "err": round(pred - real, 2),
                        "origen": e.get("origen", "robot")})
            hechas.add((ts, h)); nuevas += 1
    limite = (d0 - timedelta(days=200)).isoformat()
    ver = sorted([v for v in ver if v["pred_ts"][:10] >= limite], key=lambda v: (v["obj_ts"], v["h"]))
    with open(F_VER, "w", encoding="utf-8") as fo:
        json.dump(ver, fo, ensure_ascii=False, indent=0)
    return ver, nuevas


def resumen_aciertos(ver):
    """Error medio y sesgo por horizonte (sesgo > 0: el modelo dijo más alto de lo que fue, optimista)."""
    out = {}
    for h in HORIZ_VER:
        es = [v["err"] for v in ver if v["h"] == h]
        if es:
            out[str(h)] = {"n": len(es), "dias": len({v["pred_ts"][:10] for v in ver if v["h"] == h}),
                           "error_medio_m": round(sum(abs(x) for x in es) / len(es), 2),
                           "sesgo_m": round(sum(es) / len(es), 2)}
    ult = [v for v in ver if v["h"] == 1]
    ultimo = ult[-1] if ult else None
    recientes = [v for v in ver if v["h"] == 1][-8:]
    return {"por_horizonte": out, "ultimo_1d": ultimo, "recientes_1d": recientes}



def ajuste_coca(hoy_d):
    """Corrección gradual del pronóstico GloFAS del río Coca según cómo le fue de verdad (análisis interno, no se
    muestra en las páginas). Compara cada pronóstico guardado con el caudal equivalente de Coca Codo (Cenace) 1–3
    días después a la misma hora (±1,5 h) y estima una deriva diaria a = mediana(ln(real/predicho)/k).
    Se acerca a 0 con pocos días (cada día distinto cuenta como un caso), se limita a ±5 %/día y se aplica hasta 7 días."""
    preds = _leer_json(F_COCA_PRED, [])
    obs = [(datetime.fromisoformat(o["ts"]), o["q"]) for o in _leer_json(F_COCA_OBS, []) if o.get("q")]
    if RIO:
        # Con el caudal REAL del río (Celec): pronóstico anclado al caudal real de las 24 h previas y comparado con
        # el caudal real de las 24 h previas al día objetivo. Ya no depende de lo que generó la central (que tiene tope).
        obs = []
        for p in preds:
            t0 = datetime.fromisoformat(p["ts"])
            q0r = rio_prom(RIO, t0)
            if q0r:
                p["q0"] = q0r
                for k in (1, 2, 3):
                    qk = rio_prom(RIO, t0 + timedelta(days=k))
                    if qk:
                        obs.append((t0 + timedelta(days=k), qk))
    desde = hoy_d - timedelta(days=21)
    tasas, dias, pares = [], set(), []
    for p in preds:
        t0 = datetime.fromisoformat(p["ts"])
        if t0.date() < desde or not p.get("q0") or not p.get("serie"):
            continue
        for k in (1, 2, 3):
            if k >= len(p["serie"]):
                continue
            obj = t0 + timedelta(days=k)
            cand = [o for o in obs if abs((o[0] - obj).total_seconds()) <= 5400]
            if not cand:
                continue
            real = min(cand, key=lambda o: abs((o[0] - obj).total_seconds()))[1]
            pred = p["q0"] * p["serie"][k]
            if pred > 0 and real > 0:
                tasas.append(math.log(real / pred) / k); dias.add(t0.date().isoformat())
                pares.append((k, pred, real))
    n = len(dias)
    if n < 3 or not tasas:
        return {"deriva_dia": 0.0, "dias": n, "casos": len(tasas), "nota": "pocos días; sin corrección"}
    tasas.sort(); m = tasas[len(tasas) // 2]
    a = max(-0.05, min(0.05, m * n / (n + 10)))
    err = {}
    for k in (1, 2, 3):
        e = [pr - re for kk, pr, re in pares if kk == k]
        if e:
            err[str(k)] = {"n": len(e), "error_medio": round(sum(abs(x) for x in e) / len(e), 1), "sesgo": round(sum(e) / len(e), 1)}
    return {"deriva_dia": round(a, 4), "deriva_observada": round(m, 4), "dias": n, "casos": len(tasas), "error_glofas": err,
            "nota": f"el Coca real va {m * 100:+.1f} %/día frente a GloFAS; se corrige {a * 100:+.1f} %/día (con {n} días)"}


def ccs_mw_rio(q):
    """MW que Coca Codo puede generar con un caudal real del río Coca."""
    return max(0.0, min(CCS_CAP, CCS_K * (q - CCS_E)))


def coca_rio(ahora, dias_atras=12):
    """Caudal real horario del río Coca (Celec). Guarda una caché en registro/coca_rio.json (hora local → m³/s):
    cada corrida vuelve a leer hoy y ayer y completa los días que falten."""
    cache = _leer_json(F_COCA_RIO, {})
    hoy_d = ahora.date()
    for n in range(dias_atras, -1, -1):
        d = hoy_d - timedelta(days=n)
        if n <= 1 or sum(1 for k in cache if k.startswith(d.isoformat())) < 20:
            try:
                for ts, v in _celec_puntos(MRID_COCA, d):
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(EC)
                    if 0 < v < 6000:
                        cache[t.strftime("%Y-%m-%dT%H")] = round(v, 1)
            except Exception as e:
                log(f"Río Coca (Celec) {d}: {e}")
    lim = (hoy_d - timedelta(days=400)).isoformat()
    cache = {k: v for k, v in sorted(cache.items()) if k >= lim}
    os.makedirs("registro", exist_ok=True)
    with open(F_COCA_RIO, "w", encoding="utf-8") as fo:
        json.dump(cache, fo, ensure_ascii=False, separators=(",", ":"))
    return cache


def _horas_rio(cache, fin, horas):
    ini = fin - timedelta(hours=horas)
    out = []
    for k, v in cache.items():
        t = datetime.strptime(k, "%Y-%m-%dT%H").replace(tzinfo=EC)
        if ini < t <= fin:
            out.append(v)
    return out


def rio_prom(cache, fin, horas=24):
    """Caudal real medio del río Coca en las `horas` anteriores a `fin` (None si faltan muchas horas)."""
    v = _horas_rio(cache, fin, horas)
    return sum(v) / len(v) if len(v) >= 0.6 * horas else None


def ccs_prom(cache, fin, horas=24):
    """MW medios que Coca Codo pudo generar con el río de esas horas (hora por hora, respetando el tope)."""
    v = _horas_rio(cache, fin, horas)
    return sum(ccs_mw_rio(x) for x in v) / len(v) if len(v) >= 0.6 * horas else None


def coca_base(cache, fin):
    """Caudal esperado del río Coca para los días 1..10 y, en la posición 11, el nivel normal al que vuelve (sin pronóstico de lluvia)."""
    ult = _horas_rio(cache, fin, 2)
    v24, v72, v7d = _horas_rio(cache, fin, 24), _horas_rio(cache, fin, 72), _horas_rio(cache, fin, 168)
    if not ult or len(v72) < 40 or len(v7d) < 100:
        return None, None
    ahora_q, q72 = sum(ult) / len(ult), sum(v72) / len(v72)
    s7 = sorted(v7d); n7 = len(s7)
    m7 = s7[n7 // 2] if n7 % 2 else (s7[n7 // 2 - 1] + s7[n7 // 2]) / 2
    prev = sorted(v24[:-1]) or [ahora_q]
    med = prev[len(prev) // 2]
    crecida = ahora_q >= 2.5 * med and med < 300          # solo informativo
    return [w * ahora_q + (1 - w) * m7 for w in W_RIO] + [m7], {"ahora": round(ahora_q, 1), "q72": round(q72, 1),
                                                                  "mediana7": round(m7, 1), "crecida": crecida}


def guardar_coca(ts, q0, serie_bruta):
    try:
        os.makedirs("registro", exist_ok=True)
        lim = (datetime.fromisoformat(ts) - timedelta(days=45)).isoformat()
        pr = [p for p in _leer_json(F_COCA_PRED, []) if p["ts"] >= lim and p["ts"] != ts]
        pr.append({"ts": ts, "q0": q0, "serie": [round(x, 4) for x in serie_bruta[:15]]})
        ob = [o for o in _leer_json(F_COCA_OBS, []) if o["ts"] >= lim and o["ts"] != ts]
        ob.append({"ts": ts, "q": q0})
        with open(F_COCA_PRED, "w", encoding="utf-8") as fo:
            json.dump(sorted(pr, key=lambda p: p["ts"]), fo, ensure_ascii=False, indent=0)
        with open(F_COCA_OBS, "w", encoding="utf-8") as fo:
            json.dump(sorted(ob, key=lambda o: o["ts"]), fo, ensure_ascii=False, indent=0)
    except Exception as e:
        log(f"Registro del río Coca: {e}")


def bloque_modelo(datos, hoy, ahora, fis, notas, fuentes):
    if not os.path.exists(F_PARAM):
        log("Modelo: falta parametros_modelo.json; se usa el modelo simple")
        return
    par = json.load(open(F_PARAM, encoding="utf-8"))
    hoy_d = datetime.fromisoformat(datos["fecha"]).date()
    manual = datos.get("manual", {})
    previo = datos.get("modelo") or {}
    mod = {k: par[k] for k in ("curva_mazar", "eficiencia_mazar", "k_molino_sopladora", "beta_cuenca_intermedia",
                               "amaluza", "rango_cuantiles", "retrospectiva", "calibrado", "historial")}
    mod["diaSemana0"] = (hoy_d.weekday() + 1) % 7          # JavaScript: 0 = domingo
    # Con caudal bajo (como en las sequías de 2023 y 2024) el rango sale solo de esas fechas
    if hoy.get("qMazar", 99) < 35 and par.get("rango_cuantiles_caudal_bajo"):
        mod["rango_cuantiles"] = par["rango_cuantiles_caudal_bajo"]
        mod["ratios_percentiles"] = par.get("ratios_percentiles_caudal_bajo")
        mod["retrospectiva"] = par.get("retrospectiva_caudal_bajo")
        mod["rango_base"] = "caudal bajo"
    else:
        mod["rango_base"] = "todas las fechas de estiaje"
        mod["ratios_percentiles"] = par.get("ratios_percentiles")
    # Amaluza: cota de ahora y cuánto se le ha sacado por día en la última semana
    try:
        pts = _celec_puntos(24019, ahora.date()) or _celec_puntos(24019, ahora.date() - timedelta(days=1))
        am_hoy = pts[-1][1]
        H = json.load(open(F_HIST, encoding="utf-8"))
        hace7 = (ahora.date() - timedelta(days=7)).isoformat()
        am_7 = H[hace7]["am"] if hace7 in H else am_hoy
        ritmo = max(0.0, (_vol_amaluza(am_7, par["amaluza"]) - _vol_amaluza(am_hoy, par["amaluza"])) / 7)
        mod["amaluzaCota"] = round(am_hoy, 2); mod["amaluzaRitmo"] = round(ritmo, 3)
        mod["amaluzaVolumen"] = round(_vol_amaluza(am_hoy, par["amaluza"]), 2)
    except Exception as e:
        log(f"Amaluza: {e}")
        if previo.get("amaluzaCota") and previo.get("amaluzaCota") != 1980.0:
            mod["amaluzaCota"] = previo["amaluzaCota"]; mod["amaluzaRitmo"] = previo.get("amaluzaRitmo", 0.0)
            mod["amaluzaVolumen"] = previo.get("amaluzaVolumen")
            log("Se conserva la última lectura buena de Amaluza")
        else:
            # Sin lectura buena previa: última cota de Amaluza del historial diario (nunca un valor inventado)
            try:
                H = json.load(open(F_HIST, encoding="utf-8"))
                ult = [H[k]["am"] for k in sorted(H) if H[k].get("am")][-1]
                mod["amaluzaCota"] = round(ult, 2); mod["amaluzaRitmo"] = float(previo.get("amaluzaRitmo") or 0.0)
                mod["amaluzaVolumen"] = round(_vol_amaluza(ult, par["amaluza"]), 2)
                log("Amaluza: se usa la última cota del historial diario")
            except Exception:
                mod["amaluzaCota"] = 1980.0; mod["amaluzaRitmo"] = 0.0; mod["amaluzaVolumen"] = None
    # Paute según el día de la semana (MW sobre o bajo su promedio)
    p7 = (fis or {}).get("paute_prom_mw") or 900
    f = par["factor_dia_semana_lun_dom"]
    js = [f[6]] + f[:6]
    mod["deltaDia"] = [round((x - 1) * p7, 1) for x in js]
    cd = manual.get("cut_dias")
    mod["cutDias"] = cd if (isinstance(cd, list) and len(cd) == 7) else None
    # Cortes ya anunciados o de emergencia por fecha (manual.cortes_plan, y cortes_registro para hoy):
    # mandan sobre el patrón semanal en esos días.
    plan_m = manual.get("cortes_plan") or {}
    reg_m = manual.get("cortes_registro") or {}
    cplan = []
    for k in range(61):
        fk = (hoy_d + timedelta(days=k)).isoformat()
        v = plan_m.get(fk) if isinstance(plan_m, dict) else None
        if v is None and isinstance(reg_m, dict):
            v = reg_m.get(fk)
        cplan.append(float(clamp(v, 0, 1500)) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
    mod["cutPlan"] = cplan if any(x is not None for x in cplan) else None
    if mod["cutPlan"]:
        log("Cortes por fecha: " + ", ".join(f"{(hoy_d + timedelta(days=k)).isoformat()} {x:.0f} MW"
                                             for k, x in enumerate(cplan) if x is not None))
    # Pronóstico de caudales
    serieM = serieC = None
    try:
        serieM, mm7 = serie_caudal_paute(par, hoy["qMazar"], hoy_d)
        mod["serieMazar"] = serieM
        try:
            mod["serieMazarSeca"], _ = serie_caudal_paute(par, hoy["qMazar"], hoy_d, semana_seca=True)
        except Exception as e:
            log(f"Escenario semana seca: {e}")
        fuentes["pronostico_caudal"] = {"ok": True}
        log(f"Caudal Mazar previsto: {hoy['qMazar']} → {hoy['qMazar']*serieM[7]:.0f} m³/s en 7 días, "
            f"{hoy['qMazar']*serieM[30]:.0f} en 30 (lluvia prevista 7 días {mm7:.0f} mm)")
    except Exception as e:
        fuentes["pronostico_caudal"] = {"ok": False, "error": str(e)[:200]}
        log(f"Pronóstico de caudal del Paute falló: {e}")
        dias_previo = (hoy_d - date_from(previo.get("serie_fecha"))).days if previo.get("serie_fecha") else 99
        if previo.get("serieMazar") and dias_previo <= 2:
            s = previo["serieMazar"][dias_previo:]
            base = s[0]
            serieM = [round(x / base, 4) for x in s] + [round(s[-1] / base, 4)] * dias_previo
            mod["serieMazar"] = serieM
            log(f"Se conserva el pronóstico de caudal anterior ({previo.get('serie_fecha')})")
    serieC_bruta = None
    try:
        serieC = serie_caudal_coca()
        serieC_bruta = list(serieC)
        log(f"Río Coca (GloFAS): ×{serieC[7]:.2f} en 7 días, ×{serieC[30]:.2f} en 30")
    except Exception as e:
        log(f"GloFAS Coca falló: {e}")
        serieC = None
        prev_b = previo.get("serieCocaBruta") or previo.get("serieCoca")
        if prev_b:
            serieC = list(prev_b); serieC_bruta = list(prev_b)
            log("Se conserva el pronóstico anterior del río Coca")
    if serieC_bruta:
        # Autoajuste interno del río Coca según los aciertos de GloFAS (no se muestra en las páginas)
        try:
            ac = ajuste_coca(hoy_d)
            a = ac["deriva_dia"]
            serieC = [x * math.exp(a * min(k, 7)) for k, x in enumerate(serieC_bruta)]
            mod["ajuste_coca"] = ac
            log(f"Autoajuste río Coca: {ac['nota']}")
        except Exception as e:
            log(f"Autoajuste río Coca: {e}")
            serieC = list(serieC_bruta)
        mod["serieCoca"] = [round(x, 4) for x in serieC]
        mod["serieCocaBruta"] = [round(x, 4) for x in serieC_bruta]
        # Con el caudal real: el pronóstico es del RÍO; lo que importa al sistema es lo que Coca Codo puede generar con
        # ese río (tope de 1.200 MW). Se convierte día a día y se expresa relativo a lo de las últimas 24 h.
        try:
            if RIO:
                ahora_l = datetime.fromisoformat(datos["fecha"])
                q24 = rio_prom(RIO, ahora_l); g24 = ccs_prom(RIO, ahora_l)
                base, info = coca_base(RIO, ahora_l)
                if q24 and g24 and g24 > 50 and base:
                    serieC_rio = list(serieC)
                    # día d: nivel esperado por la historia del río (base) × cambio que pronostica GloFAS (lluvia)
                    qd = [base[min(d, len(base)) - 1] if d >= 1 else q24 for d in range(len(serieC_rio))]
                    qd = [(base[-1] if d > len(base) else qd[d]) for d in range(len(serieC_rio))]
                    serieC = [1.0] + [round(ccs_mw_rio(qd[d] * serieC_rio[d]) / g24, 4) for d in range(1, len(serieC_rio))]
                    mod["serieCoca"] = serieC
                    mod["serieCocaRio"] = [round(x, 4) for x in serieC_rio]
                    mod["coca_rio"] = {"q24": round(q24, 1), "mw24": round(g24), "k": CCS_K, "e": CCS_E, "tope": CCS_CAP, **info,
                                       "mw_1d": round(ccs_mw_rio(qd[1] * serieC_rio[1])), "mw_3d": round(ccs_mw_rio(qd[3] * serieC_rio[3])),
                                       "mw_7d": round(ccs_mw_rio(qd[7] * serieC_rio[7]))}
                    log(f"Río Coca real: ahora {info['ahora']:.0f} m³/s, 72 h {info['q72']:.0f}, nivel normal (mediana 7 días) {info['mediana7']:.0f}" + (" (crecida súbita)" if info["crecida"] else "")
                        + f" → Coca Codo {g24:.0f} MW (24 h); día 1 {mod['coca_rio']['mw_1d']} MW, día 3 {mod['coca_rio']['mw_3d']} MW, "
                          f"día 7 {mod['coca_rio']['mw_7d']} MW")
        except Exception as e:
            log(f"Conversión río → generación de Coca Codo: {e}")
        guardar_coca(ahora.isoformat(timespec="minutes"), hoy.get("qCoca"), serieC_bruta)
    mod["serie_fecha"] = hoy_d.isoformat() if serieM is not None and fuentes.get("pronostico_caudal", {}).get("ok") else previo.get("serie_fecha")
    # Escenario automático = pronóstico calibrado (salvo que Claude haya fijado otro)
    hoy_txt = ahora.date().isoformat()
    if serieM and not manual_activo(manual, "wPaute", hoy_txt):
        hoy["wPaute"] = "auto"
    if serieC and not manual_activo(manual, "wCoca", hoy_txt):
        hoy["wCoca"] = "auto"
    datos["modelo"] = mod

    # Predicción del día con el mismo cálculo de la página
    P = {"qMazar": hoy["qMazar"], "qCoca": hoy["qCoca"], "wPaute": hoy["wPaute"], "wCoca": hoy["wCoca"],
         "demanda": hoy["dBase"] + 50 * (hoy["tCosta"] - 32), "cut": hoy["cut"], "imp": hoy["imp"],
         "therm": hoy["therm"], "other": hoy["other"]}
    ctx = {"cota": datos["cota"], "diaSemana0": mod["diaSemana0"], "amaluzaCota": mod["amaluzaCota"],
           "amaluzaRitmo": mod["amaluzaRitmo"], "deltaDia": mod["deltaDia"], "cutDias": mod["cutDias"],
           "cutPlan": mod.get("cutPlan"), "serieMazar": serieM, "serieCoca": serieC}
    aj = autoajuste(_leer_json(F_VER, []), hoy_d)
    mod["ajuste"] = aj["factor"]; mod["ajuste_info"] = aj
    ctx["ajuste"] = aj["factor"]
    log(f"Autoajuste por aciertos: {aj['nota']}")
    diarios, cruce = simular_py(P, ctx, par)
    # Memoria de las corridas de las últimas 48 h: cada corrida suma un ladrillo a la proyección
    numero_corridas = None
    try:
        zc_foto = zona_critica_py(diarios, cruce, datos["cota"])
        ts_mem = datetime.fromisoformat(datos["fecha"]).isoformat(timespec="minutes")
        mem, n_mem, numero_corridas = memoria_corridas(ts_mem, datos["cota"], diarios, par)
        mod["prediccion_foto"] = {"dias_critica": round(zc_foto["entrada"], 1) if zc_foto["entrada"] is not None else None,
                                  "cota_3d": round(diarios[3]["cota"], 2), "cota_5d": round(diarios[5]["cota"], 2)}
        if mem:
            ctx["memoria"] = mem
            mod["memoria"] = [round(x, 2) for x in mem]
            mod["memoria_info"] = {"corridas": n_mem, "horas": 48,
                                   "nota": f"promedio ponderado de las {n_mem} corridas de las últimas 48 h (antigüedad y acierto), cada una anclada a su cota"}
            diarios, cruce = simular_py(P, ctx, par)
            log(f"Memoria: {n_mem} corridas de las últimas 48 h; sin memoria la zona crítica sería en "
                f"{mod['prediccion_foto']['dias_critica']} días")
        else:
            log(f"Memoria: solo {n_mem} corridas en 48 h; todavía sin memoria")
    except Exception as e:
        log(f"Memoria de corridas: {e}")
        ctx.pop("memoria", None)
    rg = rango_py(diarios, mod.get("rango_cuantiles"), datos["cota"])
    d0 = diarios[0]
    ritmo = (d0["qturb"] - d0["qin"]) * 0.0864 / (par["curva_mazar"]["a"] + par["curva_mazar"]["b"] * (datos["cota"] - 2115))
    # Días hasta la zona de racionamiento (2.120 m)
    tz = 0.0 if datos["cota"] <= 2120 else None
    for k in range(1, len(diarios)):
        if tz is not None:
            break
        a_, b_ = diarios[k - 1], diarios[k]
        if b_["cota"] <= 2120:
            tz = a_["t"] + (a_["cota"] - 2120) / max(1e-6, a_["cota"] - b_["cota"])
    rgz = rango_py(diarios, mod.get("rango_cuantiles"), datos["cota"], 2120)
    mod["prediccion"] = {"dias_zona_2120": round(tz, 1) if tz is not None else None,
                         "rango_zona_2120": [(round(x, 1) if x is not None else None) for x in rgz] if rgz else None,
                         "dias": round(cruce, 1) if cruce is not None else None,
                         "rango": [(round(x, 1) if x is not None else None) for x in rg] if rg else None,
                         "ritmo_hoy_m_dia": round(-ritmo, 2)}
    # Zona crítica (2.116 m): número principal de las páginas; la parada (2.115 m) es "dias"
    zc = zona_critica_py(diarios, cruce, datos["cota"])
    rgc = rango_py(diarios, mod.get("rango_cuantiles"), datos["cota"], 2116)
    r1 = lambda v: round(v, 1) if v is not None else None
    if numero_corridas:
        mod["prediccion"]["numero"] = numero_corridas
        log(f"Número grande (promedio ponderado de {numero_corridas['corridas']} corridas): zona crítica "
            f"{numero_corridas['critica']['dias']} días {numero_corridas['critica']['rango']}, parada {numero_corridas['parada']['dias']} días")
    mod["prediccion"].update({"dias_critica": r1(zc["entrada"]),
                              "rango_critica": [r1(x) for x in rgc] if rgc else None,
                              "salida_critica": r1(zc["salida"]),
                              "parada_en_ventana": zc["parada_en_ventana"],
                              "minimo_critica": zc["minimo"]})
    # Probabilidades (con la lluvia pronosticada y si la semana fuera seca), para dos umbrales
    probs = {}
    ctx_seco = dict(ctx, serieMazar=mod.get("serieMazarSeca") or serieM)
    di_seco, _ = simular_py(P, ctx_seco, par)
    for nombre, di in (("pronostico", diarios), ("semana_seca", di_seco)):
        probs[nombre] = {str(u): probabilidades_py(di, mod.get("ratios_percentiles"), datos["cota"], u) for u in (2120, 2116, 2115)}
    mod["probabilidades"] = probs
    log(f"Probabilidad de llegar a 2.115 en 7/14/30 días: con lluvia {probs['pronostico']['2115']}, semana seca {probs['semana_seca']['2115']}")
    log(f"Zona crítica (2.116): {zc['entrada']}; ventana hasta {zc['salida']}; mínimo {zc['minimo']}")
    log(f"Modelo: {('%.1f días' % cruce) if cruce else 'más de 60 días'} hasta 2.115"
        + (f" (rango {rg[0]}–{rg[1]})" if rg else "") + f"; hoy {-ritmo:+.2f} m/día")
    # Registro de predicciones: una por corrida (cada 2 h), con la trayectoria de los próximos 14 días,
    # para comparar después lo que dijo con lo que pasó a la misma hora.
    try:
        os.makedirs("registro", exist_ok=True)
        reg = _leer_json(F_REG, [])
        hora = datetime.fromisoformat(datos["fecha"])
        ts = hora.isoformat(timespec="minutes")
        if not any(e.get("ts") == ts for e in reg):
            reg.append({"ts": ts, "fecha": hoy_d.isoformat(), "hora": hora.strftime("%H:%M"), "cota": datos["cota"],
                        "dias": mod["prediccion"]["dias"], "rango": mod["prediccion"]["rango"],
                        "dias_critica": mod["prediccion"].get("dias_critica"), "ajuste": aj["factor"],
                        "cota_pred": {str(h): round(diarios[h]["cota"], 2) for h in (1, 3, 7, 14)},
                        "traj": [round(diarios[h]["cota"], 2) for h in range(1, 41)]})
            limite = (hoy_d - timedelta(days=200)).isoformat()
            reg = sorted([e for e in reg if e["fecha"] >= limite], key=lambda e: e.get("ts") or e["fecha"])
            with open(F_REG, "w", encoding="utf-8") as fo:
                json.dump(reg, fo, ensure_ascii=False, indent=0)
            log("Predicción guardada en registro/predicciones.json")
    except Exception as e:
        log(f"Registro de predicciones: {e}")
    # Verificación: lo que el modelo dijo antes frente a la cota real a la misma hora
    try:
        ver, nuevas = verificar(datetime.fromisoformat(datos["fecha"]), datos["cota"])
        mod["aciertos"] = resumen_aciertos(ver)
        u = mod["aciertos"]["ultimo_1d"]
        log(f"Verificación: {nuevas} comparaciones nuevas; " + (f"última a 1 día: dijo {u['pred']} y fue {u['real']} "
            f"({u['err']:+.2f} m)" if u else "aún sin comparaciones a 1 día"))
    except Exception as e:
        log(f"Verificación: {e}")
    # Texto de control
    real7 = None
    hist = datos.get("historico", [])
    if len(hist) >= 8:
        real7 = (hist[-1][1] - hist[-8][1]) / 7
    c2 = lambda v: f"{v:.2f}".replace(".", ",")
    txt = (f"Con los valores de \"Hoy\", Paute debe aportar ≈ {d0['paute']:.0f} MW y para eso Mazar suelta "
           f"≈ {d0['qturb']:.0f} m³/s mientras le entran {d0['qin']:.0f}: hoy baja ≈ {c2(ritmo)} m/día.")
    if real7 is not None:
        txt += f" Promedio real de los últimos 7 días: {c2(-real7)} m/día"
        if mod.get("amaluzaVolumen") is not None and mod["amaluzaVolumen"] < 1:
            txt += (f", cuando Amaluza todavía aportaba agua; hoy Amaluza está en {mod['amaluzaCota']:.1f}".replace(".", ",") + " m, "
                    "su nivel mínimo, y ya no puede ayudar.")
        else:
            txt += "."
    notas["calibracion"] = txt

# ---------------------------------------------------------------- principal
def main():
    ahora = datetime.now(EC)
    with open("datos.json", encoding="utf-8") as f:
        datos = json.load(f)
    hoy = datos["hoy"]
    notas = datos.setdefault("notas", {})
    manual = datos.setdefault("manual", {"cut": hoy.get("cut", 300)})
    robot = datos.setdefault("robot", {})
    fuentes = robot.setdefault("fuentes", {})
    hoy_txt = ahora.date().isoformat()
    cambios = 0

    # --- Cortes (fijados por Claude a partir de las noticias)
    cut = manual.get("cut", hoy.get("cut", 300))
    hoy["cut"] = int(clamp(cut, 0, 700))

    # --- Celec: cota y caudal de entrada
    cota_t = cota_24 = q24 = t_cota = None
    try:
        cotas = celec_serie(MRID_COTA, ahora)
        t_cota, cota_t = cotas[-1]
        if not 2090 < cota_t < 2160:
            raise ValueError(f"cota fuera de rango: {cota_t}")
        cota_24 = valor_en(cotas, t_cota - timedelta(hours=24))
        caud = [v for tt, v in celec_serie(MRID_CAUDAL, ahora)
                if t_cota - timedelta(hours=24) < tt <= t_cota and 0 <= v < 2000]
        q24 = sum(caud) / len(caud) if len(caud) >= 12 else None
        fuentes["celec"] = {"ok": True, "lectura": t_cota.isoformat()}
        log(f"Celec: cota {cota_t:.2f} a las {t_cota:%H:%M}; hace 24 h {cota_24}; caudal 24 h {q24}")
    except Exception as e:
        fuentes["celec"] = {"ok": False, "error": str(e)[:200], "intento": ahora.isoformat(timespec='minutes')}
        log(f"Celec falló: {e}")

    if cota_t is not None and t_cota > datetime.fromisoformat(datos["fecha"]):
        cota = round(cota_t, 2)
        datos["cota"] = cota
        datos["fecha"] = t_cota.isoformat()
        datos["etiqueta"] = (f"datos al {DIAS[t_cota.weekday()]} {t_cota.day} {MESES[t_cota.month-1]} "
                             f"{t_cota.year}, {t_cota:%H:%M} (actualización automática)")
        dia = t_cota.date().isoformat()
        hist = [p for p in datos.get("historico", []) if p[0] != dia] + [[dia, cota]]
        datos["historico"] = sorted(hist)[-45:]
        cambios += 1
    if q24 is not None:
        hoy["qMazar"] = int(clamp(round(q24), 5, 120))
        notas["mazar"] = (f"Promedio de las últimas 24 h: {q24:.0f} m³/s (Celec Sur, automático). "
                          "Promedio histórico de octubre: 66 m³/s.")

    # --- Cenace: térmica, importación, demanda, Coca Codo
    D = None
    try:
        fecha_rt, puntos, mwh, perfil, fecha_perfil = cenace()
        energia = mwh.pop("_energia", {})
        if fecha_rt != ahora.date():
            raise ValueError(f"la página de Cenace muestra el {fecha_rt}, no hoy")
        try:
            with open(SERIE, encoding="utf-8") as f:
                serie = json.load(f)
        except FileNotFoundError:
            serie = {"puntos": {}, "plantas": {}}
        serie["puntos"].update(puntos)
        n_hoy = len(puntos)
        if n_hoy:
            serie["plantas"][fecha_rt.isoformat()] = {"horas": n_hoy / 2.0, **mwh}
        corte = (ahora - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        serie["puntos"] = {k: v for k, v in sorted(serie["puntos"].items()) if k >= corte}
        serie["plantas"] = {k: v for k, v in sorted(serie["plantas"].items())
                            if k >= (ahora - timedelta(days=3)).date().isoformat()}
        with open(SERIE, "w", encoding="utf-8") as f:
            json.dump(serie, f, ensure_ascii=False, separators=(",", ":"))

        claves = sorted(serie["puntos"])
        ultimo = datetime.fromisoformat(claves[-1])
        # Ventana de 24 h (48 medias horas). Las que no tienen dato propio guardado se completan con
        # la misma media hora del último día completo que publica Cenace.
        ventana, reales = [], 0
        for k in range(48):
            ts = ultimo - timedelta(minutes=30 * k)
            if ts.strftime("%Y-%m-%dT%H:%M") in serie["puntos"]:
                ventana.append(serie["puntos"][ts.strftime("%Y-%m-%dT%H:%M")])
                reales += 1
            elif ts.strftime("%H:%M") in perfil:
                ventana.append(perfil[ts.strftime("%H:%M")])
        if reales < 8 or len(ventana) < 40:
            raise ValueError(f"datos insuficientes ({reales} medias horas propias, {len(ventana)} en total)")
        prom = {c: sum(p[c] for p in ventana) / len(ventana) for c in "htirde"}
        D = prom["d"]
        hoy["therm"] = int(clamp(r10(prom["t"] + prom["r"]), 700, 1700))
        hoy["imp"] = int(clamp(round(prom["i"] / 5) * 5, 0, 450))

        # Coca Codo: energía del día / horas transcurridas (si hay menos de 4 h, se usa el día anterior)
        dias = sorted(serie["plantas"].items())
        base = next(((d, p) for d, p in reversed(dias) if p.get("horas", 0) >= 4 and "Coca Codo" in p), None)
        if base:
            ccs_mw = base[1]["Coca Codo"] / base[1]["horas"]
            hoy["qCoca"] = int(clamp(round(ccs_mw / 5), 80, 450))
            notas["coca"] = (f"Coca Codo generó en promedio {ccs_mw:.0f} MW ({base[0]}, Cenace, automático), "
                             f"equivalente a ~{hoy['qCoca']} m³/s en el modelo. Necesita 240–250 m³/s para 1.200 MW.")
        # Caudal REAL del río Coca (Celec, cada hora): reemplaza al equivalente por generación, que nunca pasa del tope
        global RIO
        try:
            RIO = coca_rio(ahora)
            q24, g24 = rio_prom(RIO, ahora), ccs_prom(RIO, ahora)
            ult = max(RIO) if RIO else None
            if q24 and g24:
                hoy["qCoca"] = int(clamp(round(g24 / 5), 80, 450))
                hu = datetime.strptime(ult, "%Y-%m-%dT%H")
                notas["coca"] = (f"Río Coca en Coca Codo Sinclair (Celec, cada hora): {q24:.0f} m³/s en promedio de 24 h; "
                                 f"a las {hu:%H}:00 iba en {RIO[ult]:.0f} m³/s. Con ese río Coca Codo puede generar ~{g24:.0f} MW "
                                 f"(tope continuo 1.200 MW desde ~250 m³/s)" + (f"; Cenace midió {ccs_mw:.0f} MW de promedio hoy." if base else ".")
                                 + f" En el modelo equivale a {hoy['qCoca']} m³/s.")
                fuentes["coca_rio"] = {"ok": True}
                log(f"Río Coca real (Celec): 24 h {q24:.0f} m³/s, último {RIO[ult]:.0f} ({ult}); Coca Codo ~{g24:.0f} MW")
        except Exception as e:
            fuentes["coca_rio"] = {"ok": False, "error": str(e)[:200]}
            log(f"Río Coca real (Celec): {e}")
        # Otras hidroeléctricas: hoy si ya hay 12 h de datos; si no, el último día completo de Cenace
        horas_hoy = len(puntos) / 2.0
        if "hoy" in energia and horas_hoy >= 12:
            otras, paute_real = otras_mw(energia["hoy"], horas_hoy); ref = f"hoy, {horas_hoy:.0f} h"
        elif "perfil" in energia:
            otras, paute_real = otras_mw(energia["perfil"], 24.0); ref = f"día completo {fecha_perfil}"
        else:
            otras = None
        if otras is not None:
            hoy["other"] = int(clamp(r10(otras), 500, 2200))
            notas["otras"] = (f"Generación medida de las demás hidroeléctricas: {otras:.0f} MW ({ref}, Cenace, automático). "
                              f"El complejo Paute generó {paute_real:.0f} MW en ese mismo periodo.")
            log(f"Otras hidro {otras:.0f} MW, Paute real {paute_real:.0f} MW ({ref})")
        notas["importacion"] = (f"Promedio de las últimas 24 h: {prom['i']:.0f} MW (Cenace, automático). "
                                "Límite de la interconexión: 450 MW.")
        notas["termica"] = (f"Promedio de las últimas 24 h: {prom['t']:.0f} MW térmicos + {prom['r']:.0f} MW "
                            "renovables no convencionales (Cenace, automático).")
        prestadas = len(ventana) - reales
        fuentes["cenace"] = {"ok": True, "ultimo_dato": claves[-1], "medias_horas_propias": reales,
                             "completadas_con_dia": fecha_perfil.isoformat() if (prestadas and fecha_perfil) else None}
        log(f"Cenace: demanda {D:.0f}, térmica {prom['t']:.0f}, importación {prom['i']:.0f}, "
            f"hidro {prom['h']:.0f} MW ({reales} medias horas propias, {prestadas} del perfil del {fecha_perfil})")
        cambios += 1
    except Exception as e:
        fuentes["cenace"] = {"ok": False, "error": str(e)[:200], "intento": ahora.isoformat(timespec='minutes')}
        log(f"Cenace falló: {e}")

    # --- Open-Meteo: temperatura y lluvia
    try:
        tmax, (pp, pf), (cp, cf), dia_t = pronostico(ahora)
        t_man = manual_activo(manual, "tCosta", hoy_txt)
        hoy["tCosta"] = float(t_man) if t_man is not None else clamp(round(tmax * 2) / 2, 28, 36)
        wp, wc = categoria(pp, pf), categoria(cp, cf)
        wp_m, wc_m = manual_activo(manual, "wPaute", hoy_txt), manual_activo(manual, "wCoca", hoy_txt)
        hoy["wPaute"] = wp_m or wp
        hoy["wCoca"] = wc_m or wc
        notas["temperatura"] = (f"Máxima prevista en Guayaquil para el {dia_t}: {tmax:.1f} °C (Open-Meteo, automático). "
                                "El modelo suma 50 MW por cada °C sobre 32 °C.")
        notas["lluviaPaute"] = (f"Cuenca del Paute: {pp:.0f} mm en los últimos 7 días y {pf:.0f} mm previstos en los "
                                f"próximos 7 (Open-Meteo) → {NOMBRE_CAT[hoy['wPaute']]}"
                                + (" (fijado por Claude)." if wp_m else ", automático."))
        notas["lluviaCoca"] = (f"Cuenca del Coca: {cp:.0f} mm en los últimos 7 días y {cf:.0f} mm previstos en los "
                               f"próximos 7 (Open-Meteo) → {NOMBRE_CAT[hoy['wCoca']]}"
                               + (" (fijado por Claude)." if wc_m else ", automático."))
        fuentes["openmeteo"] = {"ok": True}
        log(f"Open-Meteo: Guayaquil {tmax} °C; Paute {pp:.0f}/{pf:.0f} mm → {wp}; Coca {cp:.0f}/{cf:.0f} mm → {wc}")
    except Exception as e:
        fuentes["openmeteo"] = {"ok": False, "error": str(e)[:200], "intento": ahora.isoformat(timespec='minutes')}
        log(f"Open-Meteo falló: {e}")

    # --- Física de Paute: agua por MW y generación real de la última semana (Celec Sur)
    fis = None
    try:
        fis = fisica_paute(ahora.date())
        fisica = {k: v for k, v in fis.items()}
        fisica["actualizado"] = ahora.isoformat(timespec="minutes")
        datos["fisica"] = fisica
        fuentes["celec_energia"] = {"ok": True}
        log(f"Física Paute: {fis['k_mw_por_m3s']} MW por m³/s ({fis['dias_k']} días), "
            f"Paute promedio {fis['paute_prom_mw']} MW ({fis['dias_p']} días)")
    except Exception as e:
        fuentes["celec_energia"] = {"ok": False, "error": str(e)[:200], "intento": ahora.isoformat(timespec='minutes')}
        log(f"Física Paute falló: {e}")
        # Si Celec Sur no responde, se usa la física de la última lectura buena (hasta 3 días), para que una
        # caída momentánea de la fuente no cambie de golpe la demanda ni la predicción.
        prev = datos.get("fisica") or {}
        try:
            edad = (ahora.date() - datetime.fromisoformat(prev["actualizado"]).date()).days
        except Exception:
            edad = 99
        if prev.get("paute_prom_mw") and prev.get("detalle") and edad <= 3:
            fis = prev
            log(f"Se usa la física de Paute de la última lectura buena ({prev.get('actualizado')})")
    k = (datos.get("fisica") or {}).get("k_mw_por_m3s", 9.0)

    # --- Demanda: equivalente a la última semana, para que un fin de semana no distorsione la proyección.
    #     Con lo medido hoy (Coca Codo, otras hidro, térmica, Colombia), Paute debe generar lo mismo que
    #     su promedio real de los últimos 7 días.
    if fis is not None:
        ccs0 = min(5 * hoy["qCoca"], 1200)
        # Coca Codo de los MISMOS días en que se midió Paute (con los mismos pesos): así, si hoy el Coca trae más
        # agua que esos días, Paute debe generar menos desde ya (y no se esconde en una demanda más alta).
        ccs_ref = ccs0
        try:
            if RIO and all("peso" in x for x in fis["detalle"]):
                pares = []
                for x in fis["detalle"]:
                    fin_d = datetime.strptime(x["dia"], "%Y-%m-%d").replace(tzinfo=EC) + timedelta(days=1)
                    g = ccs_prom(RIO, fin_d)
                    if g is not None:
                        pares.append((g, x["peso"]))
                if len(pares) >= 0.7 * len(fis["detalle"]):
                    ccs_ref = sum(g * w for g, w in pares) / sum(w for _, w in pares)
                    log(f"Coca Codo en los días de Paute: {ccs_ref:.0f} MW (hoy {ccs0:.0f} MW)")
        except Exception as e:
            log(f"Coca Codo de referencia: {e}")
        robot["ccs_referencia_mw"] = round(ccs_ref)
        dem = fis["paute_prom_mw"] + ccs_ref + hoy["other"] + hoy["therm"] + hoy["imp"]
        # Los cortes que de verdad hubo en la semana medida (no el valor de hoy repetido 7 días):
        # así un día sin cortes en cut_dias no suma dos veces un ahorro que no ocurrió.
        if all("peso" in x for x in fis["detalle"]):
            dias_sem = [x["dia"] for x in fis["detalle"]]
            cut_sem = corte_promedio(manual, hoy["cut"], dias_sem, [x["peso"] for x in fis["detalle"]])
        else:
            dias_sem = [x["dia"] for x in fis["detalle"][-fis["dias_p"]:]]
            cut_sem = corte_promedio(manual, hoy["cut"], dias_sem)
        robot["cortes_semana_medida"] = {"desde": dias_sem[0], "hasta": dias_sem[-1], "mw_promedio": round(cut_sem)}
        log(f"Cortes en la semana medida ({dias_sem[0]} a {dias_sem[-1]}): {cut_sem:.0f} MW en promedio")
        hoy["dBase"] = int(clamp(r10(dem + cut_sem - 50 * (hoy["tCosta"] - 32)), 3500, 5200))
        notas["demanda"] = (f"Equivale a los últimos días: Paute generó {fis['paute_prom_mw']} MW en promedio ponderado del "
                            f"{dias_sem[0]} al {fis['hasta']} (Celec Sur; los días recientes pesan más, cada día vale la mitad cada 3 días), con "
                            f"~{cut_sem:.0f} MW medios de cortes a empresas."
                            + (f" Demanda atendida en las últimas 24 h: {D:.0f} MW (Cenace)." if D is not None else ""))
    elif D is not None:
        hoy["dBase"] = int(clamp(r10(D + corte_del_dia(manual, hoy["cut"], ahora.date())
                                     - 50 * (hoy["tCosta"] - 32)), 3500, 5200))
        notas["demanda"] = (f"Demanda atendida en las últimas 24 h: {D:.0f} MW medios (Cenace). Sin cortes ni calor "
                            f"extra sería ~{hoy['dBase']} MW.")

    # --- Modelo calibrado: pronóstico de caudales, Amaluza, día de la semana, predicción y registro
    try:
        bloque_modelo(datos, hoy, ahora, fis, notas, fuentes)
    except Exception as e:
        log(f"Modelo calibrado falló: {e}")

    if manual.get("nota_cortes"):
        notas["cortes"] = manual["nota_cortes"]

    robot["ultima_ejecucion"] = ahora.isoformat(timespec="minutes")
    robot["ultima_lectura"] = datos["fecha"]
    robot["caudal_entrada_24h"] = round(q24) if q24 is not None else None
    robot["variacion_cota_24h"] = round(cota_t - cota_24, 2) if (cota_t and cota_24) else None
    robot["registro"] = LOG[-8:]

    with open("datos.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # Pestañas Hidroeléctricas, Térmicas, Otras fuentes y Clima (no tocan el modelo; si fallan, no pasa nada)
    try:
        import generacion
        generacion.actualizar(ahora, get, CENACE)
    except Exception as e:
        print(f"Pestañas de generación y clima: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
