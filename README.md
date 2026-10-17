# Simulador Mazar

Simulador interactivo de cuántos días faltan para que el embalse Mazar (Paute Integral, Ecuador) llegue a su cota crítica de 2.115 msnm, según el caudal de Mazar y de Coca Codo Sinclair, la demanda nacional, los cortes a empresas, la temperatura de la Costa, la generación térmica y la importación desde Colombia.

Página: https://luiscampozano.github.io/simulador-mazar/

## Archivos

- `index.html`: la página y el modelo. No hace falta tocarla para las actualizaciones.
- `datos.json`: los datos del día. Es lo único que cambia en cada actualización:
  - `fecha` y `etiqueta`: fecha y hora de la última lectura.
  - `cota`: cota de Mazar en msnm.
  - `historico`: lista de `["AAAA-MM-DD", cota]`, un punto por día.
  - `hoy`: valores iniciales de los controles (caudales en m³/s, MW, °C).
  - `notas`: textos bajo los controles y la calibración.
  - `robot`: última lectura automática, caudal promedio de 24 h y variación de cota en 24 h.
- `scripts/robot_cota.py`: script del robot.
- `.github/workflows/robot-cota.yml`: horario del robot y publicación de la página.

## Quién actualiza qué

| Quién | Cuándo | Qué actualiza |
|---|---|---|
| Robot (GitHub Actions) | Cada 2 horas | Cota de Mazar, caudal de entrada promedio de 24 h, punto del día en el histórico. Fuente: servicio de datos del panel de Celec Sur. |
| Tarea de Claude, mañana | 09:45 (Ecuador) | Actualización completa: caudal del Coca, importación desde Colombia, cortes, temperatura, pronóstico y recalibración del modelo con la caída de 24 h. |
| Tarea de Claude, noche | 21:45 (Ecuador) | Importación, cortes, temperatura, pronóstico, caudal del Coca y notas. No recalibra. |

Cada cambio en `main` vuelve a publicar la página automáticamente.

Fuentes: Celec Sur (panel hidrológico), Cenace (producción en tiempo real), Inamhi (pronósticos) y prensa nacional.

El modelo usa promedios diarios y una curva cota–volumen aproximada; ver la sección "Cómo calcula el modelo" en la página.
