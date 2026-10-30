"""Revisor Gemini: le envía a Gemini (API) el manual de contexto, el código del laboratorio, el cambio propuesto y los
marcadores, y deja su veredicto como comentario en el commit. Uso en GitHub Actions (secreto GEMINI_API_KEY):
  python revisor_gemini.py --manual laboratorio/GEMINI.md --base origin/main --archivos a.py b.json ...
  python revisor_gemini.py --prueba      (solo comprueba que la llave y el modelo funcionan)
Modelos: primero gemini-4-argon; si falla, gemini-3.8-flash."""
import argparse, json, os, subprocess, sys, urllib.request, urllib.error

MODELOS = ["gemini-4-argon", "gemini-3.8-flash"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
MAX_CHARS = 120000   # tope de contexto por revisión (controla el costo)


def preguntar(texto):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Falta el secreto GEMINI_API_KEY")
    cuerpo = json.dumps({"contents": [{"role": "user", "parts": [{"text": texto}]}],
                         "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2500}}).encode()
    ultimo = None
    for m in MODELOS:
        req = urllib.request.Request(URL.format(m=m), data=cuerpo,
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            partes = d["candidates"][0]["content"]["parts"]
            uso = d.get("usageMetadata", {})
            return m, "".join(p.get("text", "") for p in partes), uso
        except urllib.error.HTTPError as e:
            ultimo = f"{m}: HTTP {e.code} {e.read()[:300]!r}"
        except Exception as e:
            ultimo = f"{m}: {e}"
        print("Falló", ultimo, file=sys.stderr)
    sys.exit("Ningún modelo respondió: " + str(ultimo))


def leer(p, n=40000):
    try:
        with open(p, encoding="utf-8") as f:
            t = f.read()
        return t if len(t) <= n else t[:n] + f"\n…(recortado, {len(t)} caracteres)"
    except Exception as e:
        return f"(no se pudo leer {p}: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual"); ap.add_argument("--base", default="origin/main")
    ap.add_argument("--archivos", nargs="*", default=[]); ap.add_argument("--prueba", action="store_true")
    ap.add_argument("--salida", default="revision_gemini.md")
    a = ap.parse_args()
    if a.prueba:
        m, t, uso = preguntar("Responde solo: 'Revisor Gemini de DataLab Ec listo.'")
        print(f"Modelo: {m}\nRespuesta: {t.strip()}\nUso: {uso}")
        return
    diff = subprocess.run(["git", "diff", a.base, "HEAD"], capture_output=True, text=True).stdout
    log = subprocess.run(["git", "log", "--format=%h %s%n%b", f"{a.base}..HEAD"], capture_output=True, text=True).stdout
    partes = [leer(a.manual, 30000), "\n\n# Commits del candidato\n" + log, "\n\n# Cambio propuesto (git diff)\n```diff\n" + diff[:40000] + "\n```"]
    for p in a.archivos:
        partes.append(f"\n\n# Archivo: {p}\n```\n{leer(p, 30000)}\n```")
    partes.append("\n\nRevisa el cambio propuesto según el manual. Empieza con la línea de VEREDICTO.")
    texto = "".join(partes)[:MAX_CHARS]
    m, t, uso = preguntar(texto)
    sal = f"**Revisor Gemini** (`{m}`)\n\n{t.strip()}\n\n<sub>tokens: entrada {uso.get('promptTokenCount')}, salida {uso.get('candidatesTokenCount')}</sub>\n"
    with open(a.salida, "w", encoding="utf-8") as f:
        f.write(sal)
    print(sal)


if __name__ == "__main__":
    main()
