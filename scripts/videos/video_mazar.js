// DataLab Ec · video diario "Mazar en 3D" (Luis, 15 nov): el embalse en el relieve real del cañón del Paute, su nivel
// día a día (30 días) y "¿por qué se movió?" con los datos del simulador. Cámara con giro leve (~23°), presa a la vista.
// Uso: node video_mazar.js <carpeta_salida> [--cuadros]   (desde la raíz del repo o con RAIZ=<raíz>)
const { chromium } = require(process.env.PLAYWRIGHT || "playwright");
const { execFileSync } = require("child_process"); const fs = require("fs"); const path = require("path");
const RAIZ = process.env.RAIZ || path.resolve(__dirname, "../.."), DIR = path.join(__dirname, "mazar");
const OUT = process.argv[2] || "salida_videos", CUADROS = process.argv.includes("--cuadros");
const FPS = 24, suave = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
const ARCH = { "mazar.html": path.join(DIR, "mazar.html"), "relieve.json": path.join(DIR, "relieve.json"),
               "datos.json": path.join(RAIZ, "datos.json"), "serie_cenace.json": path.join(RAIZ, "serie_cenace.json"),
               "celec_2010_2022.json": path.join(RAIZ, "historial", "celec_2010_2022.json"), "celec_diario.json": path.join(RAIZ, "historial", "celec_diario.json") };
(async () => {
  fs.mkdirSync(OUT, { recursive: true }); const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "vmz-"));
  const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const p = await (await b.newContext({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 2 })).newPage();
  p.on("pageerror", e => console.error("página:", e.message));
  await p.route("http://mazar.local/**", r => { const f = ARCH[new URL(r.request().url()).pathname.slice(1)];
    return f && fs.existsSync(f) ? r.fulfill({ body: fs.readFileSync(f), contentType: f.endsWith(".html") ? "text/html" : "application/json" }) : r.fulfill({ status: 404 }); });
  await p.goto("http://mazar.local/mazar.html", { timeout: 120000 });
  await p.evaluate(() => window.listo);
  const hoy = await p.evaluate(() => D.hoy), n30 = await p.evaluate(() => D.hist.length - 1);
  const plan = [];
  for (let i = 0; i < FPS * 3; i++) plan.push(["inicio", n30, 0.2 * suave(i / (FPS * 3))]);                     // hoy
  for (let i = 0; i < FPS * 11; i++) { const t = i / (FPS * 11); plan.push(["historia", n30 * t, 0.2 + 0.6 * suave(t)]); }   // 30 días
  for (let i = 0; i < FPS * 1; i++) plan.push(["historia", n30, 0.8]);
  for (let i = 0; i < FPS * 7; i++) plan.push(["ayer", n30, 0.8 + 0.2 * suave(i / (FPS * 7))]);                // ¿por qué?
  const sel = CUADROS ? [0, FPS * 3 + Math.round(FPS * 11 * 0.12), plan.length - 1] : plan.map((_, i) => i);
  let n = 0;
  for (const i of sel) {
    await p.evaluate(([f, d, g]) => window.fijar(f, d, g), plan[i]);
    await p.screenshot({ path: CUADROS ? path.join(OUT, `mazar_cuadro${n++}.png`) : path.join(tmp, `c${String(n++).padStart(4, "0")}.jpg`),
                         ...(CUADROS ? {} : { type: "jpeg", quality: 92 }) });
  }
  await b.close();
  if (CUADROS) return console.log("cuadros:", n);
  const f = path.join(OUT, `mazar_${process.env.DIA || hoy}.mp4`)   // con el mismo DÍA (ayer) que los otros 2 videos, parcial = f.replace(/\.mp4$/, ".tmp.mp4");
  execFileSync("ffmpeg", ["-v", "error", "-y", "-framerate", String(FPS), "-i", path.join(tmp, "c%04d.jpg"), "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
    "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", parcial]);
  fs.renameSync(parcial, f); fs.rmSync(tmp, { recursive: true, force: true });
  console.log("video Mazar:", f, n, "cuadros");
})().catch(e => { console.error(e); process.exit(1); });
