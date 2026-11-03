# Decisiones

Este documento crece con el proyecto. Esta primera versión recoge lo que decidí antes de escribir código: cómo entiendo el problema, el alcance y las herramientas. Las decisiones que dependen de medir (chunking, umbrales, búsqueda híbrida) las agrego cuando tenga datos.

## Cómo entiendo el problema

Los analistas de Clausulia necesitan encontrar cláusulas concretas (renovación, penalizaciones, jurisdicción) en cientos de contratos. Lo importante no es que el sistema responda siempre, sino que lo que responda se pueda verificar. Por eso doy prioridad a dos cosas: que cada respuesta cite documento y página, y que el sistema diga "no lo sé" cuando no tiene evidencia.

## Alcance y negocio

Aislamiento entre clientes. Lo modelo desde el inicio: cada documento pertenece a una organización y todas las búsquedas filtran por ella. En el MVP la organización llega por un header, sin autenticación. Sé que eso no es seguridad real, pero mezclar contratos de distintos clientes sería el peor error posible, y prefiero que el modelo de datos ya lo contemple.

Archivos duplicados. Identifico cada archivo por su hash SHA-256. Si la misma organización sube el mismo archivo, devuelvo el documento existente en lugar de crear otro.

Evidencia débil o contradictoria. Prefiero rechazar a inventar. Si no hay fragmentos suficientemente relevantes, la respuesta es "no hay evidencia suficiente". Si dos contratos se contradicen, muestro ambas versiones con sus citas, porque decidir cuál prevalece le corresponde al analista.

Preguntas independientes. El chat no tiene memoria de conversación en el MVP: cada pregunta se responde solo con los documentos.

## Arquitectura

La API recibe el PDF, lo valida, lo guarda y encola el procesamiento. No hace nada pesado, para poder responder rápido.

Un worker de Celery hace la extracción de texto, el chunking y los embeddings, y guarda todo en PostgreSQL con pgvector.

Las preguntas se responden en la API: búsqueda por similitud, llamada al LLM y validación de la respuesta.

El estado del procesamiento se actualiza en la interfaz con polling. Es lo más simple, y como una ingesta tarda varios segundos, unos segundos de retraso no se notan.

## Herramientas

FastAPI, Pydantic, Celery, Redis, PostgreSQL con pgvector y React las pide el enunciado.

Uso Python 3.12 en los contenedores porque algunas dependencias con binarios tardan en soportar la versión más nueva.

Uso uv para manejar las dependencias de Python porque es rápido y genera un lockfile reproducible.

Para extraer el texto de los PDF uso pypdf. Es liviano y da el texto por página, que es lo que necesito para citar. Docling es más completo, pero muy pesado para contratos que son sobre todo texto.

Los embeddings se generan con un modelo local (fastembed), porque el sistema tiene que funcionar sin claves de API.

Para el LLM uso una interfaz propia con un proveedor simulado para pruebas. Son pocas líneas y es fácil de probar. LiteLLM tendría sentido si hubiera que soportar muchos proveedores.

Jaeger es el visor de trazas, porque recibe OpenTelemetry directamente. Flower permite ver el estado de las tareas de Celery.

En el frontend uso pnpm en lugar de npm porque es más rápido y no permite usar dependencias que no declaré.

Ruff y mypy revisan el estilo y los tipos en el CI.

## Pendiente de decidir con datos

Tamaño de chunk, solapamiento, número de fragmentos a recuperar y umbral de similitud. También si agrego búsqueda híbrida y cómo calculo el nivel de confianza.

## Uso de IA

Uso Claude como apoyo durante todo el proyecto. En esta etapa lo usé para analizar el enunciado, comparar alternativas y redactar este documento a partir de las decisiones que tomé. Iré anotando aquí qué acepto, qué corrijo y por qué.
