# Simulador Mazar

Simulador interactivo de cuántos días faltan para que el embalse Mazar (Paute Integral, Ecuador) llegue a su cota crítica de 2.115 msnm, según el caudal de Mazar y de Coca Codo Sinclair, la demanda nacional, los cortes a empresas, la temperatura de la Costa, la generación térmica y la importación desde Colombia.

Página: https://luiscampozano.github.io/simulador-mazar/

## Cómo se actualiza

- `index.html`: la página y el modelo. No hace falta tocarla para la actualización diaria.
- `datos.json`: los datos del día. Para actualizar, se cambia solo este archivo:
  - `fecha` y `etiqueta`: fecha y hora del registro.
  - `cota`: cota de Mazar en msnm (Celec Sur).
  - `historico`: lista de `["AAAA-MM-DD", cota]`; se agrega un punto por día.
  - `hoy`: valores iniciales de los controles (caudales en m³/s, MW, °C).
  - `notas`: textos que se muestran bajo los controles de Mazar, Coca Codo e importación, y la calibración.

Fuentes de datos: Celec Sur (panel hidrológico), Cenace (producción en tiempo real), Inamhi (pronósticos) y prensa nacional.

El modelo usa promedios diarios y una curva cota–volumen aproximada; ver la sección "Cómo calcula el modelo" en la página.
