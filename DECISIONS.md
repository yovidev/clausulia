# Decisiones
 
En este documento cuento qué decidí en los puntos que el enunciado deja abiertos, qué descarté y qué compromisos acepté. Los números de la recuperación salen de la evaluación que está en backend/eval/results.md.
 
## El problema
 
Lo primero que tuve claro es que, para un analista que revisa contratos, una respuesta inventada es mucho peor que un "no lo sé". Por eso casi todas las decisiones van en la misma dirección: que cada respuesta se pueda verificar con su documento y su página, y que el sistema se calle cuando no tiene evidencia.
 
## Clientes y documentos
 
El enunciado no dice si los documentos son compartidos o de cada cliente. Decidí separarlos por organización desde el principio, porque que un cliente vea los contratos de otro sería el peor error posible. Cada documento tiene una organización, que llega en el header X-Org-Id, y todas las búsquedas filtran por ella. Si alguien pide un documento de otra organización, recibe un 404 y no un 403, para no confirmarle que existe.
 
No hay autenticación, y lo sé: cualquiera puede poner un header. Lo veo como la base del modelo de datos. El siguiente paso sería un token con la organización dentro, y la base de datos ya está preparada para eso.
 
Si alguien sube dos veces el mismo archivo, lo detecto por su hash y devuelvo el que ya existía. Si ese documento había fallado, lo vuelvo a procesar: así, subirlo de nuevo funciona como un "reintentar".
 
## Cuando la evidencia es débil o contradictoria
 
Si no encuentro ningún fragmento suficientemente parecido a la pregunta, respondo que no hay evidencia y ni siquiera llamo al LLM. Me ahorro el costo y elimino la posibilidad de que invente.
 
Si dos contratos dicen cosas distintas, muestro las dos versiones con sus citas y aviso del conflicto. No elijo una, porque el sistema no sabe qué contrato está vigente; eso lo tiene que decidir el analista.
 
Cada pregunta se responde sola, sin memoria de la conversación. Con memoria, una pregunta como "¿y en el otro?" dependería de respuestas anteriores que podrían estar mal, y verificar las citas sería más difícil.
 
## Cómo está armado
 
La API recibe el PDF, lo valida, lo guarda y encola el trabajo. No procesa nada pesado, para responder rápido. Un worker de Celery hace la parte lenta: extrae el texto, lo divide en fragmentos, calcula los embeddings y lo guarda todo en PostgreSQL con pgvector. Las preguntas se responden en la API.
 
La lógica de la ingesta y de las respuestas está en servicios que reciben todo lo que necesitan como parámetros. Celery y FastAPI solo los llaman. Gracias a eso puedo probar casi todo sin levantar un worker ni llamar a la red.
 
## Lectura de los PDF
 
Uso pypdf. Es liviano y me da el texto página por página, que es justo lo que necesito para citar. Miré Docling, que es mucho más completo con tablas, pero trae PyTorch y modelos pesados, y para contratos que son casi todo texto no me compensaba. Lo dejé detrás de una interfaz, así que podría entrar más adelante sin tocar el resto. PyMuPDF lo descarté por su licencia.
 
Si un PDF es un escaneo y casi no tiene texto, lo marco como fallido con un mensaje claro. No hago OCR: prefiero decir que no puedo leer un documento a responder con texto mal reconocido.
 
## Fragmentos y embeddings
 
Divido el texto por párrafos y, si hace falta, por oraciones. Una regla que me pareció importante es que ningún fragmento mezcle dos páginas, para que cada cita apunte a una página concreta. Los fragmentos tienen 1000 caracteres con 150 de solapamiento; esos valores salen de la evaluación.
 
Para los embeddings uso un modelo local, porque el sistema tiene que funcionar sin claves. Revisé el catálogo de fastembed y, de los modelos de 384 dimensiones, solo uno era multilingüe (paraphrase-multilingual-MiniLM-L12-v2). Como los contratos están en español, la elección fue fácil. La dimensión está fija en el código y no en una variable de entorno, porque cambiarla obliga a reprocesar todo.
 
## Que nada se duplique ni se quede atascado
 
Esta fue la parte que más me hizo pensar. La ingesta tiene tres pasos. Primero bloqueo la fila del documento y lo marco como "en proceso". Después hago el trabajo lento, sin ninguna transacción abierta. Al final, en una sola transacción, borro los fragmentos viejos, inserto los nuevos y lo marco como listo.
 
Con eso, si la tarea se ejecuta dos veces, la segunda ve que el documento ya está listo y no hace nada. Si el worker se cae a la mitad, no queda nada guardado a medias. Y si dos workers agarran el mismo documento, el bloqueo hace que uno espere al otro.
 
Celery solo confirma una tarea cuando termina, así que si el worker muere, la tarea vuelve a la cola. Solo reintento los errores que pueden arreglarse solos (la base de datos o la red), esperando cada vez un poco más. Un PDF corrupto no se reintenta, porque seguiría corrupto. Si no se puede cargar el modelo de embeddings, lo trato igual que un error de red: reintento y, si sigue fallando, el documento queda fallido con su motivo.
 
Aun así hay casos que no se cubren solos, como que Redis pierda la cola. Por eso cada cinco minutos una tarea busca documentos que lleven demasiado tiempo pendientes o en proceso y los vuelve a encolar. Si ya fallaron varias veces, los marca como fallidos. Así ningún documento se queda colgado para siempre.
 
## La búsqueda
 
Al principio usaba solo búsqueda vectorial. Probándola a mano, pregunté cuándo había que entregar esta prueba: el sistema encontraba la página correcta, pero no el fragmento con la fecha. Los embeddings captan bien el significado general, pero no tanto los datos exactos.
 
Por eso añadí búsqueda por palabras de PostgreSQL y combino los dos resultados. La evaluación confirmó la intuición: el modo combinado encuentra la página correcta entre los seis primeros resultados en el 88 % de las preguntas, contra el 81 % del vectorial, y gana justo en fechas, porcentajes y nombres. Tarda unos 45 ms más, nada comparado con un LLM.
 
El umbral de similitud (0,50) lo uso solo para decidir si hay evidencia, mirando el mejor fragmento. Si la hay, el LLM recibe los seis fragmentos. Al principio también filtraba con él qué fragmentos veía el LLM, y la evaluación me mostró que así perdía fragmentos útiles que quedaban un poco por debajo. Separar las dos cosas me dio el mejor resultado: todas las preguntas sin respuesta se rechazan y ninguna con respuesta se rechaza por error.
 
También probé fragmentos de 500 caracteres y poner el nombre del documento delante de cada fragmento. Los dos tenían alguna ventaja, pero dejaban pasar preguntas que no tienen respuesta, así que los descarté. Para mí pesa más no inventar que acertar un poco más.
 
Un detalle técnico: pgvector filtra por organización después de recorrer el índice, así que con muchas organizaciones podría devolver menos resultados de los que pido. Lo resolví activando el escaneo iterativo del índice, y hay un test que comprueba que ese ajuste no afecta a otras consultas.
 
Para medir todo esto generé contratos ficticios con un script, incluidos dos que se contradicen a propósito, uno escaneado y uno con un intento de prompt injection, y escribí 20 preguntas con su página esperada. Soy consciente de que son pocas preguntas y de que la diferencia entre las que tienen respuesta y las que no es muy pequeña. Tomo los valores como un buen punto de partida, no como algo definitivo.
 
## El LLM
 
Hice una interfaz propia con dos proveedores: uno simulado, que permite usar todo el sistema sin claves, y otro de OpenAI. No usé LiteLLM porque, con dos proveedores, una interfaz pequeña es más fácil de entender y de probar. El simulado también puede fallar a propósito (devolver JSON roto, tardar demasiado, limitar la tasa), para probar cómo reacciona el sistema.
 
Con OpenAI uso salidas estructuradas con un esquema estricto, de forma que es la propia API la que garantiza el formato. Además le pido que no guarde las conversaciones, porque son contratos. El proveedor de OpenAI lo probé con dobles, no contra la API real.
 
Toda respuesta se valida con Pydantic. Si llega mal formada, lo intento una vez más explicándole el error; si vuelve a fallar, la rechazo en lugar de mostrar algo sin validar. También descarto cualquier cita a un fragmento que no recuperé yo. La confianza que muestro es la menor entre la que dice el modelo y la que calculo con la similitud, porque los modelos suelen ser demasiado optimistas.
 
## Prompt injection
 
Como el texto de los contratos entra en el prompt, lo trato como datos y nunca como instrucciones. Cada fragmento va dentro de una etiqueta y su contenido se escapa, para que un documento no pueda cerrarla y colar instrucciones propias. El prompt le dice al modelo que ignore cualquier orden que aparezca dentro de un contrato, y la respuesta tiene que seguir un esquema.
 
Hay un test que me gusta especialmente: simula un modelo que cae en la trampa y cita un fragmento inventado por el atacante. Aun así, ese fragmento nunca llega a la respuesta, porque no es uno de los que recuperé. No es una defensa perfecta, pero son varias capas independientes.
 
## Errores
 
Todos los errores tienen el mismo formato: un código, un mensaje en español y el identificador de la traza, para poder buscarla en Jaeger. Uso códigos HTTP que tengan sentido: 413 si el archivo es muy grande, 415 si no es un PDF, 503 si la base de datos o Redis no responden, y 429, 502 o 504 según lo que falle en el LLM.
 
Un matiz que aprendí: FastAPI recibe el archivo completo antes de que mi código lo vea, así que el límite de tamaño en la API protege el disco, pero no la red. Por eso también lo limito en nginx, que está delante.
 
## Trazas y logs
 
Una subida genera una sola traza que va de la petición HTTP al worker de Celery, la lectura del PDF, los embeddings y la escritura en la base. Lo comprobé buscando el mismo identificador de traza en los logs de la API y del worker. Las preguntas generan otra traza, donde se ven la búsqueda, los tokens del LLM y cuántos fragmentos se usaron. Dejé capturas en la carpeta docs.
 
Jaeger solo guarda trazas, así que las latencias van como atributos de las trazas y no como métricas. Los logs salen en JSON y cada línea lleva el identificador de su traza. No trazo el endpoint de salud, porque Docker lo llama cada diez segundos y llenaría todo de ruido.
 
Tuve que bajar SQLAlchemy de la versión 2.1 a la 2.0, porque la instrumentación de OpenTelemetry todavía no soporta la más nueva. Preferí tener trazas completas.
 
## La interfaz
 
Es una página con dos partes: los documentos y el chat. El estado de los documentos se actualiza consultando la API cada dos segundos, y solo mientras haya alguno en proceso. Pensé en SSE, pero necesitaba más piezas y era más difícil de probar, y como una ingesta tarda varios segundos, dos de retraso no se notan.
 
Las subidas y las preguntas no se repiten solas si fallan, para no duplicar nada sin que el usuario lo pida.
 
## Herramientas
 
Python 3.12, porque algunas librerías tardan en soportar la versión más nueva. uv para las dependencias de Python y pnpm para las del frontend. Ruff y mypy en modo estricto. Flower para ver las tareas de Celery. Docker con una sola imagen para la API, el worker y Flower, y un usuario sin privilegios.
 
El CI de GitHub revisa estilo, tipos y tests del backend contra un Postgres real, hace lo mismo con el frontend y busca secretos con gitleaks. Si en el CI falta la base de datos, los tests fallan en vez de saltarse, porque prefiero un CI en rojo a uno en verde que no probó nada.
 
## Lo que quedó fuera
 
- Autenticación y usuarios.
- OCR para documentos escaneados.
- Un reordenamiento más fino de los resultados, y una forma de que cada fragmento sepa de qué contrato es sin empeorar los rechazos.
- Ignorar tildes en la búsqueda por palabras.
- Notificaciones en vivo en lugar de consultas periódicas.
- Memoria de conversación.
- Evaluar la calidad de la respuesta completa, no solo de la búsqueda.
- Borrar documentos, paginar la lista y guardar los archivos en S3.
- Un tiempo máximo total por pregunta en la API.
- Agentes. La vacante los menciona, pero este problema es de buscar y citar.
## Cómo usé la IA
 
Trabajé con Claude durante todo el proyecto. Al principio, en un chat, analicé el enunciado, comparé alternativas y monté la base paso a paso, ejecutando yo cada comando y revisando cada salida. Cuando la base estuvo probada, pasé a Claude Code con un archivo CLAUDE.md donde dejé el contexto, las decisiones y unas reglas: una pieza a la vez, no cambiar decisiones sin preguntarme, dejar los tests en verde y no hacer commits. Revisé cada cambio y los commits los hice yo. Este documento también lo redacté con ayuda de Claude, a partir de mis decisiones.
 
Acepté buena parte de lo que propuso, y varias ideas mejoraron mi plan: las salidas estructuradas de OpenAI, no guardar las conversaciones, un escape más completo del texto, el escaneo iterativo del índice y separar el umbral de decisión del filtrado de fragmentos. Los valores finales de la búsqueda los aprobé yo con la tabla de la evaluación delante.
 
También hubo cosas que corregí o tuve que verificar:
 
- Un test de integración encontró un error real: el lector de PDF decía "PDF inválido" cuando en realidad el archivo no existía, porque atrapaba un tipo de error demasiado amplio.
- mypy encontró dos errores de tipos en código propuesto por la IA.
- Comprobé en el catálogo de fastembed que el modelo sugerido existía y tenía la dimensión correcta.
- La primera imagen de Jaeger que me propuso era de una versión que ya no se mantiene.
- La migración generada automáticamente no creaba la extensión vector; lo comprobé borrándola y volviendo a migrar.
- Resolví yo los conflictos de puertos con otros proyectos de mi máquina.
- En los logs vi que el modelo se colaba dentro de la imagen de Docker y que Flower no iba a ver las tareas.
- Probando a mano encontré un mensaje de error confuso y el problema con las fechas que me llevó a la búsqueda combinada.
- En la revisión final apareció un caso en que un documento podía quedarse pendiente para siempre si fallaba la descarga del modelo, y lo corregí antes de entregar.