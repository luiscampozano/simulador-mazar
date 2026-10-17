"""Robot del simulador Mazar (GitHub Actions, cada 2 horas).

Actualiza datos.json con datos que se publican en formato legible por máquina:
  - Celec Sur (servicio de datos del panel): cota de Mazar y caudal de entrada.
  - Cenace (página "Información Operativa"): generación térmica, importación,
    demanda nacional y energía de Coca Codo Sinclair, cada media hora.
  - Open-Meteo: temperatura máxima en Guayaquil y lluvia prevista en las
    cuencas del Paute y del Coca.
Con esos datos recalibra "otras hidroeléctricas" para que el modelo reproduzca
la variación real de la cota en las últimas 24 horas.

Lo que no se publica como dato (los cortes a empresas) lo fija Claude en el
bloque "manual" de datos.json. El robot respeta siempre ese bloque.
Si una fuente falla, el robot conserva el valor anterior de lo que depende de
ella y sigue con el resto.
"""
import base64, html as htmllib, json, math, re, ssl, struct, sys, urllib.request
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
    puntos = {f"{fecha.isoformat()}T{hh}": f for hh, f in hoy_filas.items()}
    return fecha, puntos, mwh, perfil, fecha_perfil


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

    # --- Demanda base: lo que se sirvió + lo que se dejó de servir por cortes − efecto del calor
    if D is not None:
        hoy["dBase"] = int(clamp(r10(D + hoy["cut"] - 50 * (hoy["tCosta"] - 32)), 3500, 5200))
        notas["demanda"] = (f"Demanda atendida en las últimas 24 h: {D:.0f} MW medios (Cenace). Sin cortes ni calor "
                            f"extra sería ~{hoy['dBase']} MW. Récord instantáneo de 2026: 5.634 MW.")

    # --- Calibración: "otras hidroeléctricas" de modo que el modelo reproduzca la variación de 24 h
    if cota_t is not None and cota_24 is not None and q24 is not None and D is not None:
        caida = cota_24 - cota_t
        x = cota_t - 2115
        A = 3.758 + 0.2177 * x
        neto = caida * A * 1e6 / 86400
        paute = clamp(9 * (q24 + neto), 0, 1757)
        demanda = hoy["dBase"] + 50 * (hoy["tCosta"] - 32) - hoy["cut"]
        ccs = min(5 * hoy["qCoca"], 1200)
        otras = demanda - ccs - hoy["therm"] - hoy["imp"] - paute
        ajustado = int(clamp(r10(otras), 500, 2200))
        hoy["other"] = ajustado
        verbo = "bajó" if caida >= 0 else "subió"
        notas["calibracion"] = (f"En las últimas 24 h Mazar {verbo} {abs(caida):.2f} m; con los valores de \"Hoy\" el "
                                f"modelo parte de ese mismo ritmo (Paute ≈ {paute:.0f} MW). Calibración automática.")
        if ajustado != r10(otras):
            notas["calibracion"] += f" Aviso: el ajuste pedía {otras:.0f} MW en otras hidro y se limitó a {ajustado}."
        notas["otras"] = (f"Calculado por el robot para cerrar el balance: {ajustado} MW "
                          "(Agoyán, San Francisco, Minas San Francisco, Delsitanisagua y menores).")
        log(f"Calibración: caída {caida:.2f} m/24 h, Paute {paute:.0f} MW, otras {otras:.0f} → {ajustado}")

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
