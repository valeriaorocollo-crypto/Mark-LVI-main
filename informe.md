# Informe final de situación — MARK LVI

**Fecha de consolidación:** 11 de noviembre de 2026
**Base examinada:** árbol de trabajo local de `Mark-LVI-main`, commit HEAD
`9c9864e` (`Merge branch 'main'...`) y modificaciones locales presentes durante
la revisión.

## 1. Resumen ejecutivo

MARK LVI es un asistente de escritorio en Python/PyQt con voz, proveedor
Gemini, herramientas locales, automatización Windows, navegador, procesamiento
de archivos, memoria, plugins, dashboard y un planificador de tareas. El
proyecto ya tiene varias defensas importantes: clasificación de efectos,
confirmaciones en el HUD, validación de argumentos, resultados que distinguen
éxito verificado de incertidumbre, planes secuenciales, auditoría de metadatos,
controles de archivo con undo y plugins que requieren confianza explícita.

**Conclusión:** hay una base funcional que se debe endurecer y completar, no
una razón para empezar desde cero. El producto está en fase de prototipo
avanzado/pilotos; no es todavía un agente universal ni un sistema que deba
ejecutar tareas sensibles desatendido. Algunas capacidades tienen pruebas
sintéticas sólidas; eso no demuestra que funcionen en cada versión real de
Windows, aplicación, cuenta, idioma o escala de pantalla.

Las prioridades inmediatas son:

1. Poner la captura de pantalla/cámara solicitada por el modelo bajo una
   política de consentimiento y un indicador visible; no tratarla como una
   lectura inocua solo por llevar el nombre `screen_process`.
2. Corregir el permiso de `screen_find`: el texto del HUD afirma que dura hasta
   cerrar MARK, pero el código lo vence en una hora; además, el alcance
   `active_screen` no identifica una ventana o tarea y se reutiliza sin
   comparar el objetivo de cada solicitud.
3. Mostrar los efectos reales de cada paso del plan. El campo `effect` se
   calcula hoy a partir del estado `"started"`/`"unknown"` y la vista previa no
   presenta efectos por paso.
4. Mantener bloqueadas las integraciones externas cuyo resultado real no está
   verificado, especialmente envío de mensajes. No repetir acciones ambiguas.
5. Reconciliar evidencia y compatibilidad: la suite actual pasó localmente en
   Python 3.12; la matriz remota citada por los documentos pertenece a commits
   previos, no al árbol de trabajo modificado de esta revisión.

La hoja de ruta de ejecución y puertas está en
[plan_seguimiento.md](./plan_seguimiento.md). El catálogo de oportunidades de
producto está en [ideas.md](./ideas.md).

## 2. Alcance, método y límites

### Revisado

- Estructura del repositorio y estado de Git.
- Código de despacho y política (`core/action_policy.py`,
  `core/tool_audit.py`, `core/confirm.py`).
- Permisos de sesión (`core/session_grants.py`) y controles relacionados del
  HUD.
- Captura visual en `main.py` y `actions/computer_control.py`.
- Planificador (`core/task_plan.py`), carga y confianza de plugins
  (`core/plugin_loader.py`).
- Rutas de archivos, mensajería, Steam y dashboard, además de manifiestos de
  dependencias y workflow Windows.
- Documentación previa: `SECURITY-REVIEW.md`,
  `ROADMAP_CONTROL_UNIVERSAL.md`, este informe y
  `plan_seguimiento.md`.
- Suite completa de unittest disponible en el entorno local actual.

### No realizado

- No se leyeron manualmente, línea por línea, los 129 archivos Python.
- No se hizo fuzzing, prueba de penetración, revisión completa de dependencias,
  prueba de malware ni auditoría criptográfica.
- No se inició sesión en proveedores, no se enviaron mensajes, no se hicieron
  compras/instalaciones y no se cambiaron firewall o ajustes de Windows.
- No se probó cada aplicación real ni todos los dispositivos de audio.
- No se certificó Windows 11, Python 3.11/3.13 o una instalación limpia en este
  corte.
- Los resultados guardados en la documentación y en `evidence/` se conservan
  como antecedentes, pero no se presumen como una ejecución del checkout
  actual.

### Cómo leer el nivel de certeza

- **Observado ahora:** comprobado directamente en código/estado local o en la
  ejecución local de pruebas indicada abajo.
- **Registrado previamente:** consta en la documentación/evidencia ya existente;
  no se volvió a reproducir en esta revisión.
- **Pendiente:** falta una prueba que permita elevar el estado.

## 3. Línea base real del árbol revisado

| Dato | Resultado actual | Interpretación |
|---|---|---|
| Rama/HEAD | `9c9864e` (merge local visible en el log) | La rama contiene trabajo previo, pero el checkout no está limpio. |
| Cambios locales | `SECURITY-REVIEW.md`, `informe.md`, `plan_seguimiento.md`, `setup.py`, `ui.py` modificados; `ideas.md` sin seguimiento | No asumir que esos cambios están publicados ni descartarlos. |
| Código Python | 129 archivos en el árbol examinado, contando `tests/` | Recuento de archivos, no medida de madurez. |
| Pruebas | 51 archivos de prueba encontrados | Hay cobertura amplia, pero también skips y dependencias de entorno. |
| Ejecución local de unittest | Python 3.12.10: 485 pruebas, 0 fallos, 0 errores, 12 omitidas | Es la validación reproducible ejecutada durante esta consolidación. Las omitidas no cuentan como aprobadas. |
| Warnings vistos en esa ejecución | Aviso deprecado `Starlette TestClient`/`httpx`, aviso `pynvml` y avisos UIA/asyncio del entorno | No hicieron fallar la suite; deben revisarse, no ocultarse. |
| Workflow | `.github/workflows/windows-tests.yml`, matriz Python 3.11/3.12/3.13 | Existe CI declarada. Debe ejecutarse sobre el commit que se vaya a entregar. |
| Evidencia versionada | `evidence/stage0-windows-2026-11-10.json` | Registra un corte anterior: 474 pruebas, 13 omitidas por intérprete, y el run CI 42948215095 en un commit previo. |
| Otra CI reportada en documentos | Run 42951554253 aparece como verde para Python 3.11–3.13 | Es un resultado histórico citado por los documentos; confirmar en GitHub y no confundirlo con `9c9864e` ni con los cambios locales. |
| `ui_holo.py` | No está presente ni versionado en el árbol actual | En la suite se observó el fallback “Holographic chrome unavailable”; la interfaz usa paneles simples. El módulo cosmético es opcional, pero hoy no está incluido. |

La discrepancia entre `485/12` en esta máquina, `474/13` en el JSON de Etapa 0
y otras cifras en documentos antiguos es de **cortes distintos**, no evidencia
de que se hayan ejecutado todas sobre el mismo código. El número válido siempre
debe citar intérprete, checkout/commit, comando y skips.

### Evidencia histórica que se conserva como antecedente

Estos resultados aparecen en `SECURITY-REVIEW.md`, `ROADMAP_CONTROL_UNIVERSAL.md`
o `plan_seguimiento.md`; no se repitieron todos durante este corte:

| Prueba/escenario | Resultado consignado | Límite |
|---|---|---|
| CI Windows run 42948215095 | Python 3.11/3.12/3.13 reportados en verde para el commit `bd6c9cc...`; artefactos por versión | Antecede al HEAD local y a cambios no confirmados. |
| CI Windows run 42951554253 | Documentado en el plan como verde para Python 3.11/3.12/3.13, commit `2d21993...` | Verificar directamente el run/artefactos antes de usarlo como release gate. |
| Archivos | Se consignan ACL denegada, medio extraíble, SMB UNC y ENOSPC en VHDX temporal; el original se preservó | Escenarios específicos; no garantizan todo volumen/ACL/fallo. |
| Cancelación | Se registra un flujo HUD `Awaiting confirmation` → `Cancelled` sin crear el archivo de prueba | Prueba manual acotada; el test automático sigue siendo necesario. |
| UI Automation | 10 pruebas opt-in en ventana sintética y 19 pruebas del driver WhatsApp reportadas | No es una prueba de compatibilidad completa con una aplicación real. |
| WhatsApp | El historial incluye intentos con destinatario/previsualización; un intento real quedó `failed` o `unverified`; no hay comprobación independiente reproducible de entrega | Mantener bloqueado/no reintentar un envío de resultado ambiguo. |
| Steam | Se abrió el diálogo real de instalación y la persona debía completar la selección | No se completó instalación ni se probó compra. |
| Dashboard | Certificado temporal en loopback validado por cliente confiado con HTTP 200; cliente sin confianza rechaza; dispositivo ASUS llegó a la pantalla de acceso | Confianza del certificado en el dispositivo y pairing real no validados. |
| Integraciones | Spotify reportado reproduciendo una pista y con estado visible; Gmail cuenta/OAuth real todavía pendiente | Resultado histórico acotado y no equivalente a matriz multi-versión. |

## 4. Arquitectura y capacidades

### Componentes principales

- `main.py`: ciclo principal, conexión al proveedor, despacho de herramientas,
  memoria, tareas, captura y funciones enlazadas al estado de sesión.
- `ui.py`: ventana PyQt y HUD; concentra pantalla, ajustes, integraciones,
  paneles de tareas y dashboard.
- `actions/`: herramientas por capacidad (navegador, escritorio, archivos,
  correo/mensajes, búsqueda, Steam, multimedia, sistema).
- `core/`: política/registro de acciones, confirmación, resultados, plugins,
  voz, planes, undo, identidad y diagnóstico.
- `providers/`: pipeline de voz/modelo, proveedores STT/LLM/TTS y registro.
- `plugins/`: conectores instalables, como Gmail, Spotify y WhatsApp.
- `memory/`: configuración, memoria y almacenamiento de preferencias/secrets.
- `dashboard/`: control remoto local/LAN, autenticación, pairing y TLS.
- `tests/`: pruebas unittest; `.github/workflows/windows-tests.yml` ejecuta la
  matriz Windows.

### Inventario funcional encontrado

| Grupo | Módulos/ejemplos presentes | Alcance que se puede afirmar |
|---|---|---|
| Voz/modelo | `providers/audio.py`, `providers/engine_pipeline.py`, `providers/llm_openai.py`, `providers/stt_*`, `providers/tts_*`, `core/gemini.py` | Hay abstracciones y caminos de voz/modelo; cada combinación de dispositivo/proveedor necesita su propio smoke test. |
| Escritorio | `actions/computer_control.py`, `computer_settings.py`, `desktop.py`, `open_app.py`, `screen_processor.py`, `system_monitor.py` | Acciones locales concretas y UIA/visión parcial; no equivalen a automatización fiable de cualquier ventana. |
| Navegación/información | `browser_control.py`, `web_search.py`, `weather_report.py`, `flight_finder.py`, `youtube_video.py`, `video_player.py` | Búsqueda y automatización web por caminos específicos; las fuentes, fechas y resultados necesitan verificación. |
| Archivos/contenido | `file_controller.py`, `file_processor.py` | Acciones locales de archivos y lectura/procesamiento de formatos con límites; no es WinRAR ni acceso ilimitado al disco. |
| Productividad | `reminder.py`, `background_monitor.py`, `proactive.py`, `task_planner.py`, `meet_control.py` | Recordatorios, monitoreo y coordinación de tareas; llamadas/reuniones no deben darse por completadas por abrir una página. |
| Desarrollo/juegos | `code_helper.py`, `dev_agent.py`, `game_updater.py` | Asistencia de código y algunas acciones de Steam; revisar workspace/diff y mantener instalación final bajo control humano. |
| Plugins | `plugins/gmail_control.py`, `spotify_control.py` y `_whatsapp_core.py`; mensajería declarada desde `actions/send_message.py` | Pilotos con estados distintos; cada uno necesita tests, permisos y matriz propia. |
| Memoria/configuración | `memory/memory_manager.py`, `config_manager.py` | Preferencias y memoria locales; retención, borrado y sincronización deben especificarse por clase de dato. |
| Dashboard | `dashboard/server.py` y `dashboard/static/` | Interfaz remota con pairing/TLS; falta validar identidad desde cada cliente que se vaya a soportar. |

### Áreas con mayor costo de cambio

Recuento actual de líneas (aproximado, obtenido del checkout local):

| Archivo | Líneas | Efecto sobre mantenimiento |
|---|---:|---|
| `ui.py` | 7.217 | UI, ajustes e integraciones en una superficie grande; una extracción exige pruebas focales. |
| `main.py` | 2.726 | Orquestación de sesión y herramientas concentrada. |
| `actions/browser_control.py` | 1.712 | Navegador, DOM, formularios y operaciones de página acoplados. |
| `actions/file_processor.py` | 1.405 | Lectura/transformación de varios formatos. |
| `actions/computer_settings.py` | 1.094 | Controles y caminos de sistema operativo. |
| `providers/engine_pipeline.py` | 1.044 | Pipeline de proveedor/voz y tiempos. |
| `dashboard/server.py` | 1.049 | Varios límites de red/servidor en un módulo. |
| `core/task_plan.py` | 920 | Validación, preview, ejecución, recuperación e historial. |
| `memory/config_manager.py` | 921 | Configuración, migraciones y almacenamiento sensible. |

No se justifica una reescritura por tamaño. Primero fijar los contratos y
pruebas, después extraer por responsabilidad con cambios pequeños.

### Madurez funcional por capacidad

| Capacidad | Estado defendible hoy | Lo que no debe prometerse |
|---|---|---|
| Voz / Gemini | Integración implementada; existe pipeline y control de dispositivos | Latencia, calidad o disponibilidad uniformes en todos los equipos/redes. |
| Acciones Windows | Teclado/ratón, ventanas y UIA con validación/selectores y límites | Control completo de Windows, acceso administrador universal o compatibilidad de cada app. |
| Planes compuestos | Preview/aprobación, hasta 12 pasos, ejecución secuencial, verificaciones y pausa/cancelación | Efecto por paso correctamente explicado todavía; recuperación persistente tras reinicio. |
| Archivos/documentos | Acciones de archivo y lectura de formatos con límites; historial de correcciones de escritura/undo | Gestión de todo el disco o garantía de recuperación en todo sistema de archivos. |
| Navegador/búsqueda | Playwright con perfil de automatización y búsqueda web/noticias | Compatibilidad universal, persistencia segura o precisión geográfica garantizada. |
| Spotify | Plugin con ruta API/UIA; prueba real registrada de reproducción visible | Confirmar audio audible o compatibilidad con otras versiones/cuentas/idiomas. |
| Gmail | Plugin de búsqueda de solo lectura y tests simulados | OAuth/cuenta real validada en este corte; envío o modificación de correo. |
| WhatsApp | Driver con intento de validar destinatario, conversación y mensaje; otros envíos genéricos deshabilitados | Entrega verificada: historial reporta resultados `failed`/`unverified`; no reintentar un caso ambiguo. |
| Calendario / Outlook | Sin integración completa confirmada | Clasificación de riesgo o abrir una aplicación no equivalen a conectores. |
| Steam | Descubre juegos y puede abrir diálogo de instalación para que la persona revise | Instalación automática, compra o control total de tienda/biblioteca. |
| YouTube/video | Busca/abre URL; el propio resultado puede ser `unverified` | Reproducción iniciada o audible sin leer el estado del reproductor. |
| Git/IDE, WinRAR, Device Manager | No hay un conector completo demostrado en este corte | Abrir ejecutables o usar automatización genérica no cuenta como integrar el producto. |
| Dashboard remoto | Servidor, pairing y TLS; existe prueba local TLS previa | Identidad de certificado y confianza de cada cliente LAN, ni uso remoto seguro sin validarlo. |
| Plugins | Descubrimiento, hash y confianza explícita antes de cargar, además de habilitación | Sandbox: el plugin confiado corre en proceso y con permisos del usuario. |

## 5. Seguridad, confiabilidad y privacidad

### Controles existentes que conviene conservar

- `core/tool_audit.py` asigna riesgos/efectos explícitos; el dispatcher
  `core/action_policy.py` valida argumentos, rechaza efecto desconocido o riesgo
  sin clasificar y confirma operaciones de alto impacto.
- La confirmación nace de la interfaz; el contexto de plan permite solo las
  firmas de herramienta/argumentos previamente aprobadas.
- `core/outcome.py` distingue estados; un resultado incierto no se debe narrar
  como éxito.
- `core/task_plan.py` ejecuta en secuencia, limita la cantidad de pasos,
  requiere verificación de solo lectura y no debe repetir automáticamente un
  efecto ambiguo.
- La auditoría de herramientas es acotada y no guarda argumentos ni texto de
  resultados.
- Los documentos existentes describen almacenamiento de secretos en keyring
  con backend de Windows; la prueba con backend simulado no equivale a certificar
  Windows Vault en otra máquina.
- El código actual de Steam abre el diálogo oficial de instalación y deja la
  elección/confirmación final a la persona.
- La carga de plugins compara hash y requiere confianza/habilitación; es una
  barrera de consentimiento, no aislamiento.

### P0 — Captura visual solicitada por el modelo fuera de una puerta clara

`screen_process` está declarado como herramienta del modelo y clasificado como
`read_or_navigate`. En `main.py`, su rama captura pantalla o cámara y adjunta la
imagen al intercambio sin pasar por el mismo gate central de `dispatch`; hay
un cooldown de cuatro segundos, pero eso no representa consentimiento ni
indica al usuario que la pantalla se va a transmitir. Para cámara se activa el
stream UI; para la ruta de pantalla no se observó un indicador equivalente.

**Riesgo:** contenido privado puede llegar al proveedor como parte de una
llamada de herramienta que el modelo pidió, sin aprobación visible específica
ni una política de tarea/retención completa.

**Estado:** pendiente de corregir. Mientras tanto, deshabilitar captura
autónoma/proactiva o exigir un consentimiento explícito del usuario antes de
capturar. La captura que el usuario pide directamente y la que solicita el
modelo deben tratarse de forma distinguible.

### P0 — Grant de pantalla con objetivo demasiado amplio y duración mal descrita

`core/session_grants.py` admite un único scope:
`(share_screen_search, Gemini, active_screen)`. `_session_grant_for` autoriza
`computer_control/screen_find` con ese scope sin comparar los argumentos,
ventana, tarea o destino de la captura. El permiso permite una búsqueda sobre
la pantalla activa en posteriores llamadas mientras siga válido.

El código fija `SESSION_GRANT_TTL_SECONDS` a **una hora**. Sin embargo, la UI
describe el permiso como vigente “hasta que se revoque o cierre MARK” y “no
expira por sí solo”. La tarjeta puede mostrar un contador, pero el texto
principal y el comportamiento no coinciden. El grant tampoco lleva ID de tarea
o sesión Gemini, no hay auditoría específica de creación/uso/revocación y no se
ha demostrado un indicador de captura.

**Riesgo:** la persona puede otorgar una duración y alcance distintos de los
que realmente presenta el producto; una sesión activa puede seguir permitiendo
capturas que no corresponden a la tarea original.

**Decisión de producto acordada durante esta sesión:** recordar permisos
específicos entre reinicios por 30 días, con expiración fija (no deslizante),
revocación visible y alcance de capacidad/proveedor/objetivo. Las acciones de
alto impacto siempre conservan confirmación por operación. La captura no se
habilita en segundo plano y requiere indicador y contexto de tarea. No se
sincronizan grants entre equipos/perfiles.

**Estado técnico:** pendiente P0; el código sigue siendo solo en memoria y
expira a la hora. No afirmar que MARK ya recuerda permisos al reiniciar. La
implementación debe incluir almacenamiento local versionado/atómico, invalidar
registros malformados y separar autorización persistente de tokens de aprobación
de plan. No migrar automáticamente el scope antiguo `active_screen` a un
permiso más amplio.

### P1 — Planes no muestran efecto real por paso

`PlanStep.effect` se construye actualmente llamando a
`classify_effect("started" if action else "unknown")`; no clasifica los
argumentos y la vista `preview()` devuelve el total de riesgos, pero no un
efecto legible por paso. La aprobación es exacta respecto a firmas y se valida
el riesgo, lo cual es valioso, pero no satisface la promesa de que la persona
vea lo que hará cada paso.

**Acción:** calcular el efecto desde herramienta/acción/argumentos, rechazar
`unknown`, y exponer en la confirmación una descripción legible del objetivo,
los datos que se leerán/enviarán y los efectos por paso. Probar redacción de
secretos y el rechazo de cambios entre preview y ejecución.

### P1 — Mensajería y resultados reales

`actions/send_message.py` mantiene un stub que rechaza envíos genéricos sin
transporte verificable. WhatsApp usa un driver específico, revalida el
destinatario y puede devolver `unverified` si no comprueba el mensaje.
Documentación anterior registra intentos reales ambiguos. No hay evidencia en
este corte de una matriz repetible de envío a una cuenta de prueba.

**Regla operativa:** no reintentar automáticamente cuando pudo haberse enviado
el mensaje; no afirmar entrega por el texto del modelo ni por el texto escrito
en el compositor.

### P1 — Plugins de Python ejecutan en el mismo proceso

`core/plugin_loader.py` limita tamaño del fuente, calcula SHA-256, evita cargar
plugins sin confianza explícita y exige que estén habilitados. Una vez cargado,
el código se ejecuta dentro del proceso de MARK con los permisos del usuario.
No existe sandbox ni aislamiento de red/archivos.

**Decisión:** documentar como código local de confianza. Antes de permitir
plugins de terceros, explorar un proceso separado/IPC, capacidades acotadas,
timeout, cancelación y límites. No llamar “seguro” o “aislado” al control por
hash.

### P1 — Dashboard: cifrado no equivale a identidad verificada

`dashboard/server.py` expone funcionalidad de red y tiene una rutina pública
de lectura de reglas de firewall; en el código inspeccionado esta función lee
reglas y no las modifica. Los antecedentes registran HTTPS con certificado
temporal/autofirmado y un test local confiado que responde HTTP 200. No se
comprobó la confianza de identidad desde un cliente físico en esta revisión.
TLS protege el canal únicamente cuando el cliente confía en el certificado
correcto.

**Estado:** cambios automáticos de firewall no se observaron en la ruta actual;
no asumir que el acceso remoto está certificado. Mantener opt-in, comprobar
emparejamiento, identidad del servidor, revocación, expiración y límite de
intentos antes de exponerlo en una LAN no confiable.

### P1 — Rutas inline y límites de la política única

`main.py::_execute_tool` tiene herramientas inline. Algunas tienen confirmación
explícita, otras son de lectura, pero `screen_process` demuestra que no toda
operación sensible pasa estructuralmente por el dispatcher central. No declarar
“toda herramienta está gateada” sin inventariar ruta por ruta.

**Acción:** inventariar todas las herramientas inline, clasificar sus datos y
efectos, y enrutar captura/escritura/efectos externos por política o gate
equivalente que falle cerrado.

### P1 — Afirmaciones de grant/confirmación y API de aprobación

La decisión de grant se origina actualmente en botones del HUD; no hay una
opción de “permitir todo”. Conviene mantenerlo. No obstante, la función
`confirm.resolve` acepta booleanos y cadenas (`accept`, `grant`, `cancel`).
La ruta observada es UI, por lo que esto se trata como endurecimiento
preventivo: usar decisiones tipadas y mantener imposible que texto del modelo,
red o una llamada futura cree aprobación.

La concesión se crea antes de ejecutar el paso confirmado y no se revierte si
el paso falla. Esto puede dejar un permiso concedido aunque la operación no
haya completado; decidir si es intencional o crear grant tras éxito, con
semántica explícita y pruebas.

### Riesgos de archivos y undo

La documentación previa registra correcciones para evitar reemplazar un
destino al copiar y para condicionar undo a identidad/contenido; el árbol tiene
pruebas de archivos en la suite. No se reprodujeron aquí las pruebas
adicionales de NTFS ACL, SMB, medio extraíble o ENOSPC mencionadas en notas
previas. Esas pruebas son evidencia acotada, no garantía para cualquier
volumen.

**Pendiente:** mantener una matriz de destino preexistente, permisos
denegados, binarios, archivos grandes, interrupciones, red y carpetas; verificar
que ningún undo borre cambios posteriores del usuario.

### Prompt injection y contenido no confiable

Existen wrappers para contenido web/documental y tests deterministas de límites.
Eso ayuda a separar datos de instrucciones, pero no prueba que el modelo obedezca
en todos los casos. Las acciones derivadas de correo, webs, documentos,
subtítulos o plugins deben requerir evaluación independiente de efecto y
confirmación humana cuando corresponda.

### Datos y retención

Hay varios subsistemas de memoria, historial, capturas y logs; no se identificó
una política única que explique todo el ciclo de vida. La auditoría de
herramientas omite argumentos, pero esto no demuestra que todos los logs de
dependencias o plugins tengan el mismo comportamiento. Documentar cada fuente,
ubicación, retención, exportación y borrado antes de afirmar “no se guarda”.

## 6. Mantenimiento y distribución

### Dependencias

- `requirements-base.txt` incluye PyQt6, audio, Gemini, HTTP, navegador
  Playwright, OpenCV, automatización de escritorio, dashboard y varias
  bibliotecas. Hay manifiestos opcionales separados, pero conviene confirmar
  que las dependencias base sean necesarias para el camino de voz mínimo.
- `setup.py` declara Python 3.11–3.13 como rango probado en el código.
- Algunos paquetes no tienen límites de versión estrictos; no se identificó un
  lockfile reproducible en la raíz.
- La suite reportó un aviso por `Starlette TestClient`/`httpx`; también apareció
  aviso deprecado de `pynvml`. No bloquearon los tests, pero conviene elegir
  dependencias recomendadas y evitar que el aviso se convierta en incompatibilidad.

### Rendimiento

El pipeline y varias herramientas ya tienen tiempos, presupuestos, cachés o
timeouts; por tanto, no es correcto describir el proyecto como carente de toda
instrumentación. Lo que no se encontró como evidencia de release es una serie
persistente y privada de P50/P95 por recorrido completo, proveedor, tipo de
tarea y resultado verificado. La recomendación es medir primero, sin texto ni
capturas, y optimizar después; paralelizar acciones que comparten foco puede
causar errores aunque reduzca latencia.

### Calidad

La CI Windows existe, pero la evidencia histórica no coincide con la línea
base del árbol modificado. No vi evidencia de que Ruff/Pyright sean un paso
requerido de la matriz. Primero fijar qué linter y comprobación de tipos son
apropiados y activar reglas gradualmente; evitar un cambio masivo que distraiga
de las brechas P0.

### Identidad del producto y UI

La documentación histórica menciona variaciones MARK/JARVIS. El código que se
revisó aún contiene nombres heredados (“Jarvis” en UI y mensajes). Definir el
nombre canónico y reservar aliases solo para compatibilidad. El módulo
holográfico separado no está en el checkout actual; el import opcional permite
fallback, por lo que no bloquea el arranque, pero sí cambia el aspecto esperado.

### Instalador

En `AAAA` había un instalador de otra aplicación, pero no se halló un instalador
propio de MARK en la raíz. El script externo puede inspirar decisiones de
Windows, no copiarse. Si MARK se distribuirá como aplicación instalada, definir
firma, arquitectura, instalación por usuario, actualización y conservación/
borrado explícitos de configuración.

## 7. Duplicación y oportunidades de simplificación

- Automatización de escritorio se reparte entre varios módulos; consolidar un
  adaptador de bajo nivel por plataforma, dejando clasificación/consentimiento
  fuera de los drivers.
- `action_loader` y `plugin_loader` comparten descubrimiento/despacho, pero
  tienen fronteras de confianza distintas; extraer tipos comunes solo después
  de documentar esa diferencia.
- `ui.py`/`main.py` son superficies grandes; dividir por capacidad con pruebas
  y API estable, no por una reescritura cosmética.
- Integraciones de mensajería deben permanecer por proveedor, no esconderse
  bajo un sender genérico que no pueda verificar destinatario.
- Reducir afirmaciones manuales de porcentaje y conteos: generar estado desde
  CI/evidencia asociada a un commit o etiquetarlo como histórico.

## 8. Decisiones para acordar con el compañero

1. **Plataforma objetivo:** ¿Windows primero con el rango Python 3.11–3.13, o
   soporte multiplataforma como objetivo activo? Hoy la evidencia fuerte es
   Windows y fixtures UIA.
2. **Modelo de captura:** ¿pantalla/cámara solo bajo petición explícita del
   usuario, o también a petición del modelo dentro de tareas aprobadas? La
   recomendación es empezar solo por petición del usuario.
3. **Permisos reutilizables — decisión tomada:** recordarlos entre reinicios
   durante 30 días, con alcance exacto, revocación visible y aprobación humana.
   Las acciones de alto impacto siguen confirmándose por operación. No está
   implementado todavía; el código actual solo conserva un grant en memoria por
   una hora para `screen_find`.
4. **Plugins externos:** ¿basta confianza explícita en proceso para plugins
   escritos por el usuario, o se necesita sandbox antes de aceptar código de
   terceros? No confundir los dos casos.
5. **Integración prioritaria:** escoger una (Spotify, Gmail de solo lectura,
   Outlook/Graph o Calendar oficial) según el uso real; no iniciar todas a la vez.
6. **Producto distribuido:** confirmar si se planea instalador/actualizador
   firmado o si MARK seguirá siendo un proyecto ejecutado desde Python.
7. **Retención:** definir con precisión qué persiste entre memoria, historial,
   logs, capturas y dashboard.

## 9. Dictamen

**Conservar y endurecer; no reescribir desde cero.** Los riesgos más urgentes
son de consistencia entre el permiso presentado y el ejecutado, captura de
datos visuales y transparencia del efecto de los planes. La base de validación
de argumentos, política fail-closed, confirmación, undo, resultados tipados y
pruebas es reutilizable. Las integraciones deben crecer con adapters
específicos, permisos mínimos y evidencia real acotada.

No declarar “todo P0/P1 cerrado” ni “control universal” mientras la captura
visual y los grants no tengan contrato verificable, los planes no expliquen
efectos por paso y la mensajería continúe sin resultado independiente. No
habilitar uso sensible desatendido a partir de tests sintéticos.

## 10. Redundancia documental y limpieza segura

Este informe absorbe el análisis de Minimax y los hallazgos relevantes de
`SECURITY-REVIEW.md`; la hoja de ruta anterior queda sustituida como plan de
trabajo por [plan_seguimiento.md](./plan_seguimiento.md). Ya no hace falta
mantener tres versiones del mismo estado, porcentajes y recomendaciones.

Antes de borrar los documentos antiguos, comprobar que el compañero los recibió
y que no necesitan conservarse como historia. **Precaución:** `SECURITY-REVIEW.md`
ya tenía cambios locales sin commit al comenzar esta tarea. Aunque sus hallazgos
revisados están consolidados aquí, borrarlo descartaría también esas notas
locales exactas; Git no las recupera si nunca se guardaron en un commit. La
hoja de ruta anterior sí estaba limpia al inicio. No he borrado ninguno de los
dos documentos. Este informe no certifica que toda recomendación esté
arreglada: los pendientes se enumeran en
[plan_seguimiento.md](./plan_seguimiento.md).
