# Informe final de situación — MARK LVI

**Fecha de consolidación:** 11 de noviembre de 2026
**Base examinada:** commit `d2fc6470011d0a6b08bc696bb51f2daa30acb253` de
`Mark-LVI-main`; la CI
[42986772997](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42986772997)
pasó en Python 3.11–3.13. Se publicaron los artefactos
`windows-ci-evidence-py3.11`, `windows-ci-evidence-py3.12` y
`windows-ci-evidence-py3.13`. La suite local pasó con 506 pruebas por versión;
las 10 pruebas UIA opt-in pasaron en Windows/Python 3.12. La inspección visual
del HUD y el flujo de permisos se probaron localmente con datos sintéticos y
almacén temporal; no se usó proveedor, captura real ni almacén de producción.
Después de la CI solo se actualizaron estos informes.

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

Estado actualizado de las prioridades:

1. **P0 privacidad implementado:** las rutas de captura requieren aprobación
   HUD o un grant exacto de tarea; se muestran fuente/proveedor, indicador y
   controles de cancelación. La UIA, inspección visual local y flujo de grant
   con almacén aislado pasaron. La CI del ajuste de legibilidad pasó en las tres
   versiones.
2. **P0 grants implementado localmente:** permisos persistentes por perfil,
   alcance hash de tarea, vencimiento fijo de 30 días, uso/revocación visibles
   y rechazo seguro ante almacén inválido. UIA sintética y el flujo local de
   creación/visualización/revocación con almacén temporal pasaron; la CI del
   commit integrado también pasó. No se usó un proveedor real ni el almacén real.
3. Mostrar los efectos reales de cada paso del plan. El campo `effect` se
   calcula hoy a partir del estado `"started"`/`"unknown"` y la vista previa no
   presenta efectos por paso.
4. Mantener bloqueadas las integraciones externas cuyo resultado real no está
   verificado, especialmente envío de mensajes. No repetir acciones ambiguas.
5. La matriz local completa y la CI remota del commit integrado
   `d2fc647` pasaron en Python 3.11–3.13. No atribuir a las pruebas sintéticas
   validación de aplicaciones reales.

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
- Se ejecutó la matriz local en Python 3.11/3.12/3.13 y las 10 pruebas UIA
  opt-in pasaron con ventanas sintéticas; no se validó una instalación limpia
  ni aplicaciones reales.
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
| Commit de código validado | `d2fc6470011d0a6b08bc696bb51f2daa30acb253` | La CI, UIA y suite local cubren este commit integrado. |
| Commit documental | `a32149b5069464a680acc8c8e0d8391e9da7e224` | Actualiza estos dos informes sin cambiar código ni pruebas; la CI del commit documental también pasó en Python 3.11–3.13 ([run 42987653025](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42987653025)). |
| Código Python | 129 archivos en el árbol examinado, contando `tests/` | Recuento de archivos, no medida de madurez. |
| Pruebas | 51 archivos de prueba encontrados | Hay cobertura amplia, pero también skips y dependencias de entorno. |
| Ejecución local de unittest | Python 3.11/3.12/3.13: 506 pruebas por versión, 0 fallos, 0 errores; 13/12/13 omitidas | Los skips no cuentan como aprobados; las pruebas incluyen regresión de ajuste de texto del panel de permisos. |
| UI Automation | 10/10 pruebas opt-in aprobadas en Windows/Python 3.12 | Ventanas sintéticas locales; no valida aplicaciones reales. |
| HUD y grants | Banners, controles tipados, grant, panel y revocaciones probados localmente | Almacén temporal aislado; no se capturó/transmitió imagen ni se modificó el almacén real. |
| Validaciones locales adicionales | `compileall`, `setup.py --dry-run` y `pip check` pasan en las tres versiones | No sustituyen CI ni instalación limpia. |
| Warnings vistos | Aviso deprecado `Starlette TestClient`/`httpx`, aviso `pynvml` y mensajes UIA/asyncio/COM del entorno | No hicieron fallar la suite; no se ocultaron ni se consideran resueltos. |
| Workflow | Run 42986772997, matriz Python 3.11/3.12/3.13, éxito en las tres versiones | [GitHub Actions](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42986772997), commit `d2fc6470011d0a6b08bc696bb51f2daa30acb253`; artefactos de evidencia disponibles por intérprete. |
| Evidencia versionada | `evidence/stage0-windows-2026-11-10.json` | Registra un corte anterior: 474 pruebas, 13 omitidas por intérprete, y el run CI 42948215095 en un commit previo. |
| CI previa | Run 42983995841 pasó para el commit base `a4a2ed4` | Antecedente; la validación del commit actual es el run 42986772997. |
| `ui_holo.py` | No está presente ni versionado en el árbol actual | En la suite se observó el fallback “Holographic chrome unavailable”; la interfaz usa paneles simples. El módulo cosmético es opcional, pero hoy no está incluido. |

La discrepancia entre `506/13`, `506/12`, `506/13` en esta matriz local,
`474/13` en el JSON de Etapa 0 y otras cifras antiguas es de **cortes
distintos**, no evidencia de que se hayan ejecutado todas sobre el mismo código.
Los skips de la suite completa son: una prueba de symlinks no disponible en el
entorno, una prueba DOCX que pasa solo en 3.12 por dependencia opcional, una
prueba Excel omitida por `pandas`/`openpyxl` y diez pruebas UIA opt-in que se
omitieron en esa corrida y luego pasaron por separado en Windows/Python 3.12.
Los nombres y motivos completos están en [plan_seguimiento.md](./plan_seguimiento.md).
El número válido siempre debe citar intérprete, árbol/commit, comando y skips.

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

### P0 — Capturas visuales protegidas; integración real pendiente

Las rutas de captura revisadas requieren una confirmación humana en el HUD o
un grant vigente ligado a la misma tarea; la petición del usuario por sí sola
no autoriza compartir una imagen con Gemini. `screen_process` exige aprobación
para cámara y admite un grant exacto solo para pantalla. `screen_find` limita
el permiso al hash de la tarea, y las rutas locales de `computer_control` y
`browser_control` guardan en un destino elegido explícitamente sin transmitir
la imagen. `screen_debug` informa el proveedor antes de capturar/enviar y
limpia su archivo temporal.

El indicador identifica la fuente y el destino antes de leer la imagen; las
rutas comprobadas consultan la señal de parada antes de capturar o transmitir.
Las pruebas unitarias cubren aprobación, cancelación, parada, orden del
indicador y transmisión. La suite completa del árbol actual pasó localmente en
Python 3.11/3.12/3.13.

**Estado:** corregido; la suite local de 506 pruebas por versión, la CI del
commit integrado, las 10 pruebas UIA y la inspección visual local pasaron. El
flujo de grant y revocación se ejercitó con un almacén temporal aislado; no se
usó una captura, proveedor o aplicación real.

### P0 — Permisos de captura persistentes y delimitados

`core/session_grants.py` almacena grants locales en JSON versionado y con
escritura atómica, vinculados a un perfil local y a un hash normalizado de la
tarea. La capacidad y el proveedor forman parte del alcance; los registros
inválidos o de otro perfil fallan cerrados. El vencimiento es fijo a 30 días y
no se desliza por uso. El HUD muestra el alcance, plazo y uso reciente, permite
revocar un permiso o todos, y avisa que el grant se conserva aunque falle la
operación aprobada. Las decisiones de concesión son tipadas; texto no confiable
no puede crear un grant. La UI no sincroniza permisos entre perfiles/equipos.

Las pruebas cubren persistencia tras recarga del almacén, aislamiento de
perfil, expiración exacta, alcance, uso, revocación y auditoría metadata-only.
Los eventos recientes son metadata-only y acotados en memoria; los metadatos de
uso del grant activo se persisten.

**Estado:** implementado; UIA, flujo visual local y creación/lectura/revocación
en un almacén temporal aislado aprobados. La suite existente cubre recarga,
vencimiento y aislamiento de perfil; la CI del commit integrado pasó. No se usó
el almacén real ni un proveedor externo.

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
2. **Modelo de captura — implementado:** las llamadas de herramienta, incluso
   las derivadas de una petición del usuario, usan la misma puerta de
   consentimiento o un permiso persistente exacto; no hay captura automática
   sin una de esas decisiones.
3. **Permisos reutilizables — implementado localmente:** permisos por perfil
   durante 30 días, alcance exacto, revocación visible y aprobación humana.
   Las acciones de alto impacto mantienen su confirmación por operación. La
   validación visual local y el flujo de grants con almacén temporal pasaron;
   no se utilizó un proveedor real.
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

Los P0 de captura y grants están implementados; la suite local actual, CI,
UIA sintética y aceptación visual/flujo local de permisos están aprobados. No
se probó proveedor o aplicación real. No declarar “todo P0/P1 cerrado” ni
“control universal” mientras las validaciones de producto sigan abiertas, los
planes no expliquen efectos por paso y la mensajería continúe sin resultado
independiente. No habilitar uso sensible desatendido a partir de tests
sintéticos.

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
