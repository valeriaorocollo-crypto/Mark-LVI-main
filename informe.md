# Informe tecnico de MARK LVI

**Fecha de revision:** 2026-11-09  
**Plataforma observada:** Windows, Python 3.13.14  
**Referencia de producto:** `ROADMAP_CONTROL_UNIVERSAL.md`

## Veredicto ejecutivo

MARK no necesita borrarse y rehacerse desde cero. Tiene una base aprovechable: registro de acciones, contratos de resultado, confirmaciones, adaptador UI Automation, planes acotados, almacenamiento seguro de credenciales y varios pilotos. Pero hoy es un **prototipo de asistente con automatizaciones parciales**, no un controlador universal fiable. No está cerca de una paridad cuantificable del 99.8% con JARVIS, y “control absoluto” no es una meta tecnica alcanzable de forma segura: las APIs, permisos, interfaces de accesibilidad y politicas de cada aplicacion imponen limites reales.

La poda recomendada es **congelar nuevas integraciones y cerrar primero los efectos no verificados**. Se corrigieron los bypasses de clasificacion, los fallos principales de sobreescritura/escritura/undo y se deshabilito la mensajeria generica ciega. Siguen pendientes la validacion real de WhatsApp, los clics heurísticos de Steam, los cambios de firewall al arrancar y el parche global de `subprocess.Popen`. La politica de permisos reutilizables solicitada tampoco existe todavia. Ademas, el informe de seguridad existente contiene texto de una solicitud y de un analisis anterior, por lo que ya no funciona como documento de control limpio.

No recomiendo cortar toda la rama. Si recomiendo cortar el enfoque de “cualquier clic/tecla sirve para cualquier efecto” y el supuesto de que basta con sumar conectores. El nucleo de acciones, los resultados y los planes se pueden conservar despues de cerrar sus contratos y reforzar las pruebas.

## Alcance y honestidad

El inventario actual tiene **125 archivos Python**: 77 fuera de `tests/` y 48 dentro. La compilacion de sintaxis de todos los modulos paso. Hice inspeccion profunda de las rutas con mayor impacto (politica, archivos, mensajeria, control de escritorio, carga de acciones/plugins, dashboard, busqueda, monitor, planificador, Spotify/Gmail, proveedor de voz y configuracion), y busquedas estaticas sobre el resto. Esto **no equivale a una lectura manual, linea por linea, de los 125 archivos** ni a una certificacion de seguridad. No afirmo haber encontrado todos los defectos posibles.

No se inspecciono ni reproduce aqui el contenido de credenciales locales. `git` no esta disponible en el terminal, asi que no pude establecer el estado de cambios locales del repositorio. La revision no accedio a cuentas, no envio mensajes, no instalo dependencias ni cambio configuraciones del sistema.

### Evidencia ejecutada

| Comprobacion | Resultado | Que demuestra y que no |
|---|---|---|
| `Python313\python.exe -m compileall -q .` | Correcto; revalidado | No hay errores de sintaxis detectables; no valida tipos ni comportamiento. |
| `Python313\python.exe setup.py --dry-run` | Correcto; revalidado | Manifiestos y activo presentes. El dry-run no prueba inicio completo, audio, OAuth ni compatibilidad de aplicaciones reales. |
| `Python313\python.exe -m unittest discover -s tests -q` | **439 casos: OK; 13 omitidos** | Suite completa aprobada en Python 3.13.14 despues de las correcciones de Etapas 1-3. Los 13 omitidos son opt-in; no cuentan como validacion de esos entornos. |
| `Python313\python.exe -m pip check` | Sin dependencias rotas | Verifica el entorno actual, no otras versiones de Python ni una instalacion limpia. |
| Chromium headless | `156.0.8078.4`, launch/close correcto | El paquete Python reporta Playwright 1.64.1; `install --list` muestra un identificador beta interno. La automatizacion funciona en este entorno; el workflow registra ambos para seguimiento. |
| HTTPS del dashboard | Certificado/clave generados en un temporal y aceptados por `SSLContext.load_cert_chain`; segunda llamada idempotente | No se modifico `config/certs`, no se abrio puerto ni se verifico confianza desde un telefono/cliente remoto. |
| CI | `.github/workflows/windows-tests.yml` agregado para Windows/Python 3.11-3.13 | YAML parseado y pasos reproducidos localmente en 3.13.14; la ejecucion remota de GitHub Actions aun esta pendiente. |
| `python -m unittest discover -s tests -p test_tool_audit.py` | 12 correctas | Pasa el conjunto existente, pero no cubre los casos peligrosos reproducidos abajo. |
| `get_errors` del editor | Sin diagnosticos | No sustituye a Ruff, Pyright ni una matriz de CI; no se encontro configuracion automatizada de lint/tipos/CI en los archivos enumerados. |
| Reproduccion en carpeta temporal | Confirmada y corregida | Antes, `copy_file` reemplazaba el destino y undo lo eliminaba. Ahora rechaza destinos existentes; los tests verifican que el original queda byte-identico y que no se registra undo. |
| Python 3.13 / `pywin32` | `import win32com.client` correcto; `pywin32_postinstall.py` existe | El aviso de setup no impide importar COM. El registro de componentes/atajos sigue siendo opcional mientras no falle una funcion que lo necesite. |
| Avisos durante tests | Starlette advierte que `TestClient` con `httpx` esta deprecado; una prueba fuerza intencionalmente fallo de certificado para asegurar que no hay downgrade HTTP | No causaron fallos. El certificado real se genero y cargo en un temporal; falta probar el servidor HTTPS desde un cliente local. |

El numero de pruebas de esta ejecucion no coincide con los resultados previos citados en `SECURITY-REVIEW.md` o el roadmap. No deben presentarse resultados historicos como resultado de este checkout.

## Hallazgos priorizados

### P0 — la politica de riesgo no protege efectos opacos

**Estado: corregido para el alcance P0 de despacho y confirmacion.** Antes de la correccion, en `core/tool_audit.py`, varias acciones de control se procesaban primero como “rutinarias”. Si el texto del objetivo no contenia una lista de palabras sensibles, la clasificacion devolvia `state_change`, incluso si la operacion usaba teclado generico, coordenadas o arrastre. `core/action_policy.py` ejecutaba acciones de ese riesgo sin confirmacion central.

Se reprodujo directamente antes del cambio:

| Entrada | Riesgo devuelto |
|---|---|
| `computer_control: press`, tecla `delete` | `state_change` |
| `computer_control: hotkey`, `shift+delete` | `state_change` |
| `computer_control: click`, coordenadas `(500, 300)` | `state_change` |
| `computer_control: click`, objetivo “Alquilar ahora” | `state_change` |
| `computer_control: click`, objetivo “Comprar ahora” | `high` |

La correccion elimino la rama heuristica general y usa la tabla explicita de riesgos para acciones globales. Ahora click/type/press/hotkey/paste/drag genericos quedan en `high`; tambien la lectura del clipboard y la busqueda visual `screen_find`, que envia capturas a Gemini. El dispatcher espera HUD antes de ejecutar. `screen_click` muestra que la pantalla sera enviada a Gemini y pide aprobacion antes de la primera captura; despues revalida el objetivo antes del clic. Una coordenada o etiqueta no rebajan el riesgo. Para no introducir confirmaciones por cada paso rutinario, el foco/activacion de ventana y controles UIA ordinarios con selector exacto mantienen su tratamiento local; etiquetas UIA sensibles siguen elevandose a `high`. Tambien se vinculo el contexto de confirmacion a la firma exacta de herramienta y argumentos: confirmar una accion de una herramienta ya no autoriza otra llamada distinta de esa misma herramienta. `code_helper auto` delega la aprobacion a su handler, que presenta la vista previa del archivo generado.

**Impacto encontrado antes de corregir:** una tecla o clic sobre la ventana equivocada podia borrar, enviar, comprar, guardar o cambiar configuracion sin que la politica lo supiera. El hito 2 y la salida declarada de la Fase 1 siguen sobrestimados hasta verificar todos los caminos, no solo los casos nuevos.

**Validacion del cambio:** las suites focales de politica, UIA, `code_helper`, archivos, mensajeria y dispatch de planes/plugins pasaron; la suite completa registro **439 aprobadas y 13 omitidas**. Las pruebas cubren Delete/Shift+Delete, coordenadas, click sin objetivo, acciones del navegador y ajustes, objetivo UIA “Alquilar ahora”, clipboard, vision antes/despues de HUD, aprobacion exacta, flujo `code_helper auto`, undo condicionado y rechazo de plataformas no verificadas. `screen_process` y la politica de consentimiento/retencion de capturas proactivas siguen pendientes de Etapa 7.

### P0 pendiente — permisos reutilizables solicitados

`core.confirm.request` crea una confirmacion por llamada; no guarda una concesion reusable. El planificador si permite una sola aprobacion para un plan y sus firmas exactas, pero las acciones sensibles sueltas vuelven a preguntar en cada invocacion. Por tanto, el requisito nuevo de “pedir permiso solo la primera vez” **no esta implementado**.

La implementacion segura recomendada es ofrecer “recordar durante esta sesion” solo para una capacidad y objetivo concretos, con expiracion y revocacion visible. No debe inferirse esa concesion de un CONFIRM normal ni persistirse globalmente. Falta definir si el alcance por sesion y objetivo satisface el requisito; no pasar a P2 hasta resolverlo y probar que no autoriza otros destinatarios, rutas o efectos.

### P0 — copia con sobrescritura y deshacer destructivo (corregido)

Antes de la correccion, `copy_file` reemplazaba un destino existente y su undo lo eliminaba en lugar de restaurarlo. La reproduccion temporal confirmo que un destino con `original` acababa borrado tras copiar y deshacer. Ahora la copia rechaza destinos existentes y los archivos nuevos se crean con modo exclusivo, cerrando tambien la carrera entre la comprobacion y la creacion.

**Validacion:** tests temporales verifican que el destino preexistente queda byte-identico y que no se registra undo; una copia a un destino nuevo conserva el origen y crea los bytes esperados. Falta completar la matriz para copias de directorios y cambios posteriores del contenido copiado.

### P1 — escritura/reemplazo sin undo fiable (corregido en la ruta local de texto)

Antes de la correccion, `create_file` podia interpretar una lectura fallida como archivo inexistente y luego borrarlo al deshacer; `write_file` podia ignorar bytes invalidos y escribir sobre binarios o archivos demasiado grandes para respaldar. Ahora ambas funciones exigen un snapshot UTF-8 dentro del limite de 1 MB, rechazan enlaces simbolicos/targets no regulares y no escriben si el respaldo falla. La escritura usa un temporal en el mismo directorio y reemplazo atomico; undo verifica contenido e identidad y deja intacto un archivo que haya cambiado despues.

**Validacion:** las regresiones cubren binario con NUL, archivo existente mayor al limite, creacion nueva, restauracion byte-exacta y modificacion posterior al write. **Pendiente:** fallos de disco/permisos, ACL y volumenes de red; undo automatico de copias de directorios; y pruebas de interrupcion entre snapshot y reemplazo. El acceso sigue restringido al perfil permitido.

### P1 — envio generico de mensajes ciego (deshabilitado; WhatsApp parcial)

Antes de la correccion, `_desktop_send` y los flujos browser de Instagram/Messenger seleccionaban destinatarios y enviaban texto con secuencias de teclas sin verificar ventana o conversacion. Ahora Telegram, Signal, Discord, Instagram, Messenger y servicios desconocidos se rechazan antes del HUD: no se llama a PyAutoGUI, al navegador ni al sender en background. El helper heredado `_desktop_send` es un stub que devuelve fallo sin escribir.

WhatsApp conserva un driver distinto con preflight y lectura posterior, pero el roadmap documenta que la prueba real no pudo activar inequivocamente la fila del contacto y una exploracion abrio el chat propio. Su validacion sigue incompleta; no se debe presentarlo como envio fiable ni permitir grants reutilizables para WhatsApp hasta verificar conversacion, destinatario y lectura posterior en una matriz de versiones.

**Validacion:** una regresion cubre Telegram, Signal, Discord, Instagram, Messenger y plataforma desconocida; todas fallan sin HUD ni llamadas a sender/browser. La suite general registro **439 aprobadas y 13 omitidas**. No reactivar ninguna plataforma sin un adaptador especifico que verifique destinatario y resultado.

### P1 — integracion Steam incluye clic a ciegas

En `actions/game_updater.py`, `_click_first_profile_by_screenshot` busca una zona de color como aproximacion a un avatar; si no encuentra ese patron, hace clic en una coordenada estimada y devuelve exito. Hay otros clics por coordenadas en el flujo de instalacion. Esto contradice el principio de “detenerse ante ambiguedad” del roadmap y es especialmente delicado en una aplicacion con perfiles, dialogs y descargas.

**Corte recomendado:** eliminar el fallback “clicking by guess”. Si UIA o un control semantico no identifican un unico objetivo, detenerse y pedir intervencion. Para instalar/actualizar, previsualizar juego, cuenta, disco y espacio, y verificar el estado real despues.

### P1 — dashboard con privilegios y cambios colaterales de red

`dashboard/server.py` configura acceso de red en segundo plano. En Windows puede solicitar elevacion UAC, crear reglas de firewall, borrar reglas de bloqueo existentes para Python y cambiar perfiles `Public` a `Private`. `main.py` crea y sirve el dashboard durante la ejecucion. Aunque la funcion sea optativa desde el punto de vista de producto, una decision de conectividad no debe modificar varios ajustes del sistema como efecto lateral de iniciar el asistente.

El dashboard usa certificado autofirmado. TLS cifra la conexion, pero por si solo no prueba que el telefono se conecto al servidor esperado. El codigo deriva clave de emparejamiento con PBKDF2 y usa AES-GCM; eso mejora protecciones, pero no elimina los riesgos de confianza de certificado, exposicion LAN, comandos remotos ni cambios del firewall.

**Corte recomendado:** deshabilitar cambios automaticos del firewall/perfil. Mostrar una vista previa exacta y ofrecer instrucciones manuales o una regla estrictamente limitada al puerto, perfil y ejecutable elegidos. El control remoto debe ser opt-in, apagado por defecto y con autenticacion y revocacion verificables.

### P1 — parche global de `subprocess.Popen`

Al importar `main.py` en Windows, se sustituye `subprocess.Popen` globalmente, se agrega `CREATE_NO_WINDOW` a todas las llamadas y se descarta `startupinfo`. Esto modifica tambien el comportamiento de librerias que no pertenecen a MARK y hace que depurar o controlar procesos concretos sea menos fiable.

**Corte recomendado:** eliminar el monkey patch. Pasar `creationflags` solo a las llamadas locales que realmente requieran ocultar consola y mantener intactos los parametros del llamador.

### P1 — plugins Python sin aislamiento

`core/plugin_loader.py` importa codigo Python de plugins en el mismo proceso de MARK. La clasificacion como `external` y la confirmacion ocurren durante el despacho, pero no aislan el codigo: el modulo puede ejecutar instrucciones durante su importacion y un plugin activo tiene los permisos del proceso. Un HUD no protege contra efectos laterales de importacion ni contra codigo hostil o defectuoso.

**Corte recomendado:** tratar plugins como codigo confiable instalado por el usuario, no como extensiones seguras por tener un permiso. Para terceros, usar proceso separado con IPC, permisos por capacidad, timeout/cancelacion y formato de datos acotado. No cargar plugins no confiables en el proceso principal.

### P2 — la suite depende de un entorno reproducible y algunas pruebas necesitan aislamiento

El primer intento se ejecuto con Python 3.14 y dependencias ausentes, y por eso produjo fallos de importacion y pruebas que no alcanzaron la confirmacion. La repeticion inicial con Python 3.13.14 aprobo 427 pruebas; despues se añadieron tests HTTPS, politicas, operaciones de archivo y bloqueo de mensajeria ciega, llevando la suite a **439 aprobadas y 13 omitidas**. Por tanto, los fallos iniciales eran del entorno equivocado y **no son un fallo actual reproducible con el interprete soportado**. La matriz 3.11-3.13 aun no tiene resultados remotos de CI.

**Corte recomendado:** conservar Python 3.13.14 como entorno verificado, incorporar CI para el rango declarado y separar tests puros de las suites opt-in de escritorio, audio y browser. Las pruebas de politica deben simular adaptadores y comprobar el gate sin depender de un dispositivo o ventana real.

## Arquitectura, mantenimiento y obsolescencia

### Monolitos y responsabilidades superpuestas

Medicion actual de lineas en los modulos mas grandes:

| Archivo | Lineas | Problema de mantenimiento |
|---|---:|---|
| `ui.py` | 6.713 | HUD, settings, dashboard, plugins y controles en un unico modulo. Cambios pequeños tienen alto riesgo de regresion. |
| `main.py` | 2.736 | Orquestacion de voz, modelo, herramientas, eventos y dashboard, ademas del parche global de procesos. |
| `actions/browser_control.py` | 1.696 | Ciclo de vida del navegador, navegacion, formularios, selectors y vision demasiado acoplados. |
| `actions/file_processor.py` | 1.405 | Muchas transformaciones con formatos, dependencias y contratos de salida distintos. |
| `dashboard/server.py` | 1.318 | HTTP/WebSocket, autenticacion, TLS, firewall, uploads y control remoto en un unico servidor. |
| `actions/computer_control.py` | 1.130 | UIA, coordenadas, procesos, portapapeles, captura y teclado mezclados. |
| `actions/computer_settings.py` | 1.075 | Muchas rutas por SO, subprocess, teclas y ajustes del sistema. |
| `actions/game_updater.py` | 1.063 | Steam discovery, scraping, instalacion, captura, clics y seguimiento en el mismo modulo. |
| `providers/engine_pipeline.py` | 1.044 | STT, VAD, LLM, llamadas de herramientas, TTS, historial y tiempos. |
| `core/task_plan.py` | 920 | Validacion, estado, aprobacion, persistencia, recuperacion y progreso acoplados. |
| `memory/config_manager.py` | 885 | Configuracion general, credenciales, migraciones y almacenamiento seguro en un archivo. |

No es un argumento para reescribir todo en microservicios. Es un problema de limites de responsabilidad y facilidad para probar. Extraer por contratos estables, despues de fijar regresiones, y no por tamaño solamente.

### Duplicacion y deriva de conceptos

- Acciones de ventana/teclado aparecen en `actions/computer_control.py`, `actions/computer_settings.py`, `actions/desktop.py` y `actions/open_app.py`; cada ruta puede tener validacion, espera y resultado distinto. Definir un solo adaptador OS y delegar, sin multiplicar controladores.
- `actions/send_message.py` mezcla transporte verificable de WhatsApp con automatizacion generica no verificable de otras apps. Separar por conectores y no exponer una capacidad universal que no existe.
- `core/action_loader.py` y `core/plugin_loader.py` implementan esquemas parecidos de descubrimiento y despacho. Hay duplicacion, pero fusionarlos sin aclarar el nivel de confianza de cada uno podria empeorar el aislamiento.
- El producto aparece como MARK, JARVIS y “MARK LIV” en codigo, UI, dashboard e instalador. Elegir un nombre canonico y dejar aliases solo donde sean necesarios.
- `actions/computer_settings.close_app` es una negativa heredada, no una implementacion. Esta comentada extensamente y direcciona a `computer_control`; mantenerla como compatibilidad puede ser razonable, pero debe aparecer como deprecated y no como capacidad activa.

### Dependencias y compatibilidad

- `setup.py` marca Python 3.11–3.13 como el rango soportado y permite continuar con versiones posteriores bajo advertencia. Esta revision se ejecuto con Python 3.13.14 y la suite aprobo; no se certificaron Python 3.11/3.12 ni versiones posteriores a 3.13.
- `requirements-base.txt` incluye capacidades pesadas o de integracion (Playwright, OpenCV, `yt-dlp`, PyAutoGUI, Pyperclip y procesamiento de presentaciones) aunque la documentacion lo llama “core”. Eso aumenta instalacion y superficie de fallos aunque el usuario solo quiera voz/chat. Separar base minima de extras reales.
- Varias dependencias no tienen limites de version, entre ellas `yt-dlp`, `pyautogui`, `pyperclip` y `python-pptx`. Sin lockfile ni resolucion fijada, dos instalaciones del mismo commit pueden diferir.
- `setup.py --dry-run` solo valida que existan manifiestos/activos. No comprueba resolver, instalar, importar el conjunto, dispositivos de audio o iniciar la aplicacion limpia.
- El proyecto anuncia soporte para varios sistemas operativos, pero `core/ui_adapter.py` declara Windows como unico adaptador de UI Automation. Las acciones multiplataforma tienen ramas distintas y no hay evidencia equivalente de compatibilidad. Si la meta inmediata es Windows, estrechar el soporte documentado y probar Windows en una matriz real es mas sensato que fingir paridad multiplataforma.

### Documentacion y estado de hoja de ruta

`SECURITY-REVIEW.md` empieza como una nota acotada al dashboard, pero despues de la seccion de limites contiene separadores y texto pegado de una solicitud/informe anterior. Mezcla alcance, hallazgos, comentarios de trabajo y cifras de versiones distintas; debe sanearse y separar el registro de hallazgos de las notas del usuario.

La hoja de ruta llama completadas las Fases 1–4 dentro de alcances sinteticos/locales. La clasificacion de riesgo reproducida invalida la afirmacion de que las acciones tienen proteccion suficiente. “100% de hitos” es un porcentaje de checklist, no un porcentaje de compatibilidad, seguridad ni madurez del producto. La Fase 5 sigue parcial; las Fases 6–7 tambien. Los valores publicados de pruebas/archivos deben generarse desde CI o eliminarse como numeros manuales.

## Cobertura real de la vision por aplicacion

| Capacidad solicitada | Estado observado | Dictamen |
|---|---|---|
| Spotify | Plugin OAuth PKCE y alternativa UIA Windows. El roadmap informa una prueba real de una pista, verificada por el estado UI de Spotify. | Piloto util, pero no prueba sonido audible, otras versiones/idiomas ni todos los comandos. No es control total. |
| Navegador | Playwright con perfil de automatizacion separado/persistente y control generico; el modulo no carga si Playwright falta. | Parcial. Sesiones/cookies no equivalen a las del navegador personal; sitios y controles complejos no heredan compatibilidad. |
| Sistema operativo | Acciones de teclado/raton, ventana, audio/brillo, algunos procesos y UIA. | Control parcial. La automatizacion generica es la brecha P0; no entregar privilegios de administrador por defecto. |
| Archivos del sistema | `file_controller` restringe rutas a `Path.home()`; lectura/escritura y operaciones con archivos son principalmente del usuario. | No controla archivos del sistema, por diseño. No ampliar a `C:\`/root: usar capacidades administrativas concretas, separadas y aprobadas. |
| WhatsApp | Driver UIA en Windows, pero la propia hoja de ruta deja bloqueado el envio real porque no pudo verificar la conversacion correcta. | No habilitar envio como fiable hasta completar una validacion real y repetible. |
| Reproductor multimedia | Acciones basicas y apertura/busqueda de YouTube; la hoja de ruta dice que no hay verificacion uniforme de reproduccion. | Parcial. No hay integracion universal con cualquier reproductor ni evidencia de audio/video efectivamente reproducido. |
| Outlook | No hay conector Outlook/Graph ni prueba real registrada. | No implementado. Abrir la aplicacion no es integrarla. |
| Agenda/Calendar | No hay conector Calendar real. `calendar_control` aparece en clasificación, no prueba que exista un plugin funcional. | No implementado; faltan OAuth, eventos, zonas horarias, recurrencias, conflictos y verificacion. |
| Noticias internacionales/nacionales/regionales | `web_search` usa Gemini/DDG; el lugar se guarda como preferencia y la busqueda reciente filtra por fechas interpretables. | Parcial. El roadmap reconoce resultados locales mezclados, relevancia geografica no demostrada y fechas dependientes de fuentes. No se observa un asistente inicial obligatorio; el valor por defecto es Peru. |
| Administrador de tareas | Lectura limitada de procesos ordenados por RAM y cierre de app con nombre. | No equivale al Administrador de tareas: sin control completo de servicios, procesos, prioridad, recursos o permisos. |
| Administrador de equipos / Device Manager | No hay conector especifico encontrado. | No implementado. |
| Configuracion / Panel de control | Algunas acciones concretas y `open_app`; no hay API semantica de todo Settings/Control Panel. | Parcial y dependiente de Windows/UIA; el nombre del atajo no garantiza cambio ni verificacion. |
| WinRAR | No hay plugin/conector especifico. El lector de documentos/archivos no es WinRAR. | No implementado. |
| Steam | `game_updater` lee manifiestos de Steam e instala/actualiza ciertos titulos con automatizacion parcial. | Integracion parcial, no control completo de biblioteca, tienda, chat, configuracion o compras. Incluye clics heurísticos que deben eliminarse. |
| Git | Alias de apertura/terminal no equivale a una integracion Git. | No se encontro flujo especifico de repositorios, ramas, diff, conflictos, commits o verificacion. |
| Visual Studio / VS Code | `code_helper` y `dev_agent` generan/editan archivos/proyectos; hay soporte de abrir aplicaciones. No se encontro extension IDE/LSP integrada como contrato principal. | Asistente de codigo parcial; no asumir que controla Visual Studio IDE ni que opera dentro de VS Code como un desarrollador con estado verificado. |

Las APIs oficiales no son intercambiables ni garantizan todas las acciones. Cada proveedor define OAuth, scopes, permisos, cuotas, tipo de cuenta y politicas. Automatizar la interfaz es un fallback fragil, no un sustituto equivalente.

## Rendimiento

Hay esfuerzos utiles: importaciones diferidas, presupuestos de herramientas, cache de algunos datos, limites de navegador y tiempos por turno en `providers/engine_pipeline.py`. Por tanto, no es correcto decir que no hay instrumentacion. Pero la telemetria actual imprime etapas/tiempos y no ofrece un conjunto persistente de P50/P95 por recorrido completo, equipo, proveedor, accion y resultado. No hay base para declarar que una optimizacion determinada resolvera “se demora mucho”.

La ruta local descrita en el codigo encadena STT → LLM → herramienta → segunda ronda de LLM → TTS; se estima en comentarios aproximadamente 1.5–4 s para turnos normales y dos rondas de modelo cuando se invoca una herramienta. Son estimaciones documentadas, no mediciones de este equipo. Hay esperas fijas en automatizacion de escritorio y el dashboard consulta metricas CPU con intervalo de 0.2 s. Ejecutar acciones UI en paralelo seria una mala optimizacion: comparte foco y produce carreras.

**Plan de medicion:** registrar monotonicamente fin de voz, STT, primer token/respuesta, llamadas por herramienta, duracion/red, verificacion y primer audio. Reportar P50/P95 por capacidad y motor, con opt-in y sin guardar texto, rutas ni capturas. Luego quitar esperas fijas reemplazandolas por condiciones observables con timeout y cancelacion. Comparar misma tarea/equipo antes y despues.

## Desajustes con la hoja de ruta

1. **Fase 1:** no considerar cerrados los hitos de clasificacion/proteccion mientras teclas, combinaciones y coordenadas caigan en `state_change` sin confirmacion. La prueba actual `test_tool_audit.py` pasa 12 casos, pero no contiene estos ejemplos.
2. **Fases 2–4:** sus porcentajes solo representan pruebas locales o fixtures sinteticos; no autorizan compatibilidad con aplicaciones reales. Dry-run no es instalacion limpia completa; fixtures UIA no son Outlook, WhatsApp, Steam ni Office.
3. **Fase 5:** correcto mantenerla parcial. Outlook, Calendar, WinRAR, Device Manager y Git no tienen integracion completa. WhatsApp sigue con una limitacion real documentada; Spotify es el piloto con evidencia real mas concreta.
4. **Fases 6–7:** idempotencia tras reinicio, compatibilidad por version/idioma/escala, privacidad unificada y resistencia a prompt injection permanecen parciales. No elevar el estado por agregar pruebas sinteticas solamente.
5. **Resultado:** cambiar la salida del roadmap para que cada hito cite evidencia reproducible (comando, test, version de app/SO y fecha); no declarar una fase cerrada cuando una prueba adversarial critica la contradice.

## Poda recomendada: orden de trabajo

### Puerta 0 — congelar alcance y corregir afirmaciones

- No añadir conectores ni permisos de administrador mientras existan los P0/P1 de este informe.
- Corregir `SECURITY-REVIEW.md`: retirar texto pegado ajeno al registro, preservar el analisis previo en otro archivo solo si es historicamente necesario y fechar/versionar hallazgos.
- Definir como producto: “asistente de tareas con adaptadores verificables”, no “omnipotente/control absoluto”. La accion no soportada debe detenerse con una explicacion.

### Puerta 1 — seguridad de efectos

- Corregir politica de riesgo y escribir pruebas para Delete, hotkeys, coordenadas, compras/alquileres, destinos ambiguos y herramientas desconocidas.
- Corregir copia, reemplazo, escritura binaria/ilegible y atomicidad; demostrar restauracion del estado previo.
- Deshabilitar mensajeria generica ciega y eliminar clics heurísticos de Steam.
- Deshabilitar mutaciones automaticas de firewall/perfil; quitar el parche global de `Popen`.

### Puerta 2 — base reproducible

- Mantener Python 3.11–3.13 como rango declarado y crear CI que pruebe sus versiones soportadas; decidir con evidencia si una version posterior entra en la matriz.
- Crear instalacion base minima, extras reales por capacidad y lock/resolucion reproducible. Ejecutar CI sin secretos ni cuentas; las integraciones reales quedan en una matriz manual opt-in.
- Mantener tests puros sin Playwright/audio/UIA; separar los tests de hardware/desktop como suites opt-in con reporte de skip explicito.

### Puerta 3 — integraciones por valor

- Priorizar una por una: Spotify (terminar matriz), Calendar oficial, Outlook via Microsoft Graph si es el objetivo, WhatsApp solo por una ruta autorizada y soportada, luego navegador y herramientas de desarrollo.
- Para cada conector: scopes minimos, revocacion, permisos, vista previa, confirmacion de efectos, clave de idempotencia cuando aplique, verificacion posterior y pruebas de expiracion/timeout/reintento. No compartir “compatibilidad” entre aplicaciones.
- Definir por separado Git, Visual Studio/VS Code, WinRAR, Device Manager y multimedia; abrir un exe no cuenta como integrar el producto.

### Puerta 4 — modularizar sin reescritura masiva

- Extraer primero telemetria, flujo de sesion, dashboard, funciones de archivos y conectores de `ui.py`, `main.py`, `file_processor.py` y `computer_control.py` por contratos pequeños.
- No hacer refactor estilistico amplio mientras no haya tests que detecten efectos erroneos. Cada extraccion conserva API y agrega una prueba focal.

## Decision final

**No reiniciar desde cero. Si podar antes de crecer.** Lo que se debe cortar ahora son las rutas de efectos opacos sin verificacion y la etiqueta de “universal” cuando solo existe una automatizacion generica. La base reutilizable es el contrato de resultado, planificador, adaptador UIA, almacenes de configuracion/credenciales y plugins confiables; sus limites necesitan pruebas y el cargador de plugins no debe confundirse con sandbox.

No declares MARK listo para uso desatendido con archivos sensibles, mensajes, instalaciones o cambios de red. Primero cierra los hallazgos P0/P1 y vuelve a ejecutar la suite en un entorno reproducible. El proyecto puede crecer bien, pero hoy la hoja de ruta expresa mas madurez que la evidencia real.