# Decisiones
 
Este documento crece con el proyecto. Primero recoge cómo entiendo el problema y las decisiones de alcance y herramientas. Después, una sección por cada parte que voy implementando. Las decisiones que dependen de medir (chunking, umbrales, búsqueda híbrida) las agrego cuando tenga datos.
 
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
 
Uso Python 3.12 en los contenedores porque algunas dependencias con binarios tardan en soportar la versión más nueva. La versión está fijada en el archivo .python-version para que local y Docker coincidan.
 
Uso uv para manejar las dependencias de Python porque es rápido y genera un lockfile reproducible.
 
Para extraer el texto de los PDF uso pypdf. Es liviano y da el texto por página, que es lo que necesito para citar. Docling es más completo, pero muy pesado para contratos que son sobre todo texto.
 
Los embeddings se generan con un modelo local (fastembed), porque el sistema tiene que funcionar sin claves de API.
 
Para el LLM uso una interfaz propia con un proveedor simulado para pruebas. Son pocas líneas y es fácil de probar. LiteLLM tendría sentido si hubiera que soportar muchos proveedores.
 
Jaeger es el visor de trazas, porque recibe OpenTelemetry directamente. Flower permite ver el estado de las tareas de Celery.
 
En el frontend uso pnpm en lugar de npm porque es más rápido y no permite usar dependencias que no declaré.
 
Ruff y mypy revisan el estilo y los tipos en el CI. Uso mypy en modo estricto, salvo para los decoradores sin tipos, porque Celery no los tipa y daría falsos errores. En Ruff activé también las reglas de seguridad (las de Bandit), que detectan cosas como contraseñas escritas en el código.
 
## Docker e infraestructura
 
Una sola imagen para el backend. La API, el worker y Flower usan la misma imagen con distintos comandos, porque comparten el mismo código y las mismas dependencias.
 
En el Dockerfile instalo primero las dependencias y después copio el código. Así, si solo cambia el código, Docker reutiliza la capa de dependencias y no las vuelve a descargar. Con mi conexión esto pasó de media hora a segundos.
 
El contenedor corre con un usuario sin privilegios, no como root.
 
Postgres y Redis tienen healthchecks, para que la API y el worker esperen a que estén realmente listos y no solo arrancados.
 
Los puertos hacia mi máquina son 55432 para Postgres y 6380 para Redis, porque los habituales ya los usaban otros proyectos. Dentro de Docker los servicios se comunican por sus puertos normales, así que esto solo afecta al desarrollo local.
 
## Base de datos
 
Dos tablas: documents y chunks.
 
La restricción única por organización y hash impide que el mismo archivo se guarde dos veces, aunque lleguen dos subidas a la vez. La restricción única por documento e índice de chunk es la red de seguridad de la ingesta: aunque una tarea se ejecute dos veces, no puede haber chunks duplicados.
 
La búsqueda usa un índice HNSW con distancia coseno. Es un índice aproximado: mucho más rápido que comparar contra todos los chunks, a cambio de que en raros casos no devuelva el más cercano exacto. Dejé los parámetros por defecto de pgvector.
 
La dimensión del vector (384) es una constante del código y no una variable de entorno. Es parte del esquema: si se cambiara por configuración, la columna dejaría de coincidir con el modelo. Cambiarla exige una migración y reprocesar todos los documentos.
 
El estado del documento es un enum en Postgres, así la base rechaza cualquier valor que no sea pendiente, procesando, listo o fallido.
 
Guardo el número de intentos y la hora de inicio del procesamiento para poder detectar y rescatar documentos que se queden atascados.
 
El esquema se crea con migraciones de Alembic. La migración inicial también crea la extensión vector, para que funcione sobre una base completamente vacía, y al revertirla no deja tipos huérfanos. Lo probé borrando la extensión y aplicando la migración de nuevo.
 
## Configuración
 
Toda la configuración sale de variables de entorno y se valida al arrancar. Si falta algo obligatorio o hay una incoherencia (por ejemplo, un solapamiento mayor que el tamaño del chunk, o elegir OpenAI sin clave), la aplicación no arranca. Prefiero eso a fallar a mitad de una petición.
 
La clave del LLM se guarda como un valor secreto que no aparece en logs ni mensajes de error.
 
## Pendiente de decidir con datos
 
Tamaño de chunk, solapamiento, número de fragmentos a recuperar y umbral de similitud. También si agrego búsqueda híbrida y cómo calculo el nivel de confianza.
 
## Uso de IA
 
Uso Claude como apoyo durante todo el proyecto. Lo usé para analizar el enunciado, comparar alternativas, proponer código y redactar este documento a partir de las decisiones que tomé. Iré anotando aquí qué acepto, qué corrijo y por qué.