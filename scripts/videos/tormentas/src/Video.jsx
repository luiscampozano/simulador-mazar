import { AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import D from "./datos.json";

// DataLab Ec · video diario de las tormentas del día (Luis, 15 nov). Datos: scripts/videos/cuadros.py → src/datos.json
const F = "Inter, 'DejaVu Sans', sans-serif", MONO = "'JetBrains Mono', 'DejaVu Sans Mono', monospace";
const C = { noche: "#06090d", texto: "#eef3f7", suave: "#9aa9b5", acento: "#7cc4ff", rosa: "#ff4f7a", oro: "#ffd36b" };
const T_TIT = 90, POR_CUADRO = 7, T_MAPA = Math.max(1, D.cuadros.length) * POR_CUADRO, T_FIN = 210;
export const DURACION = T_TIT + T_MAPA + T_FIN;
const MAPA_Y = 300;
const IZQ = { Daule: 1 }, ABAJO = { Milagro: 26, Guayaquil: 30 };
const SEM = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"], MES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fd = new Date(D.dia + "T12:00:00"), FECHA = `${SEM[fd.getDay()]} ${fd.getDate()} de ${MES[fd.getMonth()]}`;
const FECHA_T = FECHA[0].toUpperCase() + FECHA.slice(1);
const aparece = (f, ini = 0, dur = 12) => interpolate(f, [ini, ini + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
const min = h => { const [a, b] = h.split(":").map(Number); return a * 60 + b; };

const Mapa = () => {
  const f = useCurrentFrame();
  const k = Math.min(D.cuadros.length - 1, Math.floor(f / POR_CUADRO));
  const hora = D.cuadros[k], m = min(hora);
  const activas = D.tormentas.map(s => ({ ...s, q: s.p.find(p => p[2] === hora) })).filter(s => s.q);
  const sg = D.tormentas.find(s => s.id === D.grande);
  const traza = sg ? sg.p.filter(p => min(p[2]) <= m) : [];
  const nota = [...D.notas].reverse().find(([h]) => min(h) <= m);
  const fNota = nota ? (m - min(nota[0])) / 10 * POR_CUADRO + (f % POR_CUADRO) : 0;
  return <AbsoluteFill style={{ background: C.noche }}>
    <Img src={staticFile(`cuadros/${hora.replace(":", "")}.jpg`)} style={{ position: "absolute", top: MAPA_Y, left: 0, width: 1080 }} />
    <svg width={1080} height={D.H} style={{ position: "absolute", top: MAPA_Y, left: 0 }}>
      {traza.length > 1 && <polyline points={traza.map(p => `${p[0]},${p[1]}`).join(" ")} fill="none" stroke={C.rosa} strokeWidth={6} strokeLinecap="round" strokeDasharray="2 12" opacity={0.95} />}
      {Object.entries(D.ciudades).map(([n, [x, y]]) => <g key={n}><circle cx={x} cy={y} r={7} fill={C.oro} stroke="#000" strokeWidth={2} />
        <text x={IZQ[n] ? x - 12 : x + 12} y={y + 8 + (ABAJO[n] || 0)} textAnchor={IZQ[n] ? "end" : "start"} fill="#fff" stroke="#000" strokeWidth={5} paintOrder="stroke" style={{ font: `600 25px ${F}` }}>{n}</text></g>)}
      {activas.map(s => { const g = s.id === D.grande, r = g ? 30 : s.fuerte ? 21 : 17;
        return <g key={s.id} opacity={g ? 1 : 0.92}>
          <circle cx={s.q[0]} cy={s.q[1]} r={r} fill={g ? C.rosa : "rgba(6,9,13,.82)"} stroke={g ? "#fff" : s.fuerte ? "#ff6b5e" : "#ffd36b"} strokeWidth={g ? 4 : 3} />
          <text x={s.q[0]} y={s.q[1] + (g ? 11 : 8)} textAnchor="middle" fill="#fff" style={{ font: `800 ${g ? 30 : String(s.id).length > 2 ? 17 : 21}px ${F}` }}>{s.id}</text></g>; })}
    </svg>
    <div style={{ position: "absolute", top: 70, left: 60, right: 60, display: "flex", justifyContent: "space-between", alignItems: "flex-end", fontFamily: F, color: C.texto }}>
      <div><div style={{ font: `800 26px ${F}`, letterSpacing: ".16em", color: C.acento }}>DATALAB EC · SATÉLITE GOES-19</div>
        <div style={{ font: `800 50px/1.05 ${F}`, marginTop: 10 }}>{FECHA_T}</div></div>
      <div style={{ textAlign: "right" }}><div style={{ font: `600 76px/1 ${MONO}`, fontVariantNumeric: "tabular-nums" }}>{hora}</div>
        <div style={{ font: `500 26px ${F}`, color: C.suave, marginTop: 8 }}>{activas.length} tormenta{activas.length === 1 ? "" : "s"} activa{activas.length === 1 ? "" : "s"}</div></div>
    </div>
    <div style={{ position: "absolute", top: MAPA_Y + D.H + 18, left: 60, right: 60, fontFamily: F }}>
      <div style={{ display: "flex", gap: 4 }}>{["#468aaa", "#3caac8", "#50c86e", "#f5d73c", "#ff8c28", "#f03232", "#c83cff"].map((c, i) => <div key={i} style={{ flex: 1, height: 14, background: c, borderRadius: 3 }} />)}</div>
      <div style={{ display: "flex", justifyContent: "space-between", color: C.suave, font: `500 22px ${F}`, marginTop: 6 }}><span>cima tibia</span><span>cima más fría = tormenta más fuerte</span></div>
    </div>
    {nota && <div style={{ position: "absolute", left: 50, right: 50, bottom: 110, background: "rgba(10,14,20,.92)", border: "1px solid rgba(170,190,210,.25)", borderLeft: `8px solid ${C.rosa}`, borderRadius: 16, padding: "24px 30px",
      opacity: aparece(fNota, 0, 8), transform: `translateY(${(1 - aparece(fNota, 0, 10)) * 30}px)`, fontFamily: F, color: C.texto }}>
      <div style={{ font: `600 30px ${MONO}`, color: C.rosa }}>{nota[0]}</div>
      <div style={{ font: `700 38px/1.25 ${F}`, marginTop: 8 }}>{nota[1]}</div>
    </div>}
    <div style={{ position: "absolute", bottom: 50, left: 0, right: 0, textAlign: "center", color: C.suave, font: `500 24px ${F}` }}>@DataLabEc{D.grande ? ` · en rosado, la tormenta más grande (#${D.grande})` : ""}</div>
  </AbsoluteFill>;
};

const Titulo = () => {
  const f = useCurrentFrame(), { fps } = useVideoConfig(), s = spring({ frame: f, fps, config: { damping: 200 } });
  const fondo = D.cuadros[Math.floor(D.cuadros.length * 0.6)] || D.cuadros[0];
  return <AbsoluteFill style={{ background: C.noche }}>
    {fondo && <Img src={staticFile(`cuadros/${fondo.replace(":", "")}.jpg`)} style={{ position: "absolute", top: MAPA_Y, width: 1080, opacity: 0.35, transform: `scale(${1.08 - 0.08 * s})` }} />}
    <div style={{ position: "absolute", left: 70, right: 70, top: 640, fontFamily: F, color: C.texto, opacity: s, transform: `translateY(${(1 - s) * 40}px)` }}>
      <div style={{ font: `800 30px ${F}`, letterSpacing: ".16em", color: C.acento }}>DATALAB EC</div>
      <div style={{ font: `800 100px/1.02 ${F}`, marginTop: 20 }}>Las tormentas del {FECHA}</div>
      <div style={{ font: `500 42px/1.3 ${F}`, color: C.suave, marginTop: 26 }}>vistas desde el satélite cada 10 minutos, de 06:00 a 24:00</div>
    </div>
  </AbsoluteFill>;
};

const Final = () => {
  const f = useCurrentFrame(), R = D.resumen;
  const n = Math.round(interpolate(f, [10, 60], [0, R.continente], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }));
  const fila = (t, i) => <div key={i} style={{ font: `500 36px/1.35 ${F}`, color: C.texto, opacity: aparece(f, 50 + i * 15, 15), transform: `translateX(${(1 - aparece(f, 50 + i * 15, 15)) * 30}px)` }}>{t}</div>;
  const lineas = [
    `⛈️ ${R.fuertes} llegaron a tormenta fuerte`,
    R.galapagos != null ? `🏝️ ${R.galapagos} más en la zona de Galápagos` : null,
    R.ciudades.length ? `🌧️ Pasaron sobre ${R.ciudades.slice(0, 6).join(", ")}${R.ciudades.length > 6 ? ` y ${R.ciudades.length - 6} más` : ""}` : "Ninguna pasó sobre nuestras ciudades",
    R.nucleos.length ? `📍 Donde más llovió (estimación): ${R.nucleos.map(([l, mm]) => `${l} ${mm} mm`).join(" · ")}` : null,
  ].filter(Boolean);
  return <AbsoluteFill style={{ background: C.noche, fontFamily: F, color: C.texto }}>
    <div style={{ position: "absolute", top: 260, left: 70, right: 70 }}>
      <div style={{ font: `800 30px ${F}`, letterSpacing: ".16em", color: C.acento }}>EL DÍA EN NÚMEROS</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 24, marginTop: 10 }}>
        <div style={{ font: `800 200px/1 ${F}`, color: C.oro, fontVariantNumeric: "tabular-nums" }}>{n}</div>
        <div style={{ font: `700 46px/1.15 ${F}` }}>tormentas en el continente{R.desde !== "00:00" ? <div style={{ font: `500 28px ${F}`, color: C.suave }}>contadas desde las {R.desde}</div> : null}</div></div>
      <div style={{ display: "grid", gap: 22, marginTop: 50 }}>{lineas.map(fila)}</div>
    </div>
    <div style={{ position: "absolute", bottom: 80, left: 0, right: 0, textAlign: "center", font: `800 46px ${F}`, color: C.texto, opacity: aparece(f, 110, 20) }}>@DataLabEc</div>
  </AbsoluteFill>;
};

export const Video = () => <AbsoluteFill style={{ background: C.noche }}>
  <Sequence durationInFrames={T_TIT}><Titulo /></Sequence>
  <Sequence from={T_TIT} durationInFrames={T_MAPA}><Mapa /></Sequence>
  <Sequence from={T_TIT + T_MAPA} durationInFrames={T_FIN}><Final /></Sequence>
</AbsoluteFill>;
