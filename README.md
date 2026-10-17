# Simulador Mazar

Simulador interactivo de cuántos días faltan para que el embalse Mazar (Paute Integral, Ecuador) llegue a su cota crítica de 2.115 msnm, según el caudal de Mazar y de Coca Codo Sinclair, la demanda nacional, los cortes a empresas, la temperatura de la Costa, la generación térmica y la importación desde Colombia.

Página: https://luiscampozano.github.io/simulador-mazar/

## Archivos

- `index.html`: la página y el modelo.
- `datos.json`: los datos del día. Es lo único que cambia en cada actualización.
  - `cota`, `fecha`, `etiqueta`, `historico`: nivel de Mazar.
  - `hoy`: valores iniciales de los controles.
  - `notas`: textos bajo cada control.
  - `manual`: lo que fija Claude a partir de noticias (cortes a empresas y, si hace falta, un escenario de lluvia o temperatura con fecha de vencimiento `_hasta`). El robot siempre lo respeta.
  - `robot`: estado de cada fuente y registro de la última ejecución.
- `serie_cenace.json`: memoria del robot con los datos de Cenace por media hora de los últimos 3 días.
- `scripts/robot.py`: el robot.
- `.github/workflows/robot-cota.yml`: horario del robot y publicación de la página.

## Quién actualiza qué

| Variable | Fuente | Quién |
|---|---|---|
| Cota de Mazar y caudal de entrada | Servicio de datos del panel de Celec Sur | Robot, cada 2 h |
| Térmica, importación desde Colombia, demanda, Coca Codo | Página "Información Operativa" de Cenace (cada media hora) | Robot, cada 2 h |
| Temperatura en Guayaquil, lluvia en las cuencas del Paute y del Coca | Open-Meteo | Robot, cada 2 h |
| Otras hidroeléctricas | Calculada para que el modelo reproduzca la variación real de la cota en 24 h | Robot, cada 2 h |
| Cortes a empresas | Noticias y anuncios oficiales | Claude, 09:45 y 21:45 |
| Revisión general y correcciones | Todas las anteriores | Claude, 09:45 y 21:45 |

Escenario de lluvia automático (lluvia acumulada de 7 días, Open-Meteo): menos de 15 mm previstos = seco; más de 70 mm previstos y más de 40 mm en la semana anterior = lluvia sostenida; en otro caso = pulso de lluvia.

Cada cambio en `main` vuelve a publicar la página automáticamente.

El modelo usa promedios diarios y una curva cota–volumen aproximada; ver la sección "Cómo calcula el modelo" en la página.
