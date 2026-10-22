/* Pestañas "Hidroeléctricas", "Térmicas", "Otras fuentes y Colombia" y "Clima e hidrología".
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
.g-ok{color:var(--g-ok)}.g-ko{color:var(--g-crit)}`;

  /* ---------- pestañas y paneles ---------- */
  const TABS = [["hidro", "Hidroeléctricas"], ["term", "Térmicas"], ["otras", "Otras fuentes y Colombia"], ["clima", "Clima e hidrología"]];
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
    clima: () => `<div style="display:grid;gap:6px;max-width:70ch"><h2 class="${CFG.h2}">Clima e hidrología</h2>
      <p class="${CFG.lede}">Lo que mueve a las centrales: el calor en Guayaquil (más consumo), la lluvia en las cuencas del Paute y del Coca y los caudales de los ríos que alimentan a las hidroeléctricas.</p></div>
      <div><h3 class="g-h3">Pronóstico del Inamhi</h3><div class="g-sub">Pronóstico oficial por ciudad</div></div>
      <div class="g-grid" id="g-ciudades"></div>
      <div><h3 class="g-h3">Lluvia ahora en las estaciones del Inamhi</h3><div class="g-sub">Última lectura de las estaciones más cercanas</div></div>
      <div class="g-grid" id="g-estaciones"></div>
      <div class="g-box g-col"><div><h3 class="g-h3">Lluvia en las cuencas: últimos 7 días y próximos 10</h3><div class="g-sub">mm por día, promedio de dos puntos de cada cuenca (modelo ECMWF, vía Open-Meteo)</div></div>
      <div class="g-legend"><span><i class="s" style="background:var(--g-real)"></i>lo que llovió</span><span><i class="s" style="background:var(--g-real);opacity:.4"></i>pronóstico</span></div>
      <div class="g-grid"><div class="g-chart"><div class="g-lbl">Cuenca del Paute (Mazar)</div><svg id="g-ll-paute" role="img" aria-label="Lluvia en la cuenca del Paute"></svg></div>
      <div class="g-chart"><div class="g-lbl">Cuenca del Coca (Coca Codo)</div><svg id="g-ll-coca" role="img" aria-label="Lluvia en la cuenca del Coca"></svg></div></div>
      <div class="g-chart"><div class="g-lbl">Guayaquil: temperatura máxima (°C)</div><svg id="g-gye" role="img" aria-label="Temperatura máxima en Guayaquil"></svg></div></div>
      <div><h3 class="g-h3">Pronóstico hidrológico de los ríos</h3><div class="g-sub">Caudal en m³/s: últimos 7 días y próximos 30 según GloFAS (Copernicus, el modelo hidrológico global de la Unión Europea). La franja es el rango probable.</div></div>
      <div class="g-legend"><span><i style="background:var(--g-real);height:3px"></i>GloFAS</span><span><i class="s" style="background:var(--g-real);opacity:.25"></i>rango probable (25–75 %)</span><span><i class="s" style="background:var(--g-ink);border-radius:50%;width:8px;height:8px"></i>caudal medido por Celec</span></div>
      <div class="g-grid" id="g-rios"></div>
      <p class="g-note">GloFAS es un modelo global: sirve más para ver si el río va a subir o bajar que para el valor exacto. En el Paute y el Coca se ve junto al caudal medido por Celec para comparar. Fuentes: Inamhi (pronóstico por ciudad y estaciones en tiempo real), Open-Meteo (ECMWF y GloFAS de Copernicus) y Celec.</p>`
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
    const H = o.h || (W < 520 ? 200 : 240), L = W < 520 ? 38 : 46, R = 10, T = 12, B = 24;
    const X = x => L + (x - o.x0) / ((o.x1 - o.x0) || 1) * (W - L - R);
    const Y = y => T + (1 - (y - o.y0) / ((o.y1 - o.y0) || 1)) * (H - T - B);
    const F = `font-family="var(--g-mono,ui-monospace,monospace)" font-size="10" style="fill:var(--g-muted)"`;
    let s = "";
    (o.yt || []).forEach(v => { s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" style="stroke:var(--g-line)"/><text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" ${F}>${f(v)}</text>`; });
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
        se.d.forEach(([x, y]) => { if (y == null || isNaN(y)) fin(); else seg.push(X(x).toFixed(1) + "," + Y(Math.min(o.y1, y)).toFixed(1)); });
        fin();
        if (se.puntos) se.d.forEach(([x, y]) => { if (y != null) s += `<circle cx="${X(x).toFixed(1)}" cy="${Y(Math.min(o.y1, y)).toFixed(1)}" r="${se.r || 3}" style="fill:${se.c}"/>`; });
      }
    });
    (o.notas || []).forEach(([x, y, t]) => { s += `<text x="${X(x) - 4}" y="${Y(y) - 5}" text-anchor="end" ${F}>${esc(t)}</text>`; });
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

  /* ---------- Clima e hidrología ---------- */
  const ROL = { "Guayaquil": "Calor = más consumo de luz", "Cuenca": "Cuenca del Paute (Mazar)", "Tena": "Cuenca del Coca", "Nueva Loja": "Cuenca del Coca (Coca Codo)" };
  const cond = c => esc(String(c || "").replace(/\s+(dia|día|noche)$/i, "").replace(/,/g, ", ").toLowerCase().replace(/^./, m => m.toUpperCase()));
  function clima() {
    const C = G.ciudades || {};
    $("g-ciudades").innerHTML = Object.keys(ROL).filter(n => C[n]).map(n => `<div class="g-box" style="display:grid;gap:8px"><div><div style="font-weight:700">${n}</div><div class="g-sub">${ROL[n]}</div></div>` +
      C[n].map(d => `<div class="g-dia"><div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><b>${fechaCorta(d.fecha)}</b><span class="g-mono">${f(+d.min, 0)}° / ${f(+d.max, 0)}°C</span></div>
        <div class="g-per">${(d.periodos || []).map(p => `<span>${esc(p.p)}</span><span>${cond(p.c)}</span>`).join("")}</div></div>`).join("") + `</div>`).join("") || `<p class="g-note">Sin datos del Inamhi por ahora.</p>`;
    const E = G.estaciones || {};
    $("g-estaciones").innerHTML = ["paute", "coca", "gye"].filter(k => E[k]).map(k => {
      const es = (E[k].estaciones || []).slice(0, 4), est = { clear: "sin lluvia", localized: "lluvia aislada", raining: "llueve", rain: "llueve", drizzle: "llovizna" }[E[k].estado] || (E[k].estado || "");
      return `<div class="g-box" style="display:grid;gap:6px"><div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap"><b>${esc(E[k].nombre)}</b><span class="${E[k].estado && E[k].estado !== "clear" ? "g-ok" : "g-lbl"}" style="font-weight:600">${esc(est)}</span></div>
        <table class="g-tbl"><thead><tr><th>Estación</th><th class="n" style="text-align:right">mm</th><th class="n" style="text-align:right">Hora</th></tr></thead><tbody>${es.map(s => `<tr><td>${esc(s.n)} <span class="g-lbl">· ${f(s.km, 0)} km</span></td><td class="n">${f(s.mm, 1)}</td><td class="n">${esc((s.t || "").slice(11, 16))}</td></tr>`).join("")}</tbody></table></div>`;
    }).join("") || `<p class="g-note">Sin datos de estaciones por ahora.</p>`;
    const Lv = G.lluvia || {};
    if (Lv.dias) {
      const hoy = new Date(Date.now() - 5 * 36e5).toISOString().slice(0, 10), n = Lv.dias.length;
      const xt = Lv.dias.map((d, i) => [i + 0.5, i % 3 === 0 || d === hoy ? (d === hoy ? "hoy" : fechaCorta(d).slice(4)) : null]).filter(x => x[1]);
      const ih = Lv.dias.indexOf(hoy);
      [["paute", "g-ll-paute"], ["coca", "g-ll-coca"]].forEach(([k, id]) => {
        const v = Lv[k] || [], top = techo(v, 10);
        grafico(id, { h: 170, x0: 0, x1: n, y0: 0, y1: top, yt: marcasY(top), xt, marcas: ih >= 0 ? [[ih, ""]] : [],
          series: [{ tipo: "barras", d: v.map((y, i) => [i + 0.1, i + 0.9, 0, y, "var(--g-real)", Lv.dias[i] >= hoy ? 0.4 : 1]) }] });
      });
      const tg = Lv.gye_tmax || [], tmin = Math.floor(Math.min(...tg.filter(x => x != null)) - 1), tmax = Math.ceil(Math.max(...tg.filter(x => x != null)) + 1);
      grafico("g-gye", { h: 150, x0: 0, x1: n, y0: tmin, y1: tmax, yt: [tmin, Math.round((tmin + tmax) / 2), tmax], xt, marcas: ih >= 0 ? [[ih + 0.5, ""]] : [],
        series: [{ d: tg.map((y, i) => [i + 0.5, y]), c: "var(--g-crit)", w: 2.5, puntos: true, r: 2.5 }] });
    }
    const RR = G.rios || [], RE = G.rios_reales || {};
    $("g-rios").innerHTML = RR.map((r, i) => `<div class="g-box" style="display:grid;gap:4px"><div><b>Río ${esc(r.rio)}</b><div class="g-sub">${esc(r.centrales)}</div></div><div class="g-lbl" id="g-rio-t${i}"></div><div class="g-chart"><svg id="g-rio-${i}" role="img" aria-label="Pronóstico de caudal del río ${esc(r.rio)}"></svg></div></div>`).join("") || `<p class="g-note">Sin pronóstico hidrológico por ahora.</p>`;
    RR.forEach((r, i) => {
      const n = r.dias.length, idx = d => r.dias.indexOf(d), hoy = new Date(Date.now() - 5 * 36e5).toISOString().slice(0, 10), ih = idx(hoy);
      const med = (RE[r.clave] || []).map(([d, q]) => [idx(d), q]).filter(p => p[0] >= 0);
      const vals = r.q.concat(r.p75 || [], med.map(p => p[1]));
      const top = techo(vals, 20);
      const xt = r.dias.map((d, j) => [j, j === ih ? "hoy" : (j % 7 === 0 ? fechaCorta(d).slice(4) : null)]).filter(x => x[1]);
      grafico(`g-rio-${i}`, { h: 170, x0: 0, x1: n - 1, y0: 0, y1: top, yt: marcasY(top), xt, marcas: ih >= 0 ? [[ih, ""]] : [],
        series: [{ tipo: "franja", d: r.dias.map((d, j) => [j, r.p25[j], r.p75[j]]), c: "var(--g-real)", op: 0.22 },
          { d: r.dias.map((d, j) => [j, r.q[j]]), c: "var(--g-real)", w: 2.5 }, { d: med, c: "var(--g-ink)", w: 1.5, puntos: true, r: 3.2 }] });
      const q0 = ih >= 0 ? r.q[ih] : null, q7 = ih >= 0 ? r.q[Math.min(n - 1, ih + 7)] : null;
      if (q0 && q7) { const c = (q7 / q0 - 1) * 100; $(`g-rio-t${i}`).textContent = `GloFAS: ${f(q0)} m³/s hoy → ${f(q7)} m³/s en 7 días (${c >= 0 ? "+" : "−"}${f(Math.abs(c))} %)` + (med.length ? ` · medido por Celec: ${f(med[med.length - 1][1])} m³/s` : ""); }
    });
  }

  /* ---------- carga y dibujo ---------- */
  const DIBUJA = { hidro, term, otras, clima };
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
