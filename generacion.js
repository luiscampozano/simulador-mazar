/* Pestañas "Hidroeléctricas", "Térmicas", "Otras fuentes y Colombia" y "Ríos y centrales".
   Mismo archivo en los dos simuladores; cada página pone su estilo con window.GEN_CFG y las variables --g-*.
   Solo leen registro/generacion.json (lo escribe el robot cada 2 h); no tocan el modelo ni el número grande. */
(function () {
  "use strict";
  const CFG = Object.assign({ url: "registro/generacion.json", nav: ".tabs", despues: "#tab-region",
    panel: "card", h2: "", lede: "lede", btn: "" }, window.GEN_CFG || {});
  const PL = ["Coca Codo", "Paute", "Sopladora", "Mazar", "San Francisco", "Agoyán", "Minas San Francisco", "Delsitanisagua"];
  const NOMBRE = { "Paute": "Molino (Paute)" };
  const MON = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const DOW = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  const f = (n, d = 0) => n == null || isNaN(n) ? "–" : Number(n).toLocaleString("es-EC", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const $ = id => document.getElementById(id);
  const fechaCorta = iso => { const d = new Date(iso + "T12:00:00"); return `${DOW[d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]}`; };
  const local = iso => new Date(iso.length <= 16 && !/[+-]\d\d:\d\d$/.test(iso) ? iso + ":00-05:00" : iso);
  let G = null, cargando = false, dia = null, ultimo = null;

  /* ---------- estilos comunes (los colores vienen de cada página) ---------- */
  const css = `.g-col{display:grid;gap:16px;min-width:0}.g-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.g-box{border:1px solid var(--g-line);border-radius:12px;padding:12px 14px;background:var(--g-soft);min-width:0;align-content:start}
.g-lbl{font-size:12px;color:var(--g-muted);line-height:1.3}.g-big{font-family:var(--g-display,inherit);font-weight:800;font-size:28px;line-height:1.15;font-variant-numeric:tabular-nums}
.g-big small{font-size:14px;font-weight:600;margin-left:3px}.g-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px}
.g-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--g-muted);align-items:center}.g-legend i{display:inline-block;width:16px;height:3px;vertical-align:middle;margin-right:6px;border-radius:2px}
.g-legend i.d{height:0;border-top:2px dashed var(--g-mod);background:none}.g-legend i.s{width:11px;height:11px;border-radius:3px}
.g-note{font-size:12px;color:var(--g-muted);line-height:1.45}.g-txt{font-size:14px;line-height:1.5;margin:0}
.g-h3{font-weight:700;font-size:16px;margin:0;line-height:1.3}.g-sub{font-size:12px;color:var(--g-muted);margin-top:2px}
.g-seg{display:inline-flex;flex-wrap:wrap;gap:4px;border:1px solid var(--g-line);border-radius:999px;padding:3px}
.g-seg button{border:0;border-radius:999px;padding:8px 14px;background:transparent;color:var(--g-ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer;min-height:40px}
.g-seg button[aria-pressed="true"]{background:var(--g-real);color:var(--g-on)}
.g-chart{min-width:0}.g-chart svg{width:100%;height:auto;display:block}.g-mono{font-family:var(--g-mono,ui-monospace,monospace);font-variant-numeric:tabular-nums}
.g-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:10px 16px}
.g-dif{font-size:13px;font-weight:600}.g-tbl{width:100%;border-collapse:collapse;font-size:13px}.g-tbl th,.g-tbl td{padding:6px 8px;border-bottom:1px solid var(--g-line);text-align:left;vertical-align:top}
.g-tbl th{color:var(--g-muted);font-weight:600;font-size:12px}.g-tbl td.n{text-align:right;font-family:var(--g-mono,ui-monospace,monospace);white-space:nowrap}
.g-scroll{overflow-x:auto}.g-dia{display:grid;gap:4px;padding-top:8px;border-top:1px solid var(--g-line)}.g-dia:first-of-type{border-top:0;padding-top:0}
.g-per{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:13px}.g-per span:nth-child(odd){color:var(--g-muted)}
.g-ok{color:var(--g-ok)}.g-ko{color:var(--g-crit)}
.g-est{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}.g-est i{width:8px;height:8px;border-radius:50%;background:currentColor}
.g-est.ok{color:var(--g-ok);background:color-mix(in srgb,var(--g-ok) 14%,transparent)}.g-est.med{color:var(--g-warn);background:color-mix(in srgb,var(--g-warn) 14%,transparent)}.g-est.mal{color:var(--g-crit);background:color-mix(in srgb,var(--g-crit) 14%,transparent)}
.g-fila{display:flex;justify-content:space-between;gap:8px;font-size:13px;color:var(--g-muted);margin-top:4px}.g-fila b{color:var(--g-ink);font-family:var(--g-mono,ui-monospace,monospace);font-variant-numeric:tabular-nums}
.g-bar{height:6px;border-radius:4px;background:var(--g-line);overflow:hidden}.g-bar i{display:block;height:100%;border-radius:4px}
.g-alerta{border:1px solid color-mix(in srgb,var(--g-crit) 45%,transparent);background:color-mix(in srgb,var(--g-crit) 10%,transparent);border-radius:12px;padding:10px 12px;font-size:13.5px;line-height:1.45}
.g-riesgo{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px}.g-riesgo>div{border:1px solid var(--g-line);border-radius:10px;padding:8px;text-align:center;font-size:12px;color:var(--g-muted);display:grid;gap:3px;justify-items:center}.g-riesgo b{color:var(--g-ink);font-size:14px}
.g-dos{display:grid;gap:12px;grid-template-columns:1fr}@media(min-width:900px){.g-dos{grid-template-columns:3fr 2fr}}`;

  /* ---------- pestañas y paneles ---------- */
  const TABS = [["hidro", "Hidroeléctricas"], ["term", "Térmicas"], ["otras", "Otras fuentes y Colombia"], ["rios", "Ríos y centrales"]];
  const leyenda = (real, txtReal) => `<div class="g-legend"><span><i style="background:${real};height:4px"></i>${txtReal}</span><span><i class="d"></i>lo que usó el modelo</span></div>`;
  const PANEL = {
    hidro: () => `<div class="g-head"><div style="display:grid;gap:6px;max-width:70ch"><h2 class="${CFG.h2}">Generación hidroeléctrica</h2>
      <p class="${CFG.lede}">Cuánto genera cada central durante el día. La línea gruesa es lo que generó de verdad (Cenace); la punteada, lo que el modelo suponía en cada corrida. Así se ve dónde acierta y dónde no.</p></div>
      <div class="g-seg" role="group" aria-label="Día" id="g-dias"></div></div>
      ${leyenda("var(--g-real)", "real (Cenace)")}
      <div class="g-col" id="g-hidro-grupos"></div>
      <div style="display:grid;gap:4px"><h3 class="g-h3">Cada central por separado</h3><p class="g-note">El modelo no las proyecta una por una, así que aquí se ve solo lo real: promedio del día en MW y energía en MWh.</p></div>
      <div class="g-grid" id="g-hidro-centrales"></div>
      <p class="g-note" id="g-hidro-nota"></p>`,
    term: () => `<div style="display:grid;gap:6px;max-width:70ch"><h2 class="${CFG.h2}">Generación térmica</h2>
      <p class="${CFG.lede}">Las térmicas cubren lo que el agua no alcanza: cada MW térmico es un MW que no sale de Mazar.</p></div>
      <div class="g-kpis" id="g-term-kpis"></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Últimas 72 horas</h3><div class="g-sub">Térmica más renovables pequeñas, como las cuenta el modelo</div></div>
      ${leyenda("var(--g-therm)", "real (Cenace, cada media hora)")}<div class="g-chart"><svg id="g-term-72" role="img" aria-label="Generación térmica de las últimas 72 horas"></svg></div><p class="g-txt" id="g-term-txt"></p></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Hoy por tipo</h3><div class="g-sub">Lo que Cenace lleva registrado en el día</div></div><div class="g-scroll"><table class="g-tbl" id="g-term-hoy"></table></div></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Por tecnología, día a día</h3><div class="g-sub">Promedio de cada día en MW (informe diario de Cenace, se publica al día siguiente)</div></div>
      <div class="g-legend" id="g-term-ley"></div><div class="g-chart"><svg id="g-term-dias" role="img" aria-label="Generación térmica diaria por tecnología"></svg></div></div>
      <p class="g-note">Cenace no publica en sus páginas abiertas la generación de cada central térmica (Esmeraldas, Trinitaria, barcazas…): por eso se muestra por tipo. Fuentes: Cenace, información operativa (cada media hora) e informe de balance energético diario.</p>`,
    otras: () => `<div style="display:grid;gap:6px;max-width:70ch"><h2 class="${CFG.h2}">Colombia y otras fuentes</h2>
      <p class="${CFG.lede}">La interconexión con Colombia permite hasta 450 MW, pero llega solo cuando Colombia tiene excedentes. Cuando llega, alivia a Mazar.</p></div>
      <div class="g-kpis" id="g-imp-kpis"></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Importación de Colombia, últimas 72 horas</h3></div>
      ${leyenda("var(--g-col)", "real (Cenace, cada media hora)")}<div class="g-chart"><svg id="g-imp-72" role="img" aria-label="Importación de Colombia de las últimas 72 horas"></svg></div><p class="g-txt" id="g-imp-txt"></p></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Importación y exportación, día a día</h3><div class="g-sub">Promedio de cada día en MW (informe diario de Cenace)</div></div>
      <div class="g-legend"><span><i class="s" style="background:var(--g-col)"></i>importación de Colombia</span><span><i class="s" style="background:var(--g-warn)"></i>exportación a Colombia</span></div>
      <div class="g-chart"><svg id="g-imp-dias" role="img" aria-label="Importación y exportación diaria con Colombia"></svg></div></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Renovables no convencionales</h3><div class="g-sub">Solar, eólica, biomasa y biogás juntas: Cenace no las separa</div></div>
      <div class="g-kpis" id="g-ren-kpis"></div><div class="g-chart"><svg id="g-ren-72" role="img" aria-label="Renovables no convencionales en las últimas 72 horas"></svg></div>
      <div class="g-chart"><svg id="g-ren-dias" role="img" aria-label="Renovables no convencionales, promedio diario"></svg></div></div>
      <p class="g-note">Fuentes: Cenace, información operativa (cada media hora) e informe de balance energético diario.</p>`,
    rios: () => `<div style="display:grid;gap:6px;max-width:75ch"><h2 class="${CFG.h2}">Ríos y centrales</h2>
      <p class="${CFG.lede}">Cuánta energía pueden dar hoy los ríos y qué está fallando: el caudal de cada río (medido por Celec y pronosticado por GloFAS) junto a lo que genera su central (Cenace). <a href="https://datalabecuador.com/clima/" style="color:var(--g-ok);font-weight:600">Ver el clima completo →</a></p></div>
      <div class="g-grid" id="g-sem"></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Coca Codo Sinclair hora a hora</h3><div class="g-sub">Barras: MW generados. Línea: caudal del río Coca (escala de la derecha). Franja roja: horas en paro (genera menos de 100 MW teniendo río).</div></div>
      <div id="g-cc-alerta"></div>
      <div class="g-legend"><span><i class="s" style="background:var(--g-ok)"></i>MW generados (escala izquierda)</span><span><i class="s" style="background:var(--g-crit)"></i>hora en paro</span><span><i style="background:var(--g-col);height:3px"></i>caudal del río Coca, m³/s (escala derecha)</span></div>
      <div class="g-chart"><svg id="g-cc" role="img" aria-label="Coca Codo: caudal y generación hora a hora"></svg></div>
      <div><h3 class="g-h3">Riesgo de paro por sedimentos · próximos 7 días</h3><div class="g-sub" id="g-cc-riesgo-txt"></div></div><div class="g-riesgo" id="g-cc-riesgo"></div></div>
      <div><h3 class="g-h3">El río de cada central</h3><div class="g-sub">Izquierda, el caudal: puntos = medido por Celec; línea = pronóstico GloFAS corregido con lo medido (punteada: GloFAS sin corregir). Derecha, lo que generó la central cada 2 h frente a su capacidad.</div></div>
      <div class="g-col" id="g-rios"></div>
      <p class="g-note" id="g-rios-nota"></p>`
  };

  function montar() {
    const nav = document.querySelector(CFG.nav), ref = document.querySelector(CFG.despues);
    if (!nav || !ref) return false;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    TABS.forEach(([k, t]) => {
      const b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "tab"); b.dataset.tab = k; b.setAttribute("aria-selected", "false");
      if (CFG.btn) b.className = CFG.btn;
      b.textContent = t; nav.appendChild(b);
    });
    let tras = ref;
    TABS.forEach(([k]) => {
      const s = document.createElement("section");
      s.id = "tab-" + k; s.setAttribute("role", "tabpanel");
      s.className = (CFG.panel + " fuera").trim();
      s.innerHTML = `<div class="g-col">${PANEL[k]()}</div>`;
      tras.after(s); tras = s;
    });
    return true;
  }

  /* ---------- gráfico SVG sencillo ---------- */
  function grafico(id, o) {
    const svg = $(id); if (!svg) return;
    const W = Math.max(280, Math.round(svg.parentNode.clientWidth || 600));
    const H = o.h || (W < 520 ? 200 : 240), L = W < 520 ? 38 : 46, R = o.y2 ? (W < 520 ? 34 : 42) : 10, T = 12, B = 24;
    const X = x => L + (x - o.x0) / ((o.x1 - o.x0) || 1) * (W - L - R);
    const Y = y => T + (1 - (y - o.y0) / ((o.y1 - o.y0) || 1)) * (H - T - B);
    const F = `font-family="var(--g-mono,ui-monospace,monospace)" font-size="10" style="fill:var(--g-muted)"`;
    let s = "";
    (o.yt || []).forEach(v => { s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" style="stroke:var(--g-line)"/><text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" ${F}>${f(v)}</text>`; });
    if (o.y2) o.yt.forEach(v => { s += `<text x="${W - R + 5}" y="${Y(v) + 3}" ${F}>${f(v * o.y2 / o.y1)}</text>`; });
    let ultX = -99;
    (o.xt || []).forEach(([x, t]) => { const px = X(x); if (px - ultX < 44) return; ultX = px; const an = px > W - R - 18 ? "end" : "middle"; s += `<text x="${an === "end" ? W - R : px}" y="${H - 6}" text-anchor="${an}" ${F}>${esc(t)}</text>`; });
    (o.series || []).forEach(se => {
      const st = `stroke:${se.c};stroke-width:${se.w || 2}${se.dash ? ";stroke-dasharray:" + se.dash : ""}`;
      if (se.tipo === "barras") se.d.forEach(([x0, x1, y0, y1, c, op]) => {
        if (y1 == null) return; const a = Y(Math.max(y0, y1)), b = Y(Math.min(y0, y1));
        s += `<rect x="${X(x0) + 0.5}" y="${a}" width="${Math.max(1, X(x1) - X(x0) - 1)}" height="${Math.max(0, b - a)}" style="fill:${c}" ${op != null ? `opacity="${op}"` : ""}/>`;
      });
      else if (se.tipo === "franja") {
        const p = se.d.filter(q => q[1] != null && q[2] != null);
        if (p.length > 1) s += `<polygon points="${p.map(q => X(q[0]) + "," + Y(q[2])).concat(p.slice().reverse().map(q => X(q[0]) + "," + Y(q[1]))).join(" ")}" style="fill:${se.c}" opacity="${se.op || 0.2}"/>`;
      } else {
        let seg = [];
        const fin = () => { if (seg.length > 1) s += `<polyline points="${seg.join(" ")}" fill="none" style="${st}" stroke-linejoin="round" stroke-linecap="round"/>`; seg = []; };
        const k2 = se.y2 && o.y2 ? o.y1 / o.y2 : 1;
        se.d.forEach(([x, y]) => { if (y == null || isNaN(y)) fin(); else seg.push(X(x).toFixed(1) + "," + Y(Math.min(o.y1, y * k2)).toFixed(1)); });
        fin();
        if (se.puntos) se.d.forEach(([x, y]) => { if (y != null) s += `<circle cx="${X(x).toFixed(1)}" cy="${Y(Math.min(o.y1, y * k2)).toFixed(1)}" r="${se.r || 3}" style="fill:${se.c}"/>`; });
      }
    });
    (o.notas || []).forEach(([x, y, t]) => { s += `<text x="${X(x) - 4}" y="${Y(y) - 5}" text-anchor="end" ${F}>${esc(t)}</text>`; });
    (o.zonas || []).forEach(([x0, x1, c]) => { s += `<rect x="${X(x0)}" y="${T}" width="${Math.max(1, X(x1) - X(x0))}" height="${H - B - T}" style="fill:${c}" opacity="0.18"/>`; });
    (o.marcas || []).forEach(([x, t]) => { s += `<line x1="${X(x)}" x2="${X(x)}" y1="${T}" y2="${H - B}" style="stroke:var(--g-muted)" stroke-dasharray="3 3"/><text x="${X(x) + 4}" y="${T + 10}" ${F}>${esc(t)}</text>`; });
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = s;
  }
  const paso = raw => { const p = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].map(x => x * p).find(x => x >= raw * 0.999); };
  const techo = (vals, min) => { const m = Math.max(min || 1, ...vals.filter(v => v != null && !isNaN(v))) * 1.05; const st = paso(m / 4); return Math.ceil(m / st) * st; };
  const marcasY = top => { const st = paso(top / 4), out = []; for (let v = 0; v <= top + 1e-9; v += st) out.push(Math.round(v * 100) / 100); return out; };

  /* ---------- datos ---------- */
  const PUNTOS = () => (G.puntos || []).map(p => ({ k: p[0], t: local(p[0]).getTime(), h: p[1], term: p[2], ren: p[3], imp: p[4], exp: p[5], dem: p[6] }));
  const MOD = () => (G.modelo || []).map(m => Object.assign({ t: local(m.ts).getTime() }, m)).sort((a, b) => a.t - b.t);
  function modeloEn(t, clave) { let v = null; for (const m of MOD()) { if (m.t <= t) v = m[clave]; else break; } return v; }

  function bloques(d) {
    const sn = (G.plantas[d] || []).slice().sort((a, b) => a[0] - b[0]);
    const out = []; let ph = 0, pv = {};
    sn.forEach(([h, v]) => {
      const dh = h - ph; if (dh < 0.9) return;
      const b = { h0: ph, h1: h, mw: {} };
      PL.forEach(k => { b.mw[k] = Math.max(0, ((v[k] || 0) - (pv[k] || 0)) / dh); });
      out.push(b); ph = h; pv = v;
    });
    const base = local(d + "T00:00").getTime(), P = PUNTOS();
    out.forEach(b => {
      const t0 = base + b.h0 * 36e5, t1 = base + b.h1 * 36e5;
      const hs = P.filter(p => p.t >= t0 && p.t < t1 && p.h != null).map(p => p.h);
      b.hidro = hs.length >= Math.max(1, (b.h1 - b.h0) * 2 * 0.6) ? hs.reduce((a, c) => a + c, 0) / hs.length : null;
      b.t0 = t0;
    });
    return out;
  }

  /* ---------- Hidroeléctricas ---------- */
  function hidro() {
    const dias = Object.keys(G.plantas || {}).sort().slice(-2).reverse();
    if (!dias.length) return;
    if (!dia || !dias.includes(dia)) dia = dias[0];
    $("g-dias").innerHTML = dias.map((d, i) => `<button type="button" data-d="${d}" aria-pressed="${d === dia}">${i === 0 ? "Hoy" : "Ayer"} · ${fechaCorta(d)}</button>`).join("");
    $("g-dias").querySelectorAll("button").forEach(b => b.onclick = () => { dia = b.dataset.d; hidro(); });
    const bl = bloques(dia);
    const grupos = [
      { id: "ccs", t: "Coca Codo Sinclair", sub: "La central más grande del país (1.500 MW instalados)", real: b => b.mw["Coca Codo"], mod: "ccs", min: 1300 },
      { id: "cx", t: "Complejo Paute", sub: "Mazar + Molino + Sopladora: lo que sale del agua de Mazar", real: b => b.mw["Paute"] + b.mw["Sopladora"] + b.mw["Mazar"], mod: "paute", min: 900 },
      { id: "ot", t: "Otras hidroeléctricas", sub: "Todo lo hidráulico que no es Coca Codo ni Paute", real: b => b.hidro == null ? null : b.hidro - b.mw["Coca Codo"] - b.mw["Paute"] - b.mw["Sopladora"] - b.mw["Mazar"], mod: "other", min: 1500 }
    ];
    const horas = bl.length ? bl[bl.length - 1].h1 : 0;
    $("g-hidro-grupos").innerHTML = grupos.map(g => `<div class="g-box g-col"><div><h3 class="g-h3">${g.t}</h3><div class="g-sub">${g.sub}</div></div>
      <div class="g-kpis"><div><div class="g-lbl">Real, promedio</div><div class="g-big" style="color:var(--g-real)" id="g-${g.id}-r">–</div></div>
      <div><div class="g-lbl">Lo que usó el modelo</div><div class="g-big" style="color:var(--g-muted)" id="g-${g.id}-m">–</div></div>
      <div><div class="g-lbl">Diferencia</div><div class="g-big" id="g-${g.id}-d">–</div></div></div>
      <div class="g-chart"><svg id="g-${g.id}-svg" role="img" aria-label="${g.t}: generación real frente al modelo"></svg></div></div>`).join("");
    const xt = [0, 3, 6, 9, 12, 15, 18, 21, 24].map(h => [h, String(h).padStart(2, "0") + ":00"]);
    grupos.forEach(g => {
      const pr = bl.map(b => [(b.h0 + b.h1) / 2, g.real(b), b.h1 - b.h0]).filter(p => p[1] != null);
      const md = []; bl.forEach(b => { for (let h = b.h0; h < b.h1; h += 0.5) { const v = modeloEn(local(dia + "T00:00").getTime() + h * 36e5, g.mod); md.push([h, v], [Math.min(h + 0.5, b.h1), v]); } });
      const sw = pr.reduce((a, p) => a + p[2], 0), rp = sw ? pr.reduce((a, p) => a + p[1] * p[2], 0) / sw : null;
      const mv = md.filter(p => p[1] != null), mp = mv.length ? mv.reduce((a, p) => a + p[1], 0) / mv.length : null;
      $(`g-${g.id}-r`).innerHTML = rp == null ? "–" : `${f(rp)}<small>MW</small>`;
      $(`g-${g.id}-m`).innerHTML = mp == null ? "–" : `${f(mp)}<small>MW</small>`;
      if (rp != null && mp != null) {
        const dd = rp - mp, ok = Math.abs(dd) <= Math.max(60, 0.1 * mp);
        $(`g-${g.id}-d`).innerHTML = `<span class="${ok ? "g-ok" : "g-ko"}">${dd >= 0 ? "+" : "−"}${f(Math.abs(dd))}<small>MW</small></span>`;
      }
      const top = techo(pr.map(p => p[1]).concat(md.map(p => p[1])), g.min);
      const series = [{ d: md, c: "var(--g-mod)", w: 2, dash: "6 5" }, { d: pr.map(p => [p[0], p[1]]), c: "var(--g-real)", w: 3.5, puntos: true }];
      if (g.id === "ccs") series.unshift({ d: [[0, 1200], [24, 1200]], c: "var(--g-warn)", w: 1, dash: "2 4" });
      grafico(`g-${g.id}-svg`, { x0: 0, x1: 24, y0: 0, y1: top, yt: marcasY(top), xt, series, notas: g.id === "ccs" ? [[24, 1200, "tope continuo 1.200 MW"]] : [] });
    });
    $("g-hidro-centrales").innerHTML = PL.filter(k => k !== "Coca Codo").map((k, i) => {
      const pr = bl.map(b => [(b.h0 + b.h1) / 2, b.mw[k], b.h1 - b.h0]);
      const sw = pr.reduce((a, p) => a + p[2], 0), rp = sw ? pr.reduce((a, p) => a + p[1] * p[2], 0) / sw : null;
      const ult = (G.plantas[dia] || []).slice(-1)[0];
      return `<div class="g-box" style="display:grid;gap:4px"><div style="font-weight:600">${esc(NOMBRE[k] || k)}</div>
        <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap"><span class="g-big" style="font-size:24px;color:var(--g-real)">${f(rp)}<small>MW</small></span><span class="g-lbl g-mono">${ult ? f(ult[1][k]) : "–"} MWh</span></div>
        <div class="g-chart"><svg id="g-pl-${i}" role="img" aria-label="${esc(NOMBRE[k] || k)}: generación del día"></svg></div></div>`;
    }).join("");
    PL.filter(k => k !== "Coca Codo").forEach((k, i) => {
      const pr = bl.map(b => [(b.h0 + b.h1) / 2, b.mw[k]]);
      const top = techo(pr.map(p => p[1]), 50);
      grafico(`g-pl-${i}`, { h: 90, x0: 0, x1: 24, y0: 0, y1: top, yt: [0, top], xt: [[0, "00:00"], [12, "12:00"], [24, "24:00"]], series: [{ d: pr, c: "var(--g-real)", w: 2.5 }] });
    });
    $("g-hidro-nota").textContent = `Datos de ${fechaCorta(dia)} hasta las ${String(Math.floor(horas)).padStart(2, "0")}:${horas % 1 ? "30" : "00"}. La curva sale de la energía acumulada que publica Cenace en cada lectura del robot (cada 2 h). Lo que usó el modelo = el valor de entrada de la corrida vigente en ese momento. Actualizado: ${esc((G.actualizado || "").replace("T", " "))}.`;
  }

  /* ---------- ejes de 72 h ---------- */
  function eje72(P) {
    const t0 = P[0].t, t1 = P[P.length - 1].t, xt = [];
    const d = new Date(t0); d.setUTCHours(5, 0, 0, 0);          // medianoche de Ecuador = 05:00 UTC
    if (d.getTime() < t0) d.setUTCDate(d.getUTCDate() + 1);
    for (let t = d.getTime(); t <= t1; t += 864e5) { const q = new Date(t - 5 * 36e5); xt.push([t, `${q.getUTCDate()} ${MON[q.getUTCMonth()]}`]); }
    return { t0, t1, xt };
  }

  /* ---------- Térmicas ---------- */
  function term() {
    const P = PUNTOS(); if (P.length < 2) return;
    const ult = P[P.length - 1], ult24 = P.filter(p => p.t > ult.t - 864e5);
    const tt = p => p.term == null ? null : p.term + (p.ren || 0);
    const prom = ult24.reduce((a, p) => a + (tt(p) || 0), 0) / ult24.length;
    const mods = MOD(), mAct = mods.length ? mods[mods.length - 1].therm : null;
    $("g-term-kpis").innerHTML = [["Ahora (" + ult.k.slice(11) + ")", tt(ult)], ["Promedio últimas 24 h", prom], ["Lo que usa el modelo", mAct]]
      .map(([l, v], i) => `<div class="g-box"><div class="g-lbl">${l}</div><div class="g-big" style="color:${i === 2 ? "var(--g-muted)" : "var(--g-therm)"}">${f(v)}<small>MW</small></div></div>`).join("");
    const e = eje72(P), real = P.map(p => [p.t, tt(p)]), md = P.map(p => [p.t, modeloEn(p.t, "therm")]);
    const top = techo(real.map(p => p[1]).concat(md.map(p => p[1])), 1400);
    grafico("g-term-72", { x0: e.t0, x1: e.t1, y0: 0, y1: top, yt: marcasY(top), xt: e.xt, series: [{ d: md, c: "var(--g-mod)", w: 2, dash: "6 5" }, { d: real, c: "var(--g-therm)", w: 3 }] });
    const mn = Math.min(...ult24.map(tt).filter(v => v != null)), mx = Math.max(...ult24.map(tt).filter(v => v != null));
    $("g-term-txt").textContent = `En las últimas 24 h la térmica fue de ${f(mn)} a ${f(mx)} MW (promedio ${f(prom)} MW). El modelo usa ${f(mAct)} MW: el promedio de 24 h, por eso su línea es casi plana.`;
    // hoy por tipo
    const og = G.otra || {}, ds = Object.keys(og).sort().slice(-2).reverse();
    const filas = ds.map(d => { const u = og[d][og[d].length - 1]; return [d, u[0], u[1]]; });
    const tipos = ["Térmica", "Gas Natural", "Renovable"];
    $("g-term-hoy").innerHTML = `<thead><tr><th>Día</th>${tipos.map(t => `<th class="n" style="text-align:right">${t}</th>`).join("")}<th class="n" style="text-align:right">Total</th></tr></thead><tbody>` +
      filas.map(([d, h, v]) => `<tr><td>${fechaCorta(d)}${h < 24 ? ` <span class="g-lbl">(hasta las ${String(Math.floor(h)).padStart(2, "0")}:${h % 1 ? "30" : "00"})</span>` : ""}</td>${tipos.map(t => `<td class="n">${f((v[t] || 0) / h)} MW</td>`).join("")}<td class="n"><b>${f(tipos.reduce((a, t) => a + (v[t] || 0), 0) / h)} MW</b></td></tr>`).join("") + "</tbody>";
    // por tecnología
    const bal = G.balance || {}, dd = Object.keys(bal).sort().slice(-45);
    const TEC = [["motores", "Motores a búnker", "var(--g-t1)"], ["vapor", "Vapor con búnker", "var(--g-t2)"], ["diesel", "Turbinas a diésel", "var(--g-t3)"], ["gas", "Turbinas a gas", "var(--g-t4)"]];
    if (!dd.length) return;
    const ultb = bal[dd[dd.length - 1]];
    $("g-term-ley").innerHTML = TEC.map(([k, n, c]) => `<span><i class="s" style="background:${c}"></i>${n} · <b class="g-mono">${f(ultb[k])} MW</b></span>`).join("") + `<span>(${fechaCorta(dd[dd.length - 1])})</span>`;
    const barras = [];
    dd.forEach((d, i) => { let y = 0; TEC.forEach(([k, , c]) => { const v = bal[d][k] || 0; barras.push([i, i + 1, y, y + v, c]); y += v; }); });
    const topb = techo(dd.map(d => TEC.reduce((a, [k]) => a + (bal[d][k] || 0), 0)), 800);
    const xt = dd.map((d, i) => [i + 0.5, d.slice(8) === "01" || i === 0 || i === dd.length - 1 ? fechaCorta(d).slice(4) : null]).filter(x => x[1]);
    grafico("g-term-dias", { x0: 0, x1: dd.length, y0: 0, y1: topb, yt: marcasY(topb), xt, series: [{ tipo: "barras", d: barras }] });
  }

  /* ---------- Colombia y renovables ---------- */
  function otras() {
    const P = PUNTOS(); if (P.length < 2) return;
    const ult = P[P.length - 1], u24 = P.filter(p => p.t > ult.t - 864e5);
    const prom = u24.reduce((a, p) => a + (p.imp || 0), 0) / u24.length, mx = Math.max(...P.map(p => p.imp || 0));
    const mods = MOD(), mAct = mods.length ? mods[mods.length - 1].imp : null;
    const k = (l, v, c) => `<div class="g-box"><div class="g-lbl">${l}</div><div class="g-big" style="color:${c}">${f(v)}<small>MW</small></div></div>`;
    $("g-imp-kpis").innerHTML = k("Ahora (" + ult.k.slice(11) + ")", ult.imp, "var(--g-col)") + k("Promedio últimas 24 h", prom, "var(--g-col)") + k("Máximo en 72 h", mx, "var(--g-col)") + k("Lo que usa el modelo", mAct, "var(--g-muted)");
    const e = eje72(P), real = P.map(p => [p.t, p.imp]), md = P.map(p => [p.t, modeloEn(p.t, "imp")]);
    const top = techo(real.map(p => p[1]).concat(md.map(p => p[1])), 50);
    grafico("g-imp-72", { x0: e.t0, x1: e.t1, y0: 0, y1: top, yt: marcasY(top), xt: e.xt, series: [{ d: md, c: "var(--g-mod)", w: 2, dash: "6 5" }, { d: real, c: "var(--g-col)", w: 3 }] });
    // racha más grande de las últimas 72 h
    let mejor = null, ini = null, suma = 0, n = 0;
    P.concat([{ imp: 0, t: Infinity }]).forEach(p => {
      if ((p.imp || 0) >= 20) { if (ini == null) { ini = p; suma = 0; n = 0; } suma += p.imp; n++; }
      else if (ini != null) { const r = { ini, fin: p, prom: suma / n, n }; if (!mejor || r.n * r.prom > mejor.n * mejor.prom) mejor = r; ini = null; }
    });
    const hhmm = p => p.k ? `${fechaCorta(p.k.slice(0, 10))} ${p.k.slice(11)}` : "";
    $("g-imp-txt").textContent = mejor ? `La llegada más grande de las últimas 72 h: unos ${f(mejor.prom)} MW durante ${f(mejor.n / 2, mejor.n % 2 ? 1 : 0)} h, desde ${hhmm(mejor.ini)}. Como llega a ratos, el modelo usa el promedio de 24 h (${f(mAct)} MW). Unos 45 MW sostenidos moverían la zona crítica de Mazar unos 2,5 a 4 días.`
      : `En las últimas 72 h casi no llegó energía de Colombia. El modelo usa el promedio de 24 h (${f(mAct)} MW).`;
    const bal = G.balance || {}, dd = Object.keys(bal).sort().slice(-45);
    if (dd.length) {
      const barras = [];
      dd.forEach((d, i) => { barras.push([i + 0.05, i + 0.5, 0, bal[d].imp_col || 0, "var(--g-col)"]); barras.push([i + 0.5, i + 0.95, 0, bal[d].exp_col || 0, "var(--g-warn)"]); });
      const topb = techo(dd.map(d => Math.max(bal[d].imp_col || 0, bal[d].exp_col || 0)), 20);
      const xt = dd.map((d, i) => [i + 0.5, d.slice(8) === "01" || i === 0 || i === dd.length - 1 ? fechaCorta(d).slice(4) : null]).filter(x => x[1]);
      grafico("g-imp-dias", { x0: 0, x1: dd.length, y0: 0, y1: topb, yt: marcasY(topb), xt, series: [{ tipo: "barras", d: barras }] });
      const br = dd.map((d, i) => [i, i + 1, 0, bal[d].otros || 0, "var(--g-ok)"]);
      const topr = techo(dd.map(d => bal[d].otros || 0), 20);
      grafico("g-ren-dias", { h: 170, x0: 0, x1: dd.length, y0: 0, y1: topr, yt: marcasY(topr), xt, series: [{ tipo: "barras", d: br }] });
    }
    const pr = u24.reduce((a, p) => a + (p.ren || 0), 0) / u24.length;
    $("g-ren-kpis").innerHTML = k("Ahora (" + ult.k.slice(11) + ")", ult.ren, "var(--g-ok)") + k("Promedio últimas 24 h", pr, "var(--g-ok)") + k("Máximo en 72 h", Math.max(...P.map(p => p.ren || 0)), "var(--g-ok)");
    const rr = P.map(p => [p.t, p.ren]), tr = techo(rr.map(p => p[1]), 30);
    grafico("g-ren-72", { h: 170, x0: e.t0, x1: e.t1, y0: 0, y1: tr, yt: marcasY(tr), xt: e.xt, series: [{ d: rr, c: "var(--g-ok)", w: 2.5 }] });
  }

  /* ---------- Ríos y centrales ---------- */
  const CENTRALES = [
    { k: "paute", n: "Complejo Paute", s: "Mazar · Molino · Sopladora", rio: "Paute", pl: ["Paute", "Sopladora", "Mazar"], cap: 1757 },
    { k: "coca", n: "Coca Codo Sinclair", s: "la central más grande del país", rio: "Coca", pl: ["Coca Codo"], cap: 1500 },
    { k: "pastaza", n: "Agoyán + San Francisco", s: "Celec Hidroagoyán", rio: "Pastaza", pl: ["Agoyán", "San Francisco"], cap: 386 },
    { k: "zamora", n: "Delsitanisagua", s: "Zamora Chinchipe", rio: "Zamora", pl: ["Delsitanisagua"], cap: 180 },
    { k: "jubones", n: "Minas San Francisco", s: "Azuay y El Oro", rio: "Jubones", pl: ["Minas San Francisco"], cap: 275 }];
  const COLP = { "Paute": "var(--g-real)", "Sopladora": "var(--g-col)", "Mazar": "var(--g-mod)", "Coca Codo": "var(--g-real)", "Agoyán": "var(--g-warn)", "San Francisco": "var(--g-therm)", "Delsitanisagua": "var(--g-real)", "Minas San Francisco": "var(--g-real)" };
  const hoyEc = () => new Date(Date.now() - 5 * 36e5).toISOString().slice(0, 10);
  function bloquesN(n) {   // bloques de los últimos n días con su hora absoluta
    const out = [];
    Object.keys(G.plantas || {}).sort().slice(-n).forEach(d => bloques(d).forEach(b => out.push(Object.assign({ d, ta: local(d + "T00:00").getTime() + b.h0 * 36e5, tb: local(d + "T00:00").getTime() + b.h1 * 36e5 }, b))));
    return out;
  }
  function rios() {
    const RR = {}; (G.rios || []).forEach(r => RR[r.clave] = r);
    const RE = G.rios_reales || {}, BL = bloquesN(4), hoy = hoyEc();
    const ult12 = BL.slice(-6), mwDe = (c, bs) => bs.length ? bs.reduce((a, b) => a + c.pl.reduce((x, p) => x + (b.mw[p] || 0), 0), 0) / bs.length : null;
    const CH = (G.coca_horas || []).filter(x => x[2] != null);
    const paro24 = CH.slice(-24).filter(x => x[2] < 100 && x[1] > 150).length;
    $("g-sem").innerHTML = CENTRALES.map(c => {
      const r = RR[c.k] || {}, me = RE[c.k] || [], ih = (r.dias || []).indexOf(hoy);
      const ultMed = me.length && me[me.length - 1][0] >= new Date(Date.now() - 2 * 864e5 - 5 * 36e5).toISOString().slice(0, 10) ? me[me.length - 1] : null;
      const q = ultMed ? ultMed[1] : (ih >= 0 ? (r.q_c || r.q)[ih] : null);
      const ref = me.length >= 10 ? me.slice(-31, -1).map(x => x[1]) : (r.q_c || r.q || []).slice(0, Math.max(1, ih));
      const prom = ref.length ? ref.reduce((a, b) => a + b, 0) / ref.length : null, pct = q && prom ? Math.round(q / prom * 100) : null;
      const mw = mwDe(c, ult12), uso = mw != null ? Math.round(mw / c.cap * 100) : null;
      const est = c.k === "coca" && paro24 >= 2 ? ["mal", `Paro de ~${paro24} h en 24 h`] : pct != null && pct < 60 ? ["med", "Río bajo"] : pct != null && pct > 180 ? ["med", "Río alto"] : uso != null && uso < 10 ? ["mal", "Casi sin generar"] : ["ok", "Normal"];
      return `<div class="g-box" style="display:grid;gap:2px"><div style="display:flex;justify-content:space-between;align-items:center;gap:6px"><b>${esc(c.n)}</b><span class="g-est ${est[0]}"><i></i>${est[1]}</span></div>
        <div class="g-sub">${esc(c.s)} · río ${esc(c.rio)}</div>
        <div class="g-fila"><span>Caudal ${ultMed ? "medido (Celec)" : "previsto (GloFAS)"}</span><b>${f(q)} m³/s</b></div>
        <div class="g-fila"><span>Frente al último mes</span><b>${pct == null ? "–" : pct + " %"}</b></div><div class="g-bar"><i style="width:${Math.min(100, pct || 0)}%;background:${pct != null && pct < 60 ? "var(--g-warn)" : "var(--g-col)"}"></i></div>
        <div class="g-fila"><span>Generando (últimas 12 h)</span><b>${f(mw)} MW</b></div>
        <div class="g-fila"><span>De su capacidad (${f(c.cap)} MW)</span><b>${uso == null ? "–" : uso + " %"}</b></div><div class="g-bar"><i style="width:${Math.min(100, uso || 0)}%;background:var(--g-ok)"></i></div></div>`;
    }).join("");
    // Coca Codo hora a hora
    const CC = (G.coca_horas || []).slice(-36);
    if (CC.length > 3) {
      const tOf = k => local(k.slice(0, 13) + ":00").getTime();
      const x0 = tOf(CC[0][0]), x1 = tOf(CC[CC.length - 1][0]) + 36e5;
      const barras = CC.filter(x => x[2] != null).map(x => [tOf(x[0]) + 3e5, tOf(x[0]) + 33e5, 0, x[2], x[2] < 100 && x[1] > 150 ? "var(--g-crit)" : "var(--g-ok)"]);
      const zonas = CC.filter(x => x[2] != null && x[2] < 100 && x[1] > 150).map(x => [tOf(x[0]), tOf(x[0]) + 36e5, "var(--g-crit)"]);
      const xt = CC.filter((x, i) => i % 6 === 0).map(x => [tOf(x[0]) + 18e5, x[0].slice(11, 13) + ":00"]);
      grafico("g-cc", { x0, x1, y0: 0, y1: 1300, y2: 650, yt: [0, 260, 520, 780, 1040, 1300], xt, zonas,
        series: [{ tipo: "barras", d: barras }, { d: CC.map(x => [tOf(x[0]) + 18e5, x[1]]), c: "var(--g-col)", w: 2.5, y2: true, puntos: true, r: 2 }] });
      const par = CC.filter(x => x[2] != null && x[2] < 100 && x[1] > 150);
      if (par.length >= 2) {
        let sub = null; CC.forEach((x, i) => { if (i >= 2 && !sub && x[1] >= CC[i - 2][1] * 1.5 && x[1] - CC[i - 2][1] >= 100) sub = [CC[i - 2], x]; });
        const perd = par.reduce((a, x) => a + Math.max(0, Math.min(1200, 5.25 * (x[1] - 21)) - x[2]), 0);
        $("g-cc-alerta").innerHTML = `<div class="g-alerta">⚠️ <b>Paro de Coca Codo:</b> ${par.length} h sin generar en las últimas 36 h${sub ? `; el río subió de ${f(sub[0][1])} a ${f(sub[1][1])} m³/s en 2 h (${sub[1][0].slice(11, 13)}:00), la señal típica de una crecida con sedimentos` : ""}. Con el río que tenía pudo generar ~${f(Math.round(perd / 100) * 100)} MWh más.</div>`;
      } else $("g-cc-alerta").innerHTML = "";
    }
    const T = G.ccs_crecida, rc = RR.coca;
    if (rc && T) {
      const ih = rc.dias.indexOf(hoy), qq = rc.med_c || rc.q_c || rc.q;
      const fac = q => { const t = T.find(t => q >= t.desde && (t.hasta == null || q < t.hasta)); return t ? t.factor : 1; };
      $("g-cc-riesgo-txt").textContent = `Según el caudal previsto del Coca y lo que pasó en el último año (Celec): ` + T.filter(t => t.desde > 0 && t.dias).map(t => `con más de ${f(t.desde)} m³/s rinde ${f(t.rendimiento * 100)} % (${t.dias} días)`).join("; ") + ". Una subida de más del 50 % en 2–3 h también es señal de alerta.";
      $("g-cc-riesgo").innerHTML = ih < 0 ? "" : [1, 2, 3, 4, 5, 6, 7].map(k => { const q = qq[ih + k]; if (q == null) return ""; const fa = fac(q), e = fa < 0.9 ? ["mal", "Alto"] : fa < 0.995 ? ["med", "Medio"] : ["ok", "Bajo"];
        return `<div>${fechaCorta(rc.dias[ih + k])}<b class="g-mono">${f(q)} m³/s</b><span class="g-est ${e[0]}"><i></i>${e[1]}</span></div>`; }).join("");
    }
    // un río por central
    $("g-rios").innerHTML = CENTRALES.map((c, i) => { const r = RR[c.k]; if (!r) return "";
      const nota = r.ratio ? `GloFAS ${r.ratio < 0.8 ? "exagera" : r.ratio > 1.25 ? "se queda corto" : "acierta"}: lo medido es ${f(r.ratio * 100)} % de lo que dice (últimos ${r.ratio_dias} días); se corrige.` : "Celec no publica el caudal de este río (Agoyán y San Francisco son de otra unidad de Celec): se muestra GloFAS sin corregir.";
      return `<div class="g-box g-col"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px 12px;align-items:baseline"><h3 class="g-h3">Río ${esc(c.rio)} → ${esc(c.n)}</h3><span class="g-note">${nota}</span></div>
        <div class="g-dos"><div class="g-chart"><div class="g-lbl" id="g-rq-t${i}"></div>
        <div class="g-legend" style="margin:4px 0"><span><i class="s" style="background:var(--g-ink);border-radius:50%;width:8px;height:8px"></i>medido por Celec</span><span><i style="background:var(--g-real);height:3px"></i>${r.ratio ? "pronóstico corregido" : "pronóstico GloFAS"}</span>${r.ratio && (r.ratio < 0.8 || r.ratio > 1.25) && r.ratio > 0.2 ? `<span><i class="d" style="border-top-color:var(--g-muted)"></i>GloFAS sin corregir</span>` : ""}<span><i class="s" style="background:var(--g-real);opacity:.25"></i>rango probable</span></div><svg id="g-rq-${i}" role="img" aria-label="Caudal del río ${esc(c.rio)}"></svg></div>
        <div class="g-chart"><div class="g-lbl">Generación cada 2 h (MW, Cenace)</div>
        <div class="g-legend" style="margin:4px 0">${c.pl.map(p => `<span><i class="s" style="background:${COLP[p]}"></i>${esc(NOMBRE[p] || p)}</span>`).join("")}<span><i class="d" style="border-top-color:var(--g-warn)"></i>capacidad ${f(c.cap)} MW</span></div><svg id="g-rg-${i}" role="img" aria-label="Generación de ${esc(c.n)}"></svg></div></div></div>`; }).join("");
    CENTRALES.forEach((c, i) => { const r = RR[c.k]; if (!r) return;
      const n = r.dias.length, ih = r.dias.indexOf(hoy), idx = d => r.dias.indexOf(d);
      const qc = r.q_c || r.q, p25 = r.p25_c || r.p25, p75 = r.p75_c || r.p75;
      const med = (RE[c.k] || []).map(([d, q]) => [idx(d), q]).filter(p => p[0] >= 0);
      const crudo = r.ratio && (r.ratio < 0.8 || r.ratio > 1.25) && r.ratio > 0.2;
      const top = techo(qc.concat(p75, med.map(p => p[1]), crudo ? r.q : []), 20);
      const xt = r.dias.map((d, j) => [j, j === ih ? "hoy" : (j % 7 === 0 ? fechaCorta(d).slice(4) : null)]).filter(x => x[1]);
      const series = [{ tipo: "franja", d: r.dias.map((d, j) => [j, j >= ih ? p25[j] : null, j >= ih ? p75[j] : null]), c: "var(--g-real)", op: 0.22 }];
      if (crudo) series.push({ d: r.dias.map((d, j) => [j, r.q[j]]), c: "var(--g-muted)", w: 1.2, dash: "3 4" });
      series.push({ d: r.dias.map((d, j) => [j, qc[j]]), c: "var(--g-real)", w: 2.8 }, { d: med, c: "var(--g-ink)", w: 1.4, puntos: true, r: 3.2 });
      grafico(`g-rq-${i}`, { h: 230, x0: 0, x1: n - 1, y0: 0, y1: top, yt: marcasY(top), xt, marcas: ih >= 0 ? [[ih, ""]] : [], series });
      const q0 = ih >= 0 ? qc[ih] : null, q7 = ih >= 0 ? qc[Math.min(n - 1, ih + 7)] : null;
      if (q0 && q7) { const cc = (q7 / q0 - 1) * 100; $(`g-rq-t${i}`).textContent = `Caudal (m³/s): ${f(q0)} hoy → ${f(q7)} en 7 días (${cc >= 0 ? "+" : "−"}${f(Math.abs(cc))} %)` + (med.length ? ` · último medido: ${f(med[med.length - 1][1])}` : ""); }
      if (BL.length) {
        const x0 = BL[0].ta, x1 = BL[BL.length - 1].tb, barras = [];
        BL.forEach(b => { let y = 0; c.pl.forEach(p => { const v = b.mw[p] || 0; barras.push([b.ta, b.tb, y, y + v, COLP[p]]); y += v; }); });
        const xtg = []; Object.keys(G.plantas || {}).sort().slice(-4).forEach(d => xtg.push([local(d + "T12:00").getTime(), fechaCorta(d)]));
        const topg = techo([c.cap * 1.02], 50);
        grafico(`g-rg-${i}`, { h: 230, x0, x1, y0: 0, y1: topg, yt: marcasY(topg), xt: xtg, series: [{ tipo: "barras", d: barras }, { d: [[x0, c.cap], [x1, c.cap]], c: "var(--g-warn)", w: 1.2, dash: "5 4" }] });
      }
    });
    const O = G.otras_rios;
    $("g-rios-nota").textContent = (O ? `El simulador ya usa estos ríos: Agoyán, San Francisco, Delsitanisagua y Minas San Francisco (${f(O.mw_total)} MW de las ${f(O.other)} MW de "otras hidroeléctricas") siguen el pronóstico de su propio río, y cada día aprende cuánto de lo que promete GloFAS se cumple. ` : "") +
      `Fuentes: Celec (caudales medidos y Coca Codo hora a hora), Cenace (generación de cada central), GloFAS de Copernicus vía Open-Meteo (pronóstico). Actualizado: ${esc((G.actualizado || "").replace("T", " "))}.`;
  }

  /* ---------- carga y dibujo ---------- */
  const DIBUJA = { hidro, term, otras, rios };
  function dibujar(tab) {
    if (!DIBUJA[tab]) return;
    ultimo = tab;
    if (!G) { cargar(); return; }
    try { DIBUJA[tab](); } catch (e) { console.error("generacion.js", tab, e); }
  }
  const espera = [];
  function cargar() {
    if (cargando) return; cargando = true;
    fetch(CFG.url + (CFG.url.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" })
      .then(r => r.ok ? r.json() : null).then(j => { if (j) { G = j; if (ultimo) dibujar(ultimo); espera.splice(0).forEach(f => f()); } })
      .catch(() => { }).finally(() => { cargando = false; });
  }
  // Último dato real de Cenace para comparar con lo simulado: Coca Codo (último bloque horario) e importación de Colombia
  function real(cb) {
    const fin = () => { try {
      const dias = Object.keys(G.plantas || {}).sort(), d = dias[dias.length - 1];
      const b = d ? bloques(d).slice(-1)[0] : null;
      const P = PUNTOS().filter(p => p.imp != null), p = P[P.length - 1];
      const hh = h => String(Math.floor(h)).padStart(2, "0") + ":" + (h % 1 ? "30" : "00");
      cb({ ccs: b ? { mw: Math.round(b.mw["Coca Codo"]), txt: hh(b.h0) + "–" + hh(b.h1), dia: d } : null,
           col: p ? { mw: Math.round(p.imp), txt: p.k.slice(11, 16) } : null });
    } catch (e) { } };
    if (G) fin(); else { espera.push(fin); cargar(); }
  }
  if (montar()) {
    window.GEN = { dibujar, real };
    let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (ultimo && $("tab-" + ultimo) && !$("tab-" + ultimo).classList.contains("fuera")) dibujar(ultimo); }, 150); });
  }
})();
