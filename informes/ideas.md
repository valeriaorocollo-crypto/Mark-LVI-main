# Ideas y oportunidades para hacer crecer MARK LVI

**Estado:** banco de ideas; no es una lista de funciones ya implementadas ni
una promesa de compatibilidad. La prioridad indica valor y secuencia sugerida,
no una autorización para habilitar acciones sensibles. La ejecución se
controla desde [plan_seguimiento.md](./plan_seguimiento.md).

## Dirección de producto

MARK puede diferenciarse como un asistente de Windows que entiende solicitudes
de voz, combina acciones locales y servicios externos, muestra lo que va a
hacer y verifica lo que realmente ocurrió. No necesita prometer que controla
cualquier programa: necesita ser útil en capacidades bien definidas, admitir
cuando no puede actuar y detenerse antes de producir un efecto incierto.

Principios para evaluar cualquier idea:

1. **El usuario conserva el control:** permisos claros, cancelación visible y
   desactivación sencilla.
2. **La respuesta refleja evidencia:** separar “iniciado”, “fallido”,
   “completado y verificado” y “resultado incierto”.
3. **Datos mínimos:** explicar qué sale del equipo, limitar la retención y no
   guardar conversaciones o capturas por comodidad.
4. **De menos a más:** comenzar con lectura/previsualización; añadir cambios
   solo con autorización, verificación y recuperación adecuadas.
5. **Integraciones específicas:** una API oficial o un adaptador UIA fiable
   para una aplicación concreta vale más que una promesa de control universal.

## Lo que ya existe y debe extenderse, no duplicarse

La revisión actual encontró una aplicación Python/PyQt con voz y proveedor
Gemini, acciones auto-descubiertas, plugins, controles de escritorio/UIA,
tratamiento de archivos, navegador, dashboard, almacenamiento de credenciales,
memoria, planes de tareas y plugins piloto. También existen controles de
confirmación, auditoría de metadatos y estados de resultado. Son una base, no
prueba de cobertura general ni de seguridad certificada. Véase
[informe.md](./informe.md) para el estado y los límites.

En particular, no conviene volver a proponer como si faltaran: una política de
riesgo por acción, una confirmación HUD, una previsualización básica de planes,
un contrato `done`/`unverified`/`failed`, el plugin Gmail de solo lectura o el
piloto de Spotify. Las oportunidades aquí describen cómo hacerlos más completos
y comprensibles.

## Prioridad 0 — confianza, privacidad y recuperación

Estas mejoras son primero porque evitan sorpresas, exposiciones de datos y
repetición de efectos.

### A. Centro de permisos y privacidad

- Una pantalla única que muestre integraciones activas, scopes OAuth,
  permisos de sesión, dispositivo emparejado, acceso remoto y cuándo se
  utilizaron por última vez.
- Acciones visibles para revocar un permiso individual, revocar todo, cerrar
  sesiones remotas y desconectar una integración.
- Antes de capturar pantalla, cámara, portapapeles o archivos: mostrar qué
  fuente se consultará y a qué proveedor se enviarán los datos.
- Indicador persistente mientras haya captura o transmisión activa, con un
  botón de detener.
- Resumen en lenguaje normal de qué información se guarda localmente, qué se
  comparte con cada proveedor y cómo borrarla.
- Preferencias granulares por proveedor y capacidad; no inferir un permiso
  amplio a partir de una aprobación para un único uso.
- No volver a preguntar al iniciar MARK cuando exista un permiso específico
  aprobado por la persona y todavía vigente. Decisión acordada: esos permisos
  vencen a los 30 días, se guardan solo en el perfil local y se pueden revocar
  individualmente o todos juntos.

### B. Confirmaciones que explican el efecto

- Una previsualización consistente antes de enviar, publicar, borrar, mover,
  sobrescribir, instalar o cambiar ajustes.
- Mostrar el destinatario o destino, cuenta, archivo, campos, proveedor y
  efecto concreto; ocultar secretos, no el contexto necesario para decidir.
- Diferenciar botones “aprobar esta vez”, “recordar este permiso por 30 días
  con este alcance” y “cancelar”.
- No permitir que los permisos recordados omitan la confirmación de mensajes,
  borrados/sobrescrituras, publicaciones, pagos o cambios administrativos.
- Si cambia cualquier campo sensible después de la aprobación, invalidarla y
  presentar la previsualización nueva.
- Proporcionar una salida de emergencia común para cancelar la tarea actual y
  desactivar temporalmente capacidades de escritura/envío.
- No sustituir seguridad técnica por advertencias: las extensiones no confiables
  no se vuelven seguras porque el usuario pulse “acepto”.

### C. Historial útil, privado y recuperable

- Línea de tiempo de acciones con hora, herramienta, estado, aprobación,
  duración y verificación, sin almacenar cuerpo de mensajes, texto de páginas,
  capturas ni secretos.
- En cada entrada: “qué intenté”, “qué pude comprobar” y “qué quedó incierto”.
- Undo solo cuando exista una operación inversa válida y el estado actual
  coincida con el estado esperado; explicar cuando no se puede deshacer.
- Borrado por categoría y fecha (memoria, historial de tareas, diagnóstico),
  con confirmación y explicación de límites de copias de seguridad y desgaste
  de almacenamiento.
- Exportación de un paquete de diagnóstico redactado y opt-in, útil para pedir
  ayuda sin incluir contenido privado.

### D. Captura visual deliberada

- Separar una pregunta explícita del usuario sobre la pantalla de una captura
  sugerida autónomamente por el modelo.
- Para futuras tareas visuales, vincular permiso, captura y resultado a una
  sola tarea; poner límites de frecuencia, duración y número de capturas.
- No conservar imágenes una vez terminada la tarea, salvo que el usuario las
  guarde expresamente.
- Ofrecer modo “seleccionar región” o ventana concreta en vez de enviar todo el
  escritorio cuando la tarea lo permita.
- Mantener bloqueadas las capturas en segundo plano hasta definir aviso,
  consentimiento, retención y pruebas de revocación.

## Prioridad 1 — utilidad cotidiana y experiencia

### E. Onboarding guiado, corto y comprobable

- Asistente inicial para probar micrófono, salida de voz, proveedor, idioma y
  permisos, sin solicitar todas las integraciones al mismo tiempo.
- Cada paso debe poder omitirse y completarse después; mostrar qué funciona y
  qué requiere configuración.
- Al terminar, ofrecer una primera acción inocua (por ejemplo, consultar hora o
  estado local) y explicar cómo cancelar.
- Una pantalla de “primeros pasos” con ejemplos reales de las capacidades
  disponibles en esta instalación, no una lista aspiracional.

### F. Manual consultable desde la interfaz y la voz

- Qué puede hacer cada función y qué no.
- Configuración de micrófono, voz, memoria, plugins, proveedores y acceso
  remoto.
- Requisitos, permisos, datos transmitidos y forma de desactivar cada
  integración.
- Guías de solución de problemas con comprobaciones específicas y enlaces a los
  controles correspondientes.
- Contenido en español primero; estructura de temas estable para poder añadir
  traducciones sin desalinear los pasos.
- Mantener la guía cerca del código o validarla en CI para detectar nombres de
  botones y opciones que ya no existen.

### G. Diagnóstico comprensible y accionable

- Panel de salud con estado del micrófono, proveedor, internet, navegador,
  plugins, dashboard y almacén de credenciales, sin mostrar valores secretos.
- Explicar fallos con: síntoma, causa más probable, comprobación segura y
  siguiente paso.
- Distinguir “no disponible”, “no autorizado”, “no se pudo verificar” y “el
  servicio remoto no respondió”.
- Permitir copiar un diagnóstico redactado y limitado, con vista previa antes
  de compartirlo.

### H. Rutinas y tareas de varios pasos seguras

- Guardar plantillas aprobadas por el usuario para tareas repetitivas (por
  ejemplo, preparar un resumen de archivos seleccionados).
- Antes de ejecutar, mostrar los pasos, sus efectos, datos que se leerán o
  enviarán y puntos que requieren intervención.
- Añadir “modo ensayo”: validar argumentos, permisos y objetivos sin ejecutar
  los pasos con efectos.
- Permitir pausa en puntos seguros, reanudación tras verificar el estado y
  cancelación que impida comenzar el siguiente efecto.
- Nunca reintentar un envío, compra, borrado o creación externa si el primer
  resultado quedó ambiguo.
- Guardar plantillas, no tokens de aprobación ni operaciones ejecutables que
  sobrevivan a un reinicio.

### I. Voz y accesibilidad

- Configuración sencilla de velocidad, volumen, dispositivo de entrada/salida,
  push-to-talk y sensibilidad de activación.
- Subtítulos/transcripción opcionales, con indicador claro y política de
  almacenamiento; desactivados si no se necesitan.
- Acciones accesibles por teclado y lector de pantalla para confirmar,
  cancelar, pausar y revisar permisos.
- Mensajes de error hablados cortos, con detalle adicional disponible en la
  interfaz.
- Modo silencioso/no molestar y controles para que avisos proactivos no
  interrumpan reuniones o audio.

### J. Interfaz y visualización

- Dar más claridad al estado actual: escuchando, pensando, usando herramienta,
  esperando aprobación, pausado, desconectado o verificando.
- Mostrar actividad y advertencias sin depender solo de color o animación.
- Vistas compacta y ampliada; ajustar contraste, tamaño de texto y movimiento.
- Si se recupera el marco holográfico que antes existía como `ui_holo.py`,
  mantenerlo opcional, con alternativa funcional y pruebas visuales; no hacer
  que una capa cosmética impida iniciar el asistente.
- Capturas de interfaz reproducibles para comparar cambios sin conectar a una
  cuenta real.

## Prioridad 2 — integraciones de alto valor, una por una

### K. Correo y calendario

- Completar Gmail de solo lectura con cuenta de prueba, revisión de consent,
  expiración/revocación, errores de red y minimización de datos.
- Explorar Microsoft Graph para Outlook con scopes mínimos; comenzar con
  lectura, luego borradores visibles. No enviar hasta que destinatario, cuenta
  y contenido sean verificables.
- Para calendario, empezar por lectura de disponibilidad; después creación de
  evento con zona horaria, calendario y asistentes visibles.
- Evitar invitaciones, cancelaciones y cambios de eventos sin una confirmación
  por operación y una comprobación posterior.
- Mostrar procedencia y hora de consulta para evitar presentar datos antiguos
  como actuales.

### L. Archivos y documentos

- Permitir elegir archivos/carpetas mediante diálogo y enseñar qué se va a leer.
- Añadir modo de comparación de documentos y resumen con referencias a página,
  hoja o sección de origen.
- Mejorar el flujo de exportación con destino y formato previsualizados.
- Para formatos comprimidos, aplicar límites a tamaño expandido, cantidad de
  entradas, profundidad de rutas y nombres maliciosos; bloquear traversal y
  sobrescrituras silenciosas.
- Separar lectura/análisis de escritura, manteniendo escritura en un segundo
  paso confirmado y reversible cuando sea posible.

### M. Navegador y búsqueda

- Perfiles de navegador claramente diferenciados del perfil personal, con un
  control visible para borrar cookies/datos del perfil automatizado.
- Permisos por dominio y operación; lectura no implica permiso para rellenar
  formularios o pulsar “enviar”.
- Resumen de noticias con enlaces, fecha, fuente y ubicación; permitir corregir
  la zona geográfica antes de presentar “noticias locales”.
- Indicar cuándo la página no proporciona fecha fiable o cuando la búsqueda no
  encontró resultados verificables.
- Botón para detener navegación/carga y límite de duración por tarea.

### N. Windows y automatización de aplicaciones

- Una ficha de compatibilidad por aplicación, versión, idioma, escala y tipo de
  cuenta probados.
- Priorizar APIs oficiales; usar UI Automation cuando la app exponga controles
  semánticos; recurrir a visión solo con límites y confirmación definidos.
- Añadir diagnóstico de procesos y dispositivos como lectura primero. Cambios
  administrativos deben ser comandos concretos, separados y aprobados; nunca
  una consola de administrador abierta.
- Para Steam, limitar la automatización a descubrir biblioteca/estado y abrir
  un diálogo para revisión humana hasta que haya una API estable y verificación
  fiable. No automatizar compras.
- Para Git y editores, empezar con inspección de diff y ejecución de tests
  previsualizada en un directorio elegido; separar VS Code, Visual Studio y Git
  como productos distintos.
- Para compresión, usar una biblioteca/CLI acotada con vista previa antes de
  extraer o reemplazar; no simular control de WinRAR si solo se ofrece gestión
  genérica de archivos.

### O. Multimedia y hogar

- Verificar si un video empezó realmente, no inferirlo porque el navegador
  abrió una URL.
- Control de música limitado al estado visible de Spotify; ampliar solo con
  pruebas por versión, cuenta e idioma.
- Integraciones de hogar inteligentes en modo lectura/previsualización primero;
  acciones físicas (cerraduras, calefacción, cámaras) requieren permisos y
  confirmación propios, estado de seguridad y modo manual.
- Rutinas horarias opcionales para recordatorios, con resumen de qué se
  ejecutará y cómo pausarlo.

## Prioridad 3 — plataforma, extensibilidad y distribución

### P. Extensiones entendibles y mantenibles

- Guía de plugins propia con esquema, parámetros, dependencias, límites de
  tiempo, permisos y pruebas mínimas.
- Mostrar en cada plugin quién lo proporciona, qué código se ejecutará, qué
  datos necesita y si se ha modificado desde la última revisión.
- Verificar hash y habilitación explícita (ya hay mecanismos de confianza en el
  código); explicar con honestidad que eso **no es sandbox**.
- Evaluar ejecución de plugins de terceros en un proceso aislado con IPC,
  capacidades explícitas, timeout, cancelación y límites de memoria.
- Un catálogo de extensiones solo tendría sentido con procedencia, revisión,
  política de actualizaciones y canal de reporte; no aceptar plugins
  arbitrarios descargados silenciosamente.

### Q. Plataforma técnica reproducible

- Matriz Windows/Python mantenida por CI con artefactos de evidencia
  redactados y vinculados al commit probado.
- Extras de dependencias por capacidad para que una instalación de voz básica
  no cargue todo el stack de navegador, documentos y visión.
- Resolución/lockfile reproducible y revisión periódica de vulnerabilidades,
  compatibilidad y licencias.
- Instalador Windows solo si se decide distribuirlo: firma, actualización
  verificable, desinstalación, manejo explícito de configuración y opción de
  conservar datos del usuario.
- Inventario de modelos, bibliotecas y recursos empaquetados con licencia,
  versión y atribución.

### R. Rendimiento y confiabilidad medidos

- Medir fin de voz, STT, primera respuesta, cada herramienta, verificación y
  primer audio TTS con reloj monotónico.
- Mostrar percentiles P50/P95 agregados por tipo de tarea, sin guardar
  transcripciones ni capturas.
- Reemplazar esperas fijas de GUI por condiciones observables, timeout y
  cancelación.
- Medir tasa de resultados `unverified` además de latencia: más velocidad no
  compensa efectos no comprobados.
- Caché solo para datos cuya vigencia y privacidad estén definidas; permitir
  refrescar o borrar.

## Recorridos de producto para prototipar

1. **“Resume estos documentos”**: el usuario selecciona archivos; MARK muestra
   tipos/tamaños, lee dentro de límites y entrega un resumen con referencias,
   sin escribir ni subir archivos sin aviso.
2. **“Prepara una respuesta a este correo”**: lectura vía API oficial,
   tratamiento del correo como contenido no confiable, borrador visible y
   destinatario/cuenta confirmados; enviar permanece como acción separada.
3. **“Qué pasó con mi tarea?”**: línea de tiempo de intentos y verificaciones,
   explicación de los puntos inciertos y opciones de reanudar solo lectura,
   cancelar o pedir asistencia.
4. **“Ayúdame a configurar el micrófono”**: diagnóstico local con pasos
   concretos, sin cambiar dispositivos ni permisos del sistema sin
   autorización.
5. **“Instala este juego”**: validar nombre y estado, presentar juego,
   biblioteca/disco y abrir el diálogo oficial; la persona completa el paso de
   instalación hasta que exista una vía automatizable comprobada.

## Ideas que no deben convertirse en alcance por defecto

- “Control absoluto” o una promesa de compatibilidad con cualquier aplicación.
- Ejecutar automáticamente contenido recibido en páginas, documentos,
  correos, plugins o mensajes.
- Un permiso “aprobar todo” o una concesión global que cubra futuras cuentas,
  destinatarios, archivos y aplicaciones.
- Mensajería, publicación, pagos, borrado o cambios administrativos por
  coordenadas/clics sin identificar el objetivo.
- Captura o monitoreo silenciosos, grabación siempre activa o retención
  indefinida de pantalla, audio, cámara o portapapeles.
- Lanzar un catálogo comunitario o una sincronización en nube antes de definir
  aislamiento, privacidad, seguridad y modelo de soporte.
- Reescribir todo en microservicios o fragmentar módulos solo por su tamaño.

## Secuencia sugerida

| Orden | Tema | Condición para avanzar |
|---|---|---|
| 1 | Cerrar las brechas de captura, alcance de permisos y efectos del plan | Captura bajo control explícito, permisos honestos y pruebas que demuestren que nada se ejecuta fuera del alcance. |
| 2 | Línea base y diagnóstico reproducibles | Matriz del commit actual; diagnósticos sin secretos; omisiones explicadas. |
| 3 | Robustecer archivos y automatización externa | Pruebas de fallo y no repetición; ningún envío o instalación ambigua. |
| 4 | Manual/contexto de funciones y onboarding | La guía coincide con la aplicación disponible y los controles reales. |
| 5 | Cerrar pilotos valiosos uno por uno | Cuenta de prueba, permisos mínimos, revocación y evidencia real no sensible. |
| 6 | Extensibilidad, métricas e instalador | Aislamiento o confianza claramente comunicada, métricas privadas y proceso de distribución verificable. |

Las prioridades y puertas detalladas están en
[plan_seguimiento.md](./plan_seguimiento.md). Los hallazgos observados y los
límites de la evidencia están en [informe.md](./informe.md).
