# Ideas para el laboratorio

Observaciones de Luis (o del auditor) que el auditor convierte en modelos candidatos. Lo más nuevo arriba.
Estados: pendiente → en sombra (id del candidato) → resultado.

- [30 oct · Luis: "muchos modelos sombra en paralelo"] Diagnóstico: el titular es pesimista y el sesgo crece con el plazo (−0,13 m a 1 día … −4,2 m a 7) y el error a 1 día está autocorrelacionado. → **en sombra (tanda Claude, aprobada por Gemini y por Claude independiente tras corregir topes del Paute)**: corrige_error_3, corrige_error_6, corrige_error_6_lento, sesgo_plazo_50, sesgo_plazo_100, cortes_siguen_7d (luis); autoajuste_completo, paute_ajuste_completo, coca_mitad, otros_rios_planos, dia_semana_suave, humedo_completo (auto). Pendiente sugerido por el revisor: sesgo por plazo solo con verificaciones desde el 28 oct.
- [30 oct · prueba del ciclo] "No proyectar el paro de Coca Codo" (sin_paro_coca): Gemini APROBÓ, Claude independiente RECHAZÓ: `ccsFactor` mezcla el paro de hoy con el riesgo de crecida de los días 1–14, así que quitarlo entero mide dos cosas a la vez. → **en sombra: sin_paro_hoy** (30 oct, propuesto por Gemini como segundo auditor: divide `ccsFactor` entre `ccs_paro.factor` y conserva la crecida; revisor Claude APROBÓ; prueba con el paro real del 29 oct 02:00: titular −74 cm, candidato −9 cm a 1 día; promoción "luis").

- [30 oct · Luis] Guayaquil tiene muy pocas estaciones públicas (5–6); un aguacero de barrio (Durán 50 mm/h el 29 oct) no lo ve ningún modelo. → pendiente (clima: ¿pesar más aeropuerto y estación más lluviosa en la Costa?)
- [29 oct · auditoría] El modelo es pesimista a 7 días por cómo baja a Coca Codo. → en sombra: coca_rio_real
- [28 oct · Luis] Los paros de Coca Codo por sedimentos hacen que Paute cubra de golpe. → aplicado (paro solo ese día); seguir midiendo con importancia_1d (paro_coca)
