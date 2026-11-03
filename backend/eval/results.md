# Evaluación de la recuperación

- Fecha: 2026-11-03 20:51 UTC
- Modelo de embeddings: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensiones, fastembed/ONNX, CPU)
- Preguntas: 20 (16 con respuesta, 4 sin respuesta), en `eval/questions.yaml`
- Documentos: `samples/` (5 contratos con texto y 1 escaneado); hybrid con 20 candidatos por rama y RRF k=60
- Overlap: 15% del chunk_size
- Vectorizar una pregunta (no incluido en la latencia): 13.6 ms de media

Métricas:

- hit@k: el archivo y la página esperados están entre los k chunks recuperados.
- MRR: media de 1/posición del primer acierto (0 si no está entre los k).
- útil@k: hay acierto y además el mejor chunk pasa el umbral, así que el LLM lo recibiría.
- rechazo correcto: preguntas sin respuesta cuyo mejor chunk no llega al umbral (no se llama al LLM).
- falso rechazo: preguntas con respuesta cuyo mejor chunk no llega al umbral.
- título: cabecera `Documento: <nombre>` antepuesta al vectorizar (EMBED_DOCUMENT_TITLE).
- latencia: búsqueda en Postgres, sin vectorizar la pregunta.

## Configuración elegida

RETRIEVAL_MODE=hybrid, CHUNK_SIZE=1000, CHUNK_OVERLAP=150, RETRIEVAL_K=6, SIMILARITY_THRESHOLD=0.50, EMBED_DOCUMENT_TITLE=false. El umbral solo decide si se llama al LLM (con la similitud del mejor chunk); si se llama, recibe los k.

| modo | chunk | overlap | k | umbral | título | hit@k | MRR | útil@k | rechazo correcto | falso rechazo | latencia (ms) |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| hybrid | 1000 | 150 | 6 | 0.50 | no | 88% | 0.620 | 88% | 100% | 0% | 62.4 |
| hybrid | 1000 | 150 | 6 | 0.50 | sí | 88% | 0.684 | 88% | 50% | 0% | 66.6 |

Separación con esta configuración: el peor «mejor chunk» de una pregunta con respuesta menos el mejor de una sin respuesta = +0.02.

Cabecera con el título del documento: hit@k 88% → 88%, MRR 0.620 → 0.684, rechazo correcto 100% → 50%. Criterio: activarla solo si mejora hit@k o MRR sin empeorar el rechazo correcto; se deja desactivada.

## Ingesta

- chunk_size 500, título no: contrato_limpieza_brillo.pdf: 6 chunks, contrato_logistica_andinos.pdf: 7 chunks, contrato_mantenimiento_escaneado.pdf: failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf: 7 chunks, contrato_suministro_andinos.pdf: 11 chunks, contrato_transporte_penalara.pdf: 7 chunks
- chunk_size 500, título sí: contrato_limpieza_brillo.pdf: 6 chunks, contrato_logistica_andinos.pdf: 7 chunks, contrato_mantenimiento_escaneado.pdf: failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf: 7 chunks, contrato_suministro_andinos.pdf: 11 chunks, contrato_transporte_penalara.pdf: 7 chunks
- chunk_size 1000, título no: contrato_limpieza_brillo.pdf: 4 chunks, contrato_logistica_andinos.pdf: 4 chunks, contrato_mantenimiento_escaneado.pdf: failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf: 4 chunks, contrato_suministro_andinos.pdf: 5 chunks, contrato_transporte_penalara.pdf: 4 chunks
- chunk_size 1000, título sí: contrato_limpieza_brillo.pdf: 4 chunks, contrato_logistica_andinos.pdf: 4 chunks, contrato_mantenimiento_escaneado.pdf: failed (NO_TEXT_LAYER), contrato_software_nexoria.pdf: 4 chunks, contrato_suministro_andinos.pdf: 5 chunks, contrato_transporte_penalara.pdf: 4 chunks

## Resultados completos

| modo | chunk | overlap | k | umbral | título | hit@k | MRR | útil@k | rechazo correcto | falso rechazo | latencia (ms) |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| vector | 500 | 75 | 4 | 0.35 | no | 81% | 0.573 | 81% | 0% | 0% | 36.9 |
| vector | 500 | 75 | 4 | 0.45 | no | 81% | 0.573 | 81% | 25% | 0% | 21.2 |
| vector | 500 | 75 | 4 | 0.50 | no | 81% | 0.573 | 75% | 75% | 6% | 21.4 |
| vector | 500 | 75 | 4 | 0.55 | no | 81% | 0.573 | 62% | 75% | 19% | 22.1 |
| vector | 500 | 75 | 6 | 0.35 | no | 81% | 0.573 | 81% | 0% | 0% | 20.9 |
| vector | 500 | 75 | 6 | 0.45 | no | 81% | 0.573 | 81% | 25% | 0% | 21.8 |
| vector | 500 | 75 | 6 | 0.50 | no | 81% | 0.573 | 75% | 75% | 6% | 22.6 |
| vector | 500 | 75 | 6 | 0.55 | no | 81% | 0.573 | 62% | 75% | 19% | 26.8 |
| hybrid | 500 | 75 | 4 | 0.35 | no | 88% | 0.630 | 88% | 0% | 0% | 69.5 |
| hybrid | 500 | 75 | 4 | 0.45 | no | 88% | 0.630 | 88% | 25% | 0% | 67.9 |
| hybrid | 500 | 75 | 4 | 0.50 | no | 88% | 0.630 | 81% | 75% | 6% | 64.6 |
| hybrid | 500 | 75 | 4 | 0.55 | no | 88% | 0.630 | 75% | 75% | 19% | 65.6 |
| hybrid | 500 | 75 | 6 | 0.35 | no | 88% | 0.630 | 88% | 0% | 0% | 66.5 |
| hybrid | 500 | 75 | 6 | 0.45 | no | 88% | 0.630 | 88% | 25% | 0% | 64.2 |
| hybrid | 500 | 75 | 6 | 0.50 | no | 88% | 0.630 | 81% | 75% | 6% | 67.6 |
| hybrid | 500 | 75 | 6 | 0.55 | no | 88% | 0.630 | 75% | 75% | 19% | 68.7 |
| vector | 500 | 75 | 4 | 0.35 | sí | 94% | 0.646 | 94% | 0% | 0% | 20.9 |
| vector | 500 | 75 | 4 | 0.45 | sí | 94% | 0.646 | 94% | 0% | 0% | 21.8 |
| vector | 500 | 75 | 4 | 0.50 | sí | 94% | 0.646 | 88% | 25% | 6% | 20.8 |
| vector | 500 | 75 | 4 | 0.55 | sí | 94% | 0.646 | 88% | 50% | 6% | 21.6 |
| vector | 500 | 75 | 6 | 0.35 | sí | 100% | 0.658 | 100% | 0% | 0% | 20.5 |
| vector | 500 | 75 | 6 | 0.45 | sí | 100% | 0.658 | 100% | 0% | 0% | 20.3 |
| vector | 500 | 75 | 6 | 0.50 | sí | 100% | 0.658 | 94% | 25% | 6% | 21.3 |
| vector | 500 | 75 | 6 | 0.55 | sí | 100% | 0.658 | 94% | 50% | 6% | 21.4 |
| hybrid | 500 | 75 | 4 | 0.35 | sí | 94% | 0.682 | 94% | 0% | 0% | 63.9 |
| hybrid | 500 | 75 | 4 | 0.45 | sí | 94% | 0.682 | 94% | 0% | 0% | 64.3 |
| hybrid | 500 | 75 | 4 | 0.50 | sí | 94% | 0.682 | 88% | 25% | 6% | 61.0 |
| hybrid | 500 | 75 | 4 | 0.55 | sí | 94% | 0.682 | 88% | 50% | 12% | 64.3 |
| hybrid | 500 | 75 | 6 | 0.35 | sí | 100% | 0.693 | 100% | 0% | 0% | 67.5 |
| hybrid | 500 | 75 | 6 | 0.45 | sí | 100% | 0.693 | 100% | 0% | 0% | 64.3 |
| hybrid | 500 | 75 | 6 | 0.50 | sí | 100% | 0.693 | 94% | 25% | 6% | 63.4 |
| hybrid | 500 | 75 | 6 | 0.55 | sí | 100% | 0.693 | 94% | 50% | 6% | 64.4 |
| vector | 1000 | 150 | 4 | 0.35 | no | 62% | 0.479 | 62% | 0% | 0% | 21.3 |
| vector | 1000 | 150 | 4 | 0.45 | no | 62% | 0.479 | 62% | 25% | 0% | 21.8 |
| vector | 1000 | 150 | 4 | 0.50 | no | 62% | 0.479 | 62% | 100% | 0% | 20.9 |
| vector | 1000 | 150 | 4 | 0.55 | no | 62% | 0.479 | 44% | 100% | 25% | 20.7 |
| vector | 1000 | 150 | 6 | 0.35 | no | 81% | 0.515 | 81% | 0% | 0% | 20.7 |
| vector | 1000 | 150 | 6 | 0.45 | no | 81% | 0.515 | 81% | 25% | 0% | 20.3 |
| vector | 1000 | 150 | 6 | 0.50 | no | 81% | 0.515 | 81% | 100% | 0% | 21.1 |
| vector | 1000 | 150 | 6 | 0.55 | no | 81% | 0.515 | 56% | 100% | 25% | 22.0 |
| hybrid | 1000 | 150 | 4 | 0.35 | no | 88% | 0.620 | 88% | 0% | 0% | 63.4 |
| hybrid | 1000 | 150 | 4 | 0.45 | no | 88% | 0.620 | 88% | 25% | 0% | 62.3 |
| hybrid | 1000 | 150 | 4 | 0.50 | no | 88% | 0.620 | 88% | 100% | 0% | 63.3 |
| hybrid | 1000 | 150 | 4 | 0.55 | no | 88% | 0.620 | 69% | 100% | 31% | 65.8 |
| hybrid | 1000 | 150 | 6 | 0.35 | no | 88% | 0.620 | 88% | 0% | 0% | 62.3 |
| hybrid | 1000 | 150 | 6 | 0.45 | no | 88% | 0.620 | 88% | 25% | 0% | 64.4 |
| hybrid | 1000 | 150 | 6 | 0.50 | no | 88% | 0.620 | 88% | 100% | 0% | 62.4 |
| hybrid | 1000 | 150 | 6 | 0.55 | no | 88% | 0.620 | 69% | 100% | 31% | 62.9 |
| vector | 1000 | 150 | 4 | 0.35 | sí | 81% | 0.531 | 81% | 0% | 0% | 21.8 |
| vector | 1000 | 150 | 4 | 0.45 | sí | 81% | 0.531 | 81% | 0% | 0% | 23.6 |
| vector | 1000 | 150 | 4 | 0.50 | sí | 81% | 0.531 | 81% | 50% | 0% | 21.6 |
| vector | 1000 | 150 | 4 | 0.55 | sí | 81% | 0.531 | 56% | 100% | 25% | 20.9 |
| vector | 1000 | 150 | 6 | 0.35 | sí | 88% | 0.542 | 88% | 0% | 0% | 20.5 |
| vector | 1000 | 150 | 6 | 0.45 | sí | 88% | 0.542 | 88% | 0% | 0% | 21.1 |
| vector | 1000 | 150 | 6 | 0.50 | sí | 88% | 0.542 | 88% | 50% | 0% | 20.7 |
| vector | 1000 | 150 | 6 | 0.55 | sí | 88% | 0.542 | 62% | 100% | 25% | 21.8 |
| hybrid | 1000 | 150 | 4 | 0.35 | sí | 81% | 0.672 | 81% | 0% | 0% | 61.8 |
| hybrid | 1000 | 150 | 4 | 0.45 | sí | 81% | 0.672 | 81% | 0% | 0% | 62.8 |
| hybrid | 1000 | 150 | 4 | 0.50 | sí | 81% | 0.672 | 81% | 50% | 0% | 63.3 |
| hybrid | 1000 | 150 | 4 | 0.55 | sí | 81% | 0.672 | 62% | 100% | 31% | 64.8 |
| hybrid | 1000 | 150 | 6 | 0.35 | sí | 88% | 0.684 | 88% | 0% | 0% | 63.4 |
| hybrid | 1000 | 150 | 6 | 0.45 | sí | 88% | 0.684 | 88% | 0% | 0% | 63.3 |
| hybrid | 1000 | 150 | 6 | 0.50 | sí | 88% | 0.684 | 88% | 50% | 0% | 66.6 |
| hybrid | 1000 | 150 | 6 | 0.55 | sí | 88% | 0.684 | 69% | 100% | 31% | 61.7 |

## Detalle por pregunta (chunk 1000, k=6)

Posición del primer acierto (– si no está entre los k), similitud coseno de ese chunk y, entre corchetes, la del mejor chunk recuperado.

| pregunta | tipo | vector | hybrid | vector + título | hybrid + título |
|---|---|---:|---:|---:|---:|
| q01 ¿Cuándo termina la vigencia inicial del contrato marco con Suministros Andinos? | exacta | 3 (0.61) [0.62] | 2 (0.61) [0.62] | 4 (0.66) [0.67] | 1 (0.66) [0.67] |
| q02 ¿El acuerdo de material de oficina sigue en vigor si nadie dice nada al terminar? | semantica | 5 (0.48) [0.61] | 1 (0.48) [0.61] | 3 (0.52) [0.62] | 1 (0.52) [0.62] |
| q03 ¿Con cuánta antelación hay que avisar a Suministros Andinos para dejar de trabajar con ellos? | semantica | 2 (0.50) [0.54] | – [0.54] | 1 (0.55) [0.55] | – [0.53] |
| q04 ¿Qué porcentaje se cobra por cada semana de demora en un pedido de papelería? | exacta | 6 (0.48) [0.60] | 3 (0.48) [0.60] | – [0.56] | 5 (0.42) [0.56] |
| q05 ¿Cuánto tiempo hay que seguir guardando el secreto cuando acabe el contrato de suministro de oficina? | semantica | 1 (0.77) [0.77] | 1 (0.77) [0.77] | 1 (0.75) [0.75] | 1 (0.75) [0.75] |
| q06 ¿En qué juzgados se resolvería un pleito sobre el suministro de material de oficina? | exacta | 2 (0.49) [0.51] | 3 (0.49) [0.51] | 3 (0.46) [0.52] | 4 (0.46) [0.52] |
| q07 ¿Cuánto debe abonar el operador logístico por cada día que se retrase la salida de un pedido? | exacta | 1 (0.75) [0.75] | 1 (0.75) [0.75] | 1 (0.75) [0.75] | 1 (0.75) [0.75] |
| q08 ¿El servicio de almacenaje se renueva solo o hay que firmar algo nuevo? | semantica | 1 (0.55) [0.55] | 1 (0.55) [0.55] | 2 (0.52) [0.54] | 1 (0.52) [0.52] |
| q09 ¿En qué plazo se pagan las facturas de logística? | exacta | – [0.61] | 4 (0.43) [0.61] | 6 (0.51) [0.62] | 2 (0.51) [0.62] |
| q10 ¿Cuál es el límite de las penalizaciones de Transportes Peñalara? | exacta | 1 (0.61) [0.61] | 1 (0.61) [0.61] | 1 (0.65) [0.65] | 1 (0.65) [0.65] |
| q11 ¿Hasta qué fecha está vigente el contrato con Peñalara? | exacta | – [0.56] | – [0.54] | – [0.58] | – [0.54] |
| q12 ¿Cómo y cuándo cobra el transportista sus servicios? | semantica | 3 (0.54) [0.68] | 2 (0.54) [0.68] | 3 (0.56) [0.68] | 2 (0.56) [0.68] |
| q13 ¿Qué pasa si el ERP no está funcionando el 30 de junio de 2026? | exacta | 5 (0.50) [0.55] | 2 (0.50) [0.55] | 2 (0.51) [0.53] | 1 (0.51) [0.53] |
| q14 ¿Con cuánta antelación se puede dar de baja la suscripción del programa de gestión? | semantica | 1 (0.67) [0.67] | 1 (0.67) [0.67] | 1 (0.66) [0.66] | 1 (0.66) [0.66] |
| q15 ¿Durante cuántos años después del contrato debe Nexoria mantener la confidencialidad? | exacta | – [0.62] | 2 (0.48) [0.62] | 4 (0.51) [0.61] | 2 (0.51) [0.60] |
| q16 ¿Qué se descuenta si la empresa de limpieza se salta una limpieza programada? | semantica | 1 (0.62) [0.62] | 1 (0.62) [0.62] | 1 (0.63) [0.63] | 1 (0.63) [0.63] |
| u1 ¿Qué seguro de responsabilidad civil debe tener contratado el transportista? | sin_respuesta | – [0.49] | – [0.49] | – [0.50] | – [0.50] |
| u2 ¿Cuál es el horario del soporte técnico de la plataforma ERP? | sin_respuesta | – [0.48] | – [0.48] | – [0.51] | – [0.51] |
| u3 ¿Cuántos trabajadores destinará la empresa de limpieza a nuestras oficinas? | sin_respuesta | – [0.45] | – [0.45] | – [0.46] | – [0.46] |
| u4 ¿Qué tarifa por kilómetro cobra el transportista? | sin_respuesta | – [0.46] | – [0.46] | – [0.48] | – [0.48] |

## Limitaciones

- Conjunto pequeño: 20 preguntas sobre 5 contratos sintéticos y redactados para la prueba. Una pregunta equivale a 6% de hit@k: diferencias de una o dos preguntas entre configuraciones son ruido.
- Separación de +0.02 entre preguntas con y sin respuesta. El umbral 0.50 separa este conjunto, pero con documentos reales habrá preguntas a ambos lados: el LLM sigue siendo el segundo filtro (puede responder insufficient_evidence y las citas se validan).
- Las preguntas sin respuesta son del mismo dominio (seguros, horarios, tarifas): son las difíciles. No se midieron preguntas ajenas a los contratos.
- Preguntas que no encuentran su página con la configuración elegida: q03, q11. q03 (preaviso de Suministros Andinos, la del conflicto entre dos contratos) sufre en hybrid: el nombre del proveedor aparece en los encabezados y esos chunks suben por full-text. q11 (vigencia del contrato con Peñalara) necesita asociar la cláusula al proveedor, que solo se nombra en el encabezado.
- Sin `unaccent`: el full-text con la configuración `spanish` no iguala palabras con y sin tilde («penalizacion» no coincide con «penalización»). Añadirlo exige la extensión y una función inmutable para la columna generada.
- El full-text une los términos con OR y `ts_rank_cd` no pondera por rareza (no hay IDF): palabras comunes como «contrato» o «fecha» pesan tanto como un nombre propio.
- La latencia se midió con unas pocas decenas de chunks; no dice nada de miles.
