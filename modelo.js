/* Modelo del embalse Mazar — compartido por los dos simuladores:
   · Monitoreo del sistema eléctrico del Ecuador: Mazar y generación (luiscampozano/simulador-mazar)
   · Monitoreo del sistema eléctrico del Ecuador: proyección del embalse Mazar (luiscampozano/simulador-sni-mazar)
   Los parámetros los calibra cada día scripts/calibrar.py con todo el historial de Celec Sur (desde 2023)
   y llegan en datos.json → "modelo". Si faltan, se usan los valores de respaldo de abajo. */
(function (global) {
  "use strict";
  const COTA_CRIT = 2115, COTA_MAX = 2153, PAUTE_MAX = 1757;
  const RESPALDO = {
    curva_mazar: { a: 3.665, b: 0.1248 },     // hm³ por metro = a + b·(cota − 2115)
    eficiencia_mazar: 0.845,
    k_molino_sopladora: 9.62,                // MW por m³/s que pasa por Molino y Sopladora
    beta_cuenca_intermedia: 0.464,           // aporte entre Mazar y Amaluza = beta × caudal de Mazar
    amaluza: { piso: 1971.3, area: [0.0844, 0.1203] },
  };
  let PAR = JSON.parse(JSON.stringify(RESPALDO));

  function configurar(m) {
    PAR = JSON.parse(JSON.stringify(RESPALDO));
    if (!m) return;
    for (const k of Object.keys(RESPALDO)) if (m[k] != null) PAR[k] = m[k];
  }
  const A = () => PAR.curva_mazar.a, B = () => PAR.curva_mazar.b;
  const volOf = x => A() * x + B() * x * x / 2;                       // hm³ sobre 2.115
  const xOf = v => v <= 0 ? 0 : (-A() + Math.sqrt(A() * A() + 2 * B() * v)) / B();
  const areaEn = cota => A() + B() * (cota - COTA_CRIT);

  function perfil(kind, t, q0, target, serie) {
    if (kind === "auto" && serie && serie.length > 1) {
      const i = Math.min(serie.length - 2, Math.floor(t)), f = Math.min(1, t - i);
      return q0 * (serie[i] + (serie[i + 1] - serie[i]) * f);
    }
    if (kind === "seco") return q0 * Math.max(0.7, 1 - 0.01 * t);
    if (kind === "inamhi" || kind === "auto") { const b0 = Math.exp(-1.6); return q0 * (1 + 0.45 * Math.max(0, Math.exp(-((t - 2) ** 2) / 2.5) - b0) / (1 - b0)); }
    return q0 + (target - q0) * (1 - Math.exp(-t / 7));   // lluvia sostenida
  }
  function ccsMW(q) { let p = Math.min(5 * q, 1200); if (q > 450) p *= 0.5; return p; }

  /* P: {qMazar, qCoca, wPaute, wCoca, demanda (MW medios sin cortes, ya con el efecto de la temperatura),
         cut, imp, therm, other, ccsFn (opcional)}
     ctx: {cota, inicio (Date), diaSemana0 (0 = domingo, día de la lectura en Ecuador), amaluzaCota, amaluzaRitmo (hm³/día que se saca de Amaluza),
           deltaDia [7] (MW extra de Paute por día de la semana, 0 = domingo), cutDias [7] (true/false),
           cutPlan [] (MW de cortes ya anunciados o de emergencia por día desde la lectura: 0 = día de la lectura; null = usar cutDias),
           serieMazar, serieCoca (caudal relativo al de hoy, día a día), horizonte} */
  function simular(P, ctx) {
    const dt = 0.25, H = ctx.horizonte || 60;
    const kms = PAR.k_molino_sopladora, beta = PAR.beta_cuenca_intermedia, eta = PAR.eficiencia_mazar;
    const amC = ctx.amaluzaCota || 1980;
    const [aa, ab] = PAR.amaluza.area, piso = PAR.amaluza.piso;
    const volAm = h => h <= piso ? 0 : aa * (h - piso) + ab * ((h - 1971) ** 2 - (piso - 1971) ** 2) / 2;
    let amRestante = volAm(amC), amRitmo = Math.max(0, ctx.amaluzaRitmo || 0);
    const ccs = P.ccsFn || ccsMW;
    const inicio = ctx.inicio || new Date();
    let V = volOf(ctx.cota - COTA_CRIT);
    let Vv = V;   // volumen "virtual": sigue bajando como si hubiera agua bajo 2.115 (sirve para el rango)
    const VMAX = volOf(COTA_MAX - COTA_CRIT);
    const daily = []; let crossDay = null, firstDay = null;
    for (let step = 0; step <= H / dt; step++) {
      const t = step * dt;
      const dia = ((ctx.diaSemana0 != null ? ctx.diaSemana0 : inicio.getDay()) + Math.floor(t)) % 7;
      const qin = perfil(P.wPaute, t, P.qMazar, 66, ctx.serieMazar);
      const qcoca = perfil(P.wCoca, t, P.qCoca, 280, ctx.serieCoca);
      // Las demás hidroeléctricas siguen al caudal de la Amazonía norte (río Coca), no al de Mazar,
      // que parte de un caudal tan bajo que cualquier lluvia lo multiplica.
      const rainF = Math.min(1.35, Math.max(0.8, qcoca / P.qCoca));
      const kd = Math.floor(t);
      const plan = ctx.cutPlan && ctx.cutPlan[kd];
      const cutHoy = (plan != null && plan !== false) ? +plan : ((!ctx.cutDias || ctx.cutDias[dia]) ? P.cut : 0);
      const demand = P.demanda + ((ctx.deltaDia && ctx.deltaDia[dia]) || 0) - cutHoy;
      const ccsT = ccs(qcoca);
      const other = P.other * rainF;
      const req = demand - ccsT - other - P.therm - P.imp;
      const cotaAhora = COTA_CRIT + xOf(V);
      const kmz = 0.00981 * eta * Math.max(20, cotaAhora - amC);
      const saque = Math.min(amRitmo * dt, amRestante); amRestante -= saque;
      const qAm = saque / dt / 0.0864;                       // m³/s que salen de Amaluza
      const intermedio = beta * qin + qAm;                   // agua que Molino y Sopladora tienen sin tocar Mazar
      let paute, deficit = 0, qturb;
      { const pv = Math.min(Math.max(req, 0), PAUTE_MAX);
        const kmzv = 0.00981 * eta * Math.max(20, COTA_CRIT + (Vv > 0 ? xOf(Vv) : Vv / A()) - amC);
        Vv = Math.min(VMAX, Vv + (qin - Math.max(0, (pv - kms * intermedio) / (kmzv + kms))) * 86400 * dt / 1e6); }
      if (V > 0) {
        paute = Math.min(Math.max(req, 0), PAUTE_MAX);
        deficit = Math.max(0, req - PAUTE_MAX);
        qturb = Math.max(0, (paute - kms * intermedio) / (kmz + kms));
        const Vprev = V;
        V += (qin - qturb) * 86400 * dt / 1e6;
        if (V > VMAX) V = VMAX;
        if (V <= 0 && crossDay === null) { crossDay = t + dt * (Vprev / (Vprev - V)); V = 0; }
      } else {
        const filo = qin * (kmz + kms) + kms * intermedio;   // lo que Paute genera solo con el río
        paute = Math.min(Math.max(req, 0), filo, PAUTE_MAX);
        deficit = Math.max(0, req - paute);
        qturb = Math.max(0, (paute - kms * intermedio) / (kmz + kms));
        V += Math.max(0, qin - qturb) * 86400 * dt / 1e6;
      }
      const rec = { t, cota: COTA_CRIT + xOf(V), cotaV: COTA_CRIT + (Vv > 0 ? xOf(Vv) : Vv / A()), qin, qcoca, demand, ccs: ccsT, other, therm: P.therm, imp: P.imp, paute, deficit, req, qturb };
      if (step === 0) firstDay = rec;
      if (Math.abs(t - Math.round(t)) < 1e-9) daily.push(rec);
    }
    return { daily, crossDay, firstDay };
  }

  /* Rango probable: en pruebas con fechas pasadas (2023–2026) se comparó la bajada real con la predicha.
     cuantiles = {"7":[r25,r75], "14":[...], ...}: bajada real ÷ bajada predicha (mitad central de los casos).
     Se escala la trayectoria del modelo con esos factores y se busca cuándo cruzaría 2.115.
     Devuelve [mínimo, máximo] en días; null = no cruza en el horizonte. */
  function rango(R, cuantiles, cota0, umbral) {
    const U = umbral == null ? COTA_CRIT : umbral;
    if (!R || !cuantiles) return null;
    const hs = Object.keys(cuantiles).map(Number).sort((x, y) => x - y);
    const q = (t, i) => { let h = hs[0]; for (const k of hs) if (Math.abs(k - t) < Math.abs(h - t)) h = k; return cuantiles[String(h)][i]; };
    const cruza = i => {
      const d = R.daily;
      for (let k = 1; k < d.length; k++) {
        const c1 = cota0 - q(d[k].t, i) * (cota0 - d[k].cotaV);
        if (c1 <= U) {
          const c0 = cota0 - q(d[k - 1].t, i) * (cota0 - d[k - 1].cotaV);
          return d[k - 1].t + (c0 - U) / Math.max(1e-6, c0 - c1);
        }
      }
      return null;
    };
    if (cota0 <= U) return [0, 0];
    return [cruza(1), cruza(0)];
  }

  /* Probabilidad de que Mazar llegue a un umbral dentro de cada horizonte.
     percentiles = {"7":[p5, p10, …, p95], ...}: bajada real ÷ bajada predicha en las pruebas con fechas pasadas.
     Cada percentil escala la trayectoria del modelo; la probabilidad es la parte de esos 19 casos que cruza
     el umbral antes del horizonte. */
  function probabilidades(R, percentiles, cota0, umbral, horizontes) {
    if (!R || !percentiles) return null;
    const hs = Object.keys(percentiles).map(Number).sort((x, y) => x - y);
    const n = percentiles[String(hs[0])].length;
    const r = (t, i) => { let h = hs[0]; for (const k of hs) if (Math.abs(k - t) < Math.abs(h - t)) h = k; return percentiles[String(h)][i]; };
    const d = R.daily;
    const tiempos = [];
    for (let i = 0; i < n; i++) {
      let tc = null;
      if (cota0 <= umbral) tc = 0;
      for (let k = 1; k < d.length && tc === null; k++) {
        const c1 = cota0 - r(d[k].t, i) * (cota0 - d[k].cotaV);
        if (c1 <= umbral) {
          const c0 = cota0 - r(d[k - 1].t, i) * (cota0 - d[k - 1].cotaV);
          tc = d[k - 1].t + (c0 - umbral) / Math.max(1e-6, c0 - c1);
        }
      }
      tiempos.push(tc);
    }
    const out = {};
    for (const H of horizontes) out[H] = tiempos.filter(t => t !== null && t <= H).length / n;
    return out;
  }

  global.ModeloMazar = { probabilidades, configurar, simular, rango, perfil, ccsMW, volOf, xOf, areaEn, COTA_CRIT, COTA_MAX, PAUTE_MAX, parametros: () => PAR };
})(typeof window !== "undefined" ? window : globalThis);
