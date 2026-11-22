"""Capas abiertas de Segura EP (Gerencia de Gestión de Riesgos, Guayaquil) publicadas en ArcGIS Online (acceso público).

Guarda en datos/segura_ep/:
  · eventos.geojson          – eventos de inundación (puntos con fecha, causa, parroquia)
  · zonas_observadas.geojson – zonas inundables cuya fuente NO es el mapa de susceptibilidad modelado
                               (Plan Maestro 2004, Plan Choche 2023, ESPOL, drones, talleres, Sala Situacional, El Niño 2026-2027)
  · resumen.json             – conteo por fuente, fecha de última edición y lo NUEVO desde la corrida anterior
El mapa de susceptibilidad EMAPAG-Interagua (~5.000 polígonos, ~66 MB) no se copia: solo se cuenta.
Crédito: Segura EP – Gerencia de Gestión de Riesgos.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://services1.arcgis.com/ESOnuLz5X3I3J4At/arcgis/rest/services"
ZONAS = BASE + "/Zonas_Inundables_TR10/FeatureServer/3"
EVENTOS = BASE + "/Eventos_de_Inundaciones/FeatureServer/4"
SALIDA = os.path.join(os.path.dirname(__file__), "..", "datos", "segura_ep")
EC = timezone(timedelta(hours=-5))


def pedir(url, params, intentos=4):
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "DataLabEc/1.0"}), timeout=90) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:
            if i == intentos - 1:
                raise
            print("reintento", i + 1, e, file=sys.stderr); time.sleep(10 * (i + 1))


def todo(url, where, campos, simplificar=None):
    feats, off = [], 0
    while True:
        p = {"where": where, "outFields": campos, "outSR": 4326, "f": "geojson", "resultOffset": off,
             "resultRecordCount": 1000, "orderByFields": "OBJECTID", "geometryPrecision": 6}
        if simplificar:
            p["maxAllowableOffset"] = simplificar
        d = pedir(url + "/query", p)
        feats += d.get("features", [])
        if not d.get("properties", {}).get("exceededTransferLimit") and len(d.get("features", [])) < 1000:
            break
        off += 1000
    return feats


def leer(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def main():
    os.makedirs(SALIDA, exist_ok=True)
    ant = leer(os.path.join(SALIDA, "resumen.json"), {}) or {}
    ids_ev_ant = set(ant.get("ids_eventos", []))
    ids_zo_ant = set(ant.get("ids_zonas", []))

    meta_z = pedir(ZONAS, {"f": "json"}); meta_e = pedir(EVENTOS, {"f": "json"})
    conteo = pedir(ZONAS + "/query", {"where": "1=1", "groupByFieldsForStatistics": "Fuente", "f": "json",
                   "outStatistics": json.dumps([{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}])})
    por_fuente = {(f["attributes"]["Fuente"] or "(sin fuente)").strip(): f["attributes"]["n"] for f in conteo["features"]}

    zonas = todo(ZONAS, "Fuente NOT LIKE '%Susceptibilidad%'", "OBJECTID,Descripción,Fuente,Area_m2", simplificar=0.00003)
    eventos = todo(EVENTOS, "1=1", "OBJECTID,FECHA,AÑO,MES,AGA,PARROQUIA,TIPODEV,CAUSA,DIRECCION")
    for f in eventos:   # fecha legible (Ecuador); dirección solo hasta el sector (sin manzana/solar de viviendas)
        d = f["properties"].get("DIRECCION")
        if isinstance(d, str):
            f["properties"]["DIRECCION"] = re.split(r"\b(?:MZ|MZA|MANZANA|SOLAR|SL|VILLA)\b\.?", d, maxsplit=1, flags=re.I)[0].strip(" ,.-;") or None
        x = f["properties"].get("FECHA")
        if isinstance(x, (int, float)):
            f["properties"]["FECHA"] = datetime.fromtimestamp(x / 1000, timezone.utc).astimezone(EC).strftime("%Y-%m-%d")
    if len(eventos) < 100 or len(zonas) < 50:
        sys.exit(f"respuesta sospechosa ({len(eventos)} eventos, {len(zonas)} zonas): no se pisa lo guardado")

    for nom, fs in (("eventos.geojson", eventos), ("zonas_observadas.geojson", zonas)):
        json.dump({"type": "FeatureCollection", "fuente": "Segura EP – Gerencia de Gestión de Riesgos (ArcGIS Online, público)",
                   "features": fs}, open(os.path.join(SALIDA, nom), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    ids_ev = sorted(f["properties"]["OBJECTID"] for f in eventos)
    ids_zo = sorted(f["properties"]["OBJECTID"] for f in zonas)
    nuevos_ev = [f["properties"] | {"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
                 for f in eventos if ant and f["properties"]["OBJECTID"] not in ids_ev_ant and f.get("geometry")]
    nuevas_zo = [f["properties"] for f in zonas if ant and f["properties"]["OBJECTID"] not in ids_zo_ant]
    recarga = len(nuevos_ev) > 50 or len(nuevas_zo) > 50   # la capa se recargó y cambió los OBJECTID: no listar todo
    if recarga:
        nuevos_ev, nuevas_zo = [], []
    ms = lambda m: datetime.fromtimestamp(m / 1000, timezone.utc).astimezone(EC).isoformat(timespec="minutes") if m else None
    res = {
        "actualizado": datetime.now(EC).isoformat(timespec="minutes"),
        "fuente": "Segura EP – Gerencia de Gestión de Riesgos (Guayaquil), capas públicas en ArcGIS Online",
        "servicios": {"zonas": ZONAS, "eventos": EVENTOS},
        "ultima_edicion": {"zonas": ms(meta_z.get("editingInfo", {}).get("lastEditDate")),
                           "eventos": ms(meta_e.get("editingInfo", {}).get("lastEditDate"))},
        "zonas_por_fuente": por_fuente,
        "n_eventos": len(eventos), "n_zonas_observadas_guardadas": len(zonas),
        "eventos_por_anio": {},
        "nuevos_eventos": nuevos_ev, "nuevas_zonas": nuevas_zo,
        "primera_corrida": not ant, "recarga_de_capa": recarga,
        "ids_eventos": ids_ev, "ids_zonas": ids_zo,
    }
    for f in eventos:
        a = str(f["properties"].get("AÑO") or "?"); res["eventos_por_anio"][a] = res["eventos_por_anio"].get(a, 0) + 1
    json.dump(res, open(os.path.join(SALIDA, "resumen.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(eventos)} eventos ({len(nuevos_ev)} nuevos), {len(zonas)} zonas observadas ({len(nuevas_zo)} nuevas)")


if __name__ == "__main__":
    main()
