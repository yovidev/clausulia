# Evaluación de la recuperación

- Fecha: 2026-11-03 20:37 UTC
- Modelo de embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensiones, fastembed/ONNX, CPU)
- Preguntas: 20 (16 con respuesta, 4 sin respuesta)
- Hybrid: 20 candidatos por rama, RRF k=60
- Overlap: 15% del chunk_size
- Vectorizar una pregunta (no incluido en la latencia): 11.1 ms de media

Métricas: hit@k = el archivo y la página esperados están entre los k primeros; MRR = media de 1/posición del primer acierto (0 si no está); útil@k = el acierto además pasa el umbral (es lo que llegaría al LLM); rechazo correcto = preguntas sin respuesta sin ningún chunk relevante; falso rechazo = preguntas con respuesta sin ningún chunk relevante; margen = rebaja del umbral para chunks que coinciden por palabras (solo hybrid); latencia = búsqueda en Postgres, sin vectorizar la pregunta.

## Ingesta

- chunk_size 500: contrato_limpieza_brillo.pdf ready (6 chunks), contrato_logistica_andinos.pdf ready (7 chunks), contrato_mantenimiento_escaneado.pdf failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf ready (7 chunks), contrato_suministro_andinos.pdf ready (11 chunks), contrato_transporte_penalara.pdf ready (7 chunks)
- chunk_size 1000: contrato_limpieza_brillo.pdf ready (4 chunks), contrato_logistica_andinos.pdf ready (4 chunks), contrato_mantenimiento_escaneado.pdf failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf ready (4 chunks), contrato_suministro_andinos.pdf ready (5 chunks), contrato_transporte_penalara.pdf ready (4 chunks)

## Resultados

| modo | chunk | overlap | k | umbral | margen | hit@k | MRR | útil@k | rechazo correcto | falso rechazo | latencia (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| vector | 500 | 75 | 4 | 0.35 | – | 81% | 0.573 | 81% | 0% | 0% | 32.7 |
| vector | 500 | 75 | 4 | 0.45 | – | 81% | 0.573 | 81% | 25% | 0% | 23.1 |
| vector | 500 | 75 | 4 | 0.50 | – | 81% | 0.573 | 69% | 75% | 6% | 20.6 |
| vector | 500 | 75 | 4 | 0.55 | – | 81% | 0.573 | 56% | 75% | 19% | 22.4 |
| vector | 500 | 75 | 6 | 0.35 | – | 81% | 0.573 | 81% | 0% | 0% | 20.8 |
| vector | 500 | 75 | 6 | 0.45 | – | 81% | 0.573 | 81% | 25% | 0% | 22.2 |
| vector | 500 | 75 | 6 | 0.50 | – | 81% | 0.573 | 69% | 75% | 6% | 22.7 |
| vector | 500 | 75 | 6 | 0.55 | – | 81% | 0.573 | 56% | 75% | 19% | 21.9 |
| hybrid | 500 | 75 | 4 | 0.35 | 0.00 | 88% | 0.630 | 88% | 0% | 0% | 68.1 |
| hybrid | 500 | 75 | 4 | 0.35 | 0.05 | 88% | 0.630 | 88% | 0% | 0% | 63.7 |
| hybrid | 500 | 75 | 4 | 0.35 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 66.6 |
| hybrid | 500 | 75 | 4 | 0.45 | 0.00 | 88% | 0.630 | 88% | 25% | 0% | 65.7 |
| hybrid | 500 | 75 | 4 | 0.45 | 0.05 | 88% | 0.630 | 88% | 0% | 0% | 65.7 |
| hybrid | 500 | 75 | 4 | 0.45 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 65.7 |
| hybrid | 500 | 75 | 4 | 0.50 | 0.00 | 88% | 0.630 | 75% | 75% | 6% | 62.7 |
| hybrid | 500 | 75 | 4 | 0.50 | 0.05 | 88% | 0.630 | 88% | 25% | 0% | 67.0 |
| hybrid | 500 | 75 | 4 | 0.50 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 67.2 |
| hybrid | 500 | 75 | 4 | 0.55 | 0.00 | 88% | 0.630 | 56% | 75% | 19% | 66.1 |
| hybrid | 500 | 75 | 4 | 0.55 | 0.05 | 88% | 0.630 | 75% | 75% | 6% | 63.7 |
| hybrid | 500 | 75 | 4 | 0.55 | 0.10 | 88% | 0.630 | 88% | 25% | 0% | 65.7 |
| hybrid | 500 | 75 | 6 | 0.35 | 0.00 | 88% | 0.630 | 88% | 0% | 0% | 67.3 |
| hybrid | 500 | 75 | 6 | 0.35 | 0.05 | 88% | 0.630 | 88% | 0% | 0% | 101.4 |
| hybrid | 500 | 75 | 6 | 0.35 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 76.3 |
| hybrid | 500 | 75 | 6 | 0.45 | 0.00 | 88% | 0.630 | 88% | 25% | 0% | 68.4 |
| hybrid | 500 | 75 | 6 | 0.45 | 0.05 | 88% | 0.630 | 88% | 0% | 0% | 68.4 |
| hybrid | 500 | 75 | 6 | 0.45 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 70.4 |
| hybrid | 500 | 75 | 6 | 0.50 | 0.00 | 88% | 0.630 | 75% | 75% | 6% | 95.7 |
| hybrid | 500 | 75 | 6 | 0.50 | 0.05 | 88% | 0.630 | 88% | 25% | 0% | 69.5 |
| hybrid | 500 | 75 | 6 | 0.50 | 0.10 | 88% | 0.630 | 88% | 0% | 0% | 84.9 |
| hybrid | 500 | 75 | 6 | 0.55 | 0.00 | 88% | 0.630 | 56% | 75% | 19% | 69.1 |
| hybrid | 500 | 75 | 6 | 0.55 | 0.05 | 88% | 0.630 | 75% | 75% | 6% | 68.5 |
| hybrid | 500 | 75 | 6 | 0.55 | 0.10 | 88% | 0.630 | 88% | 25% | 0% | 68.1 |
| vector | 1000 | 150 | 4 | 0.35 | – | 62% | 0.479 | 62% | 0% | 0% | 24.2 |
| vector | 1000 | 150 | 4 | 0.45 | – | 62% | 0.479 | 62% | 25% | 0% | 23.7 |
| vector | 1000 | 150 | 4 | 0.50 | – | 62% | 0.479 | 50% | 100% | 0% | 24.9 |
| vector | 1000 | 150 | 4 | 0.55 | – | 62% | 0.479 | 38% | 100% | 25% | 30.8 |
| vector | 1000 | 150 | 6 | 0.35 | – | 81% | 0.515 | 81% | 0% | 0% | 29.6 |
| vector | 1000 | 150 | 6 | 0.45 | – | 81% | 0.515 | 81% | 25% | 0% | 27.0 |
| vector | 1000 | 150 | 6 | 0.50 | – | 81% | 0.515 | 56% | 100% | 0% | 24.5 |
| vector | 1000 | 150 | 6 | 0.55 | – | 81% | 0.515 | 38% | 100% | 25% | 27.1 |
| hybrid | 1000 | 150 | 4 | 0.35 | 0.00 | 88% | 0.620 | 88% | 0% | 0% | 73.7 |
| hybrid | 1000 | 150 | 4 | 0.35 | 0.05 | 88% | 0.620 | 88% | 0% | 0% | 70.9 |
| hybrid | 1000 | 150 | 4 | 0.35 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 69.0 |
| hybrid | 1000 | 150 | 4 | 0.45 | 0.00 | 88% | 0.620 | 81% | 25% | 0% | 77.0 |
| hybrid | 1000 | 150 | 4 | 0.45 | 0.05 | 88% | 0.620 | 88% | 0% | 0% | 78.9 |
| hybrid | 1000 | 150 | 4 | 0.45 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 69.2 |
| hybrid | 1000 | 150 | 4 | 0.50 | 0.00 | 88% | 0.620 | 56% | 100% | 0% | 67.7 |
| hybrid | 1000 | 150 | 4 | 0.50 | 0.05 | 88% | 0.620 | 81% | 25% | 0% | 72.0 |
| hybrid | 1000 | 150 | 4 | 0.50 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 75.0 |
| hybrid | 1000 | 150 | 4 | 0.55 | 0.00 | 88% | 0.620 | 38% | 100% | 31% | 72.1 |
| hybrid | 1000 | 150 | 4 | 0.55 | 0.05 | 88% | 0.620 | 56% | 100% | 0% | 77.6 |
| hybrid | 1000 | 150 | 4 | 0.55 | 0.10 | 88% | 0.620 | 81% | 25% | 0% | 71.5 |
| hybrid | 1000 | 150 | 6 | 0.35 | 0.00 | 88% | 0.620 | 88% | 0% | 0% | 78.9 |
| hybrid | 1000 | 150 | 6 | 0.35 | 0.05 | 88% | 0.620 | 88% | 0% | 0% | 75.7 |
| hybrid | 1000 | 150 | 6 | 0.35 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 67.2 |
| hybrid | 1000 | 150 | 6 | 0.45 | 0.00 | 88% | 0.620 | 81% | 25% | 0% | 69.6 |
| hybrid | 1000 | 150 | 6 | 0.45 | 0.05 | 88% | 0.620 | 88% | 0% | 0% | 79.3 |
| hybrid | 1000 | 150 | 6 | 0.45 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 71.4 |
| hybrid | 1000 | 150 | 6 | 0.50 | 0.00 | 88% | 0.620 | 56% | 100% | 0% | 68.9 |
| hybrid | 1000 | 150 | 6 | 0.50 | 0.05 | 88% | 0.620 | 81% | 25% | 0% | 72.0 |
| hybrid | 1000 | 150 | 6 | 0.50 | 0.10 | 88% | 0.620 | 88% | 0% | 0% | 68.9 |
| hybrid | 1000 | 150 | 6 | 0.55 | 0.00 | 88% | 0.620 | 38% | 100% | 31% | 66.7 |
| hybrid | 1000 | 150 | 6 | 0.55 | 0.05 | 88% | 0.620 | 56% | 100% | 0% | 67.0 |
| hybrid | 1000 | 150 | 6 | 0.55 | 0.10 | 88% | 0.620 | 81% | 25% | 0% | 67.5 |

## Detalle por pregunta (k=6)

Posición del primer acierto (– si no está en los 6 primeros), similitud coseno de ese chunk y, entre corchetes, la del mejor chunk recuperado. No dependen del umbral.

| pregunta | tipo | vector 500 | hybrid 500 | vector 1000 | hybrid 1000 |
|---|---|---:|---:|---:|---:|
| q01 ¿Cuándo termina la vigencia inicial del contrato marco con Suministros Andinos? | exacta | 1 (0.70) [0.70] | 1 (0.70) [0.70] | 3 (0.61) [0.62] | 2 (0.61) [0.62] |
| q02 ¿El acuerdo de material de oficina sigue en vigor si nadie dice nada al terminar? | semantica | 3 (0.52) [0.60] | 1 (0.52) [0.60] | 5 (0.48) [0.61] | 1 (0.48) [0.61] |
| q03 ¿Con cuánta antelación hay que avisar a Suministros Andinos para dejar de trabajar con ellos? | semantica | 2 (0.49) [0.55] | – [0.55] | 2 (0.50) [0.54] | – [0.54] |
| q04 ¿Qué porcentaje se cobra por cada semana de demora en un pedido de papelería? | exacta | 1 (0.62) [0.62] | 1 (0.62) [0.62] | 6 (0.48) [0.60] | 3 (0.48) [0.60] |
| q05 ¿Cuánto tiempo hay que seguir guardando el secreto cuando acabe el contrato de suministro de oficina? | semantica | 1 (0.76) [0.76] | 1 (0.76) [0.76] | 1 (0.77) [0.77] | 1 (0.77) [0.77] |
| q06 ¿En qué juzgados se resolvería un pleito sobre el suministro de material de oficina? | exacta | 2 (0.49) [0.50] | 4 (0.49) [0.50] | 2 (0.49) [0.51] | 3 (0.49) [0.51] |
| q07 ¿Cuánto debe abonar el operador logístico por cada día que se retrase la salida de un pedido? | exacta | 3 (0.74) [0.77] | 2 (0.74) [0.77] | 1 (0.75) [0.75] | 1 (0.75) [0.75] |
| q08 ¿El servicio de almacenaje se renueva solo o hay que firmar algo nuevo? | semantica | 1 (0.57) [0.57] | 1 (0.57) [0.57] | 1 (0.55) [0.55] | 1 (0.55) [0.55] |
| q09 ¿En qué plazo se pagan las facturas de logística? | exacta | – [0.64] | 4 (0.52) [0.64] | – [0.61] | 4 (0.43) [0.61] |
| q10 ¿Cuál es el límite de las penalizaciones de Transportes Peñalara? | exacta | 1 (0.61) [0.61] | 1 (0.61) [0.61] | 1 (0.61) [0.61] | 1 (0.61) [0.61] |
| q11 ¿Hasta qué fecha está vigente el contrato con Peñalara? | exacta | – [0.58] | – [0.58] | – [0.56] | – [0.54] |
| q12 ¿Cómo y cuándo cobra el transportista sus servicios? | semantica | 4 (0.58) [0.69] | 3 (0.58) [0.69] | 3 (0.54) [0.68] | 2 (0.54) [0.68] |
| q13 ¿Qué pasa si el ERP no está funcionando el 30 de junio de 2026? | exacta | 4 (0.50) [0.54] | 2 (0.50) [0.54] | 5 (0.50) [0.55] | 2 (0.50) [0.55] |
| q14 ¿Con cuánta antelación se puede dar de baja la suscripción del programa de gestión? | semantica | 1 (0.67) [0.67] | 1 (0.67) [0.67] | 1 (0.67) [0.67] | 1 (0.67) [0.67] |
| q15 ¿Durante cuántos años después del contrato debe Nexoria mantener la confidencialidad? | exacta | – [0.64] | 4 (0.48) [0.64] | – [0.62] | 2 (0.48) [0.62] |
| q16 ¿Qué se descuenta si la empresa de limpieza se salta una limpieza programada? | semantica | 1 (0.60) [0.60] | 1 (0.60) [0.60] | 1 (0.62) [0.62] | 1 (0.62) [0.62] |
| u1 ¿Qué seguro de responsabilidad civil debe tener contratado el transportista? | sin_respuesta | – [0.62] | – [0.62] | – [0.49] | – [0.49] |
| u2 ¿Cuál es el horario del soporte técnico de la plataforma ERP? | sin_respuesta | – [0.48] | – [0.48] | – [0.48] | – [0.48] |
| u3 ¿Cuántos trabajadores destinará la empresa de limpieza a nuestras oficinas? | sin_respuesta | – [0.44] | – [0.44] | – [0.45] | – [0.45] |
| u4 ¿Qué tarifa por kilómetro cobra el transportista? | sin_respuesta | – [0.48] | – [0.48] | – [0.46] | – [0.46] |
