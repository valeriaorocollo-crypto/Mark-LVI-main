# Plan de seguimiento para enderezar MARK LVI

**Fecha:** 2026-11-10  
**Base:** [informe.md](informe.md) y `ROADMAP_CONTROL_UNIVERSAL.md`  
**Prioridad:** primero evitar efectos incorrectos y perdida de datos; despues ampliar capacidades.

## Seguimiento de ejecucion

| Etapa | Estado | Evidencia |
|---|---|---|
| Etapa 0: entorno reproducible | **Completada.** | Windows 10 build 19045; suites locales en Python 3.11.9, 3.12.10 y 3.13.14: 474 ejecutadas, 461 aprobadas y 13 omitidas. `compileall`, setup dry-run, `pip check`, Chromium headless (156.0.8078.4) y prueba HTTPS local pasan. CI remota en [run 42948215095](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42948215095), commit `bd6c9ccd61dd6f83854b13e7b42fe0ccc7dfabde`: los tres jobs (Python 3.11.9, 3.12.10 y 3.13.17) finalizaron en verde; versiones, pruebas y resultados se guardaron en artefactos CI por 14 días. |
| Etapa 1: politica de efectos | **Contrato de efectos y fail-closed implementados; matriz remota de esta revisión pendiente.** | `classify_action_effect` separa lectura, navegación, cambio local reversible/destructivo, comunicación externa y operación financiera/administrativa. Teclado/ratón genéricos, acciones de ventana sin alcance y destinos ausentes fallan cerrados; escribir/invocar controles UIA siempre requiere confirmación, independientemente de su etiqueta. Las confirmaciones muestran selector/alcance y redactan entradas sensibles. Dispatcher, registries de acciones/plugins, planes compuestos y handlers críticos directos pasan por la política. Suite completa local: 485 pruebas, 472 aprobadas y 13 omitidas en Python 3.11, 3.12 y 3.13. |
| Permisos reutilizables | **No requeridos para un primer piloto P2 acotado.** | El plan compuesto tiene una aprobación por plan con pasos exactos. Las acciones sensibles sueltas conservan confirmación por operación; no existe “recordar permiso”. Un piloto inicial debe mantener ese modo, sin grants nuevos. Si luego se proponen grants, deben ser de sesión, ligados a capacidad/objetivo, visibles y revocables; nunca permiso global implícito. |
| Etapa 2: archivos P0/P1 | **Validada en entorno local acotado; cancelación real del HUD verificada.** | Copia no reemplaza destinos; escrituras rechazan binarios/no UTF-8/NUL, enlaces y archivos >1 MB, son atómicas y el undo comprueba contenido e identidad. Pasaron ACL NTFS denegada, escritura/undo en medio removible, y escritura/undo del controlador sobre SMB UNC. Un VHDX temporal produjo ENOSPC real: el original quedó intacto y no quedaron temporales ni undo. Una prueba real en MARK registró `Awaiting confirmation` y luego `Cancelled`; el archivo temporal de prueba no fue creado. |
| Etapa 3: mensajería/escritorio | **Fail-closed y parcialmente validada en apps reales.** | Se ajustó el driver UIA para aceptar una fila de búsqueda cuyo nombre exacto va seguido de metadatos, revalidar el encabezado y recuperar el foco de forma acotada; 19 pruebas del driver pasan en Python 3.11-3.13. El chat “Mi Princesa” y el HUD con destinatario/texto exactos se verificaron. Con el cambio cargado, un intento devolvió `status=failed` y el último `status=unverified`; UIA no encontró el texto, aunque el usuario indicó que sí se envió. No repetir sin verificar el chat. Steam real abrió el diálogo de instalación de Left 4 Dead 2 y dejó la biblioteca/instalación bajo control humano; no se completó una instalación. |
| Privacidad de captura | Pendiente en Etapa 7; no bloquea el cierre de la politica de efectos de Etapa 1. | `screen_process` puede adjuntar capturas solicitadas a la conversacion del modelo. Definir consentimiento/indicador y retencion antes de habilitar captura proactiva o automatica. |

La matriz de Etapa 0 pasó en Windows 10 build 19045 con Python 3.11.9, 3.12.10 y 3.13.14: **474 pruebas ejecutadas, 461 aprobadas y 13 omitidas por versión**, junto con `compileall`, `setup.py --dry-run`, `pip check` y Chromium headless 156.0.8078.4. Las 13 omisiones locales son una prueba de enlace simbólico no disponible en este entorno, dos pruebas de extras documentales opcionales y diez pruebas UIA opt-in; estas últimas pasaron por separado en Python 3.13 sobre ventanas sintéticas. Playwright Python 1.64.1 y driver 1.64.0-beta están en la misma línea 1.64 y el navegador arranca en las tres versiones. Se añadió una prueba HTTPS/TLS que inicia el dashboard en loopback, confía solo en el certificado temporal y obtiene 200; no abre firewall ni escribe el certificado real. MARK se inició con Python 3.13.14 y se comprobó el ejecutable del proceso; cerró normalmente. En ese arranque faltaba el extra opcional `openwakeword`, por lo que la palabra de activación no quedó disponible. La validación LAN anterior desde el ASUS alcanzó HTTPS, pero falta verificar allí la confianza del certificado y no se emparejó; no bloquea esta etapa porque la conexión local confiada por HTTPX sí pasó. Las pruebas reales de ACL, medio removible, SMB, ENOSPC y cancelación HUD constan como completadas; Steam abrió el diálogo, sin completar instalación. El envío autorizado de WhatsApp quedó `unverified`; no se reintentó. La CI remota de Etapa 0 del commit `bd6c9ccd61dd6f83854b13e7b42fe0ccc7dfabde` (run 42948215095) pasó en Python 3.11.9, 3.12.10 y 3.13.17; los artefactos incluyen las versiones y los resultados por job. En la revisión actual, la suite completa pasó también localmente en 3.11, 3.12 y 3.13: 485 pruebas, 472 aprobadas y 13 omitidas por entorno/opt-in. `screen_process` sigue en seguimiento de privacidad y no se habilita como captura proactiva.

## Modelo de permisos propuesto

La aprobacion se clasifica por efecto y alcance, no solo por herramienta:

| Nivel | Comportamiento | Ejemplos iniciales |
|---|---|---|
| Sin HUD | Se ejecuta si la accion esta limitada y es de bajo riesgo; mantiene registro y verificacion. | Buscar noticias, leer archivos/ventanas permitidos, abrir una app, reproducir/pausar una pista, volumen. |
| Grant reutilizable de sesion | Una aprobacion inicial autoriza una capacidad concreta dentro de un alcance visible; no expira al cerrar MARK o por timeout y se puede revocar desde el HUD. Primera version solo en memoria, nunca permanente. | Enviar capturas solicitadas a Gemini durante esta sesion; enviar mensajes solo a contactos permitidos; crear eventos sin invitados en un calendario seleccionado. |
| Confirmacion por operacion | Se confirma cada efecto porque cambia mucho el objetivo o el impacto es dificil de revertir. | Comprar/alquilar, borrado permanente o sobrescritura, destinatario no permitido/ambiguo, invitaciones externas, cambios de firewall/seguridad y acciones administrativas. |

Reglas de implementacion antes de habilitar grants:

1. El grant nace de un control humano del HUD, no de texto, argumentos ni una instruccion del modelo. La opcion separada debe decir “permitir durante esta sesion” y mostrar capacidad, plataforma, destinatarios/rutas/calendario y expiracion exactos.
2. Autorizar por `(capacidad, integracion, recurso/objetivo, sesion, vencimiento)`. No hay comodin universal. Cambiar contacto, calendario, ruta, cuenta o efecto queda fuera del grant.
3. Las acciones de alto impacto conservan confirmacion por operacion aunque exista otro grant. Un permiso de mensajeria no cubre compras ni cambios de cuenta; una captura local no autoriza enviar la imagen a un proveedor remoto.
4. Mensajeria puede evitar prompts repetidos solo para contactos previamente permitidos. Contacto nuevo/ambiguo, grupo nuevo o texto que el usuario no solicito claramente exige confirmacion. Calendar puede permitir crear eventos sin invitados en el calendario aprobado; enviar invitaciones o borrar/modificar un evento requiere confirmacion salvo grant especifico y visible.
5. Captura visual bajo grant se toma solo cuando una tarea activa la necesita, con indicador visible; no habilita grabacion ni captura en segundo plano. No conservar imagenes despues de la tarea por defecto.
6. El grant se revoca al cerrar sesion, al vencer, al cerrar sesion/cambiar cuenta de la aplicacion o mediante “REVOCAR”. La auditoria guarda solo metadatos de grant/uso, nunca cuerpos, capturas o secretos.
7. El dispatcher verifica el grant y su alcance antes del handler. Los planes muestran los efectos, y su aprobacion unica solo cubre las firmas exactas del plan, no concede un grant futuro.

**Bloqueo:** no construir una opción “aprobar todo una vez”. Para el primer P2 se mantiene confirmación por operación y no se habilitan grants reutilizables nuevos. Cualquier grant futuro requiere alcance acordado, opt-in visible y límite de sesión.

## Objetivo y criterio rector

Convertir MARK en un asistente de Windows con capacidades amplias, especificas por aplicacion, verificables y recuperables. No se debe prometer "control absoluto" ni automatizacion universal: cuando MARK no pueda identificar el objetivo, el efecto o el resultado con suficiente certeza, debe detenerse, explicar el limite y pedir intervencion.

No se recomienda una reescritura total. Se conserva el registro de acciones, los contratos de resultado, el planificador, el adaptador UIA y las integraciones que pasen sus pruebas. Se congelan nuevas capacidades que puedan enviar, borrar, sobrescribir, instalar, comprar o cambiar el sistema hasta cerrar las puertas P0/P1.

## Linea base confirmada

| Estado | Evidencia actual |
|---|---|
| Completado | Windows y Python 3.13.14 seleccionados como entorno principal; Python 3.11.9 y 3.12.10 instalados para probar la matriz. |
| Completado localmente; CI remota requiere corrección | En cada Python soportado, `python -m unittest discover -s tests -q`: 474 ejecutadas, 461 aprobadas y 13 omitidas. La ejecución remota inicial en GitHub Actions reprodujo dos fallos de rutas en Windows; los tests se corrigieron y pasan localmente en 3.11/3.12/3.13. Las omisiones locales son una prueba de symlink no disponible, dos dependencias documentales opcionales y diez UIA opt-in. |
| Completado | `python -m compileall -q .`, `python setup.py --dry-run` y `python -m pip check` pasan con Python 3.11, 3.12 y 3.13. |
| Completado | Playwright Python `1.64.1` y driver integrado `1.64.0-beta-1791568591000` comparten la línea `1.64`; Chromium headless `156.0.8078.4` abre y cierra en Python 3.11, 3.12 y 3.13. |
| Completado | El certificado HTTPS se genera en carpeta temporal, carga en `SSLContext` y la segunda generacion es idempotente. Una prueba local inicia el dashboard solo en loopback, valida TLS con un cliente HTTPX que confia explicitamente en ese certificado y recibe HTTP 200. No se modifico `config/certs` real ni se abrio el firewall. |
| Completado | `import win32com.client` funciona; no hace falta ejecutar el postinstall de pywin32 salvo que una funcion concreta de COM falle. |
| Pendiente | La matriz CI y la carga del artefacto de evidencia están configuradas y se ejecutaron en `valeriaorocollo-crypto/Mark-LVI-main`. El run 42947058149 probó las tres versiones; fallaron dos aserciones frágiles de rutas Windows. Los arreglos pasan en local y deben subirse para repetir el run. |
| Completado en LAN; confianza del certificado pendiente | Un cliente HTTPX verificó HTTPS/TLS 1.3 y un cliente sin confianza rechazó el certificado autofirmado. Desde el ASUS se alcanzó la pantalla de acceso remoto HTTPS sin ingresar una clave. Falta verificar/instalar la confianza del certificado autofirmado si se requiere uso normal desde ese dispositivo. |
| Pendiente | Repetir la CI remota tras subir las correcciones de comparación de rutas y verificar los tres jobs en verde. |

## Orden de ejecucion

### Etapa 0 - fijar entorno reproducible

**Riesgo si se omite:** un resultado de pruebas puede depender del Python equivocado, paquetes que cambian o navegadores distintos.

1. Usar Python 3.13 como intérprete principal y confirmar que MARK y la terminal apuntan a ese ejecutable. En esta máquina se verificó el proceso real de MARK bajo Python 3.13.14; para iniciarlo desde consola:
   ```powershell
   py -3.13 --version
   py -3.13 -m pip show playwright
   py -3.13 -c "import importlib.metadata as m; print(m.version('playwright'))"
   py -3.13 -m playwright install --list
   py -3.13 main.py
   ```
2. La matriz local confirma Playwright Python 1.64.1 y driver 1.64.0-beta en la misma línea 1.64; Chromium 156.0.8078.4 se inicia en los tres intérpretes. `pip check` no detectó dependencias rotas. Se intentó reinstalar la misma versión estable, pero la descarga de 38 MB avanzó a unos 5 KB/s; se canceló antes de alterar paquetes. No fue necesaria una reparación para el smoke test. El workflow verifica major/minor y Chromium.
3. La evidencia local sanitizada está en [evidence/stage0-windows-2026-11-10.json](./evidence/stage0-windows-2026-11-10.json). El workflow genera un directorio con versiones, dependencias, navegador y salida de unittest, y lo conserva como artefacto por 14 días. No incluye credenciales, mensajes ni capturas.
4. Se añadió y ejecutó en las tres versiones una prueba de cliente HTTPS local: genera certificado temporal, inicia el dashboard en loopback, confía solo en ese certificado y obtiene HTTP 200. No abre firewall. Desde el ASUS se alcanzó previamente el HTTPS, pero aún no se validó allí la identidad/confianza del certificado; no se generó clave de emparejamiento.

**Criterio de salida:** cumplido. La matriz CI del repositorio correcto pasó remotamente en Python 3.11, 3.12 y 3.13; los logs y artefactos identifican commit, versiones y resultados; Chromium funciona; y el dashboard HTTPS se verificó desde un cliente local que confía explícitamente en un certificado temporal. El extra opcional `openwakeword` falta en el arranque observado y no se considera validado, pero no es requisito de Etapa 0.

### Etapa 1 - cerrar la politica de efectos P0

**Archivos principales:** `core/tool_audit.py`, `core/action_policy.py`, `actions/computer_control.py`, `tests/test_tool_audit.py`, `tests/test_confirmed_actions.py`.

**Estado de esta revisión:** el contrato de efectos quedó implementado en `core/tool_audit.py`. Los efectos desconocidos no se ejecutan ni siquiera dentro de un plan aprobado; las acciones de teclado/ratón opacas y los controles genéricos sin destino verificable se bloquean antes del handler. Los controles semánticos UIA de escritura/invocación exigen confirmación para toda etiqueta y presentan destino y alcance; se añadieron gates en los registries de acciones/plugins y en los handlers de escritorio para proteger llamadas directas. La suite completa local pasa en Python 3.11.9, 3.12.10 y 3.13.14; falta que CI remota vuelva a validar este cambio.

1. Cambiar la clasificacion desde nombres/etiquetas a un contrato de efecto explicito por accion. Como minimo: solo lectura, navegacion, cambio local reversible, cambio local destructivo, comunicacion externa y operacion financiera/administrativa.
2. Tratar coordenadas opacas, `press`, `hotkey`, `paste`, `drag` y acciones genericas de ventana como efecto desconocido salvo que una herramienta especifica entregue objetivo y alcance verificables.
3. En caso de efecto desconocido, no ejecutar por defecto. La politica debe fallar cerrada o solicitar aprobacion que describa exactamente el objetivo y las consecuencias posibles.
4. Evitar que una etiqueta como "Comprar", "Borrar" o "Alquilar" sea el unico detector. El texto es evidencia auxiliar, no una prueba del efecto.
5. Recorrer todos los caminos de despacho: herramientas internas, acciones auto-descubiertas, plugins, planes compuestos y llamadas directas de handlers. No debe existir una ruta alternativa que salte el gate.
6. Agregar pruebas de regresion para `Delete`, `Shift+Delete`, combinaciones de teclas, click por coordenadas, click sin selector, destino desconocido, formularios, terminos en espanol/ingles y riesgo no clasificado. El test debe afirmar que el handler no se ejecuto antes de la aprobacion.

**Criterio de salida:** la matriz de casos peligrosos no tiene ningun efecto sin una autorizacion exacta; los casos no comprendidos se detienen; la suite focal y la suite general pasan.

### Etapa 2 - proteger operaciones de archivos P0/P1

**Archivos principales:** `actions/file_controller.py`, `core/undo.py`, pruebas de `file_controller`.

**Estado actual:** destinos existentes ya no se sobrescriben al copiar. `create_file` y `write_file` rechazan enlaces simbólicos, datos no UTF-8/NUL y snapshots existentes mayores de 1 MB; los reemplazos se escriben en temporal y se aplican atómicamente. Undo valida el contenido y la identidad del archivo antes de restaurar o borrar. Quedan por probar fallos de disco/permisos, volúmenes de red y la política de undo para copias de directorios.

**Estado actual:** se bloqueo la sobrescritura de copias; los writes hacen snapshot estricto de texto UTF-8 hasta 1 MB, reemplazo atomico y undo condicionado al contenido e identidad actual. Se rechazan binarios/NUL, enlaces simbolicos, snapshots ilegibles y reemplazos mayores al limite. La etapa sigue abierta hasta probar fallos/ACL, volumen de red, cancelacion, carpetas y compatibilidad real.

1. En copia, fallar si el destino existe. Si se agrega reemplazo deliberado, mostrar el destino y el contenido que podria perderse, guardar un respaldo restaurable y deshacer restaurando exactamente ese respaldo.
2. Distinguir archivo inexistente, texto leible, binario/no UTF-8, sin permisos y demasiado grande. No usar `None` para representar simultaneamente "no existia" y "no se pudo leer".
3. Rechazar reemplazos cuando no se pudo crear un respaldo recuperable. No seguir escribiendo y prometer un undo que podria borrar el archivo original.
4. Hacer las escrituras mediante temporal en el mismo volumen, flush/fsync cuando corresponda y reemplazo atomico. Limpiar temporales ante excepcion o cancelacion.
5. Definir que pasa con append, enlaces simbolicos, permisos ACL, archivos abiertos, nombres conflictivos y volumenes de red. Mantener el confinamiento por defecto al perfil de usuario; no habilitar todo el disco.
6. Probar igualdad byte a byte antes/despues, archivo destino preexistente, restauracion tras undo, interrupcion, archivo binario, archivo grande, lectura fallida y destino sin permisos.

**Criterio de salida:** nunca se pierde ni sobrescribe silenciosamente un archivo preexistente; undo restaura los bytes originales o informa que no hay undo antes de ejecutar.

### Etapa 3 - detener acciones ciegas de escritorio y mensajeria

**Archivos principales:** `actions/send_message.py`, `plugins/_whatsapp_core.py`, `actions/game_updater.py`, `actions/browser_control.py`.

**Estado actual:** `_desktop_send` y los flujos ciegos de navegador fueron retirados/deshabilitados; plataformas sin transporte verificado devuelven fallo antes del HUD y no escriben ni envian. WhatsApp sigue sujeto a validacion real; no declararlo completado por las pruebas simuladas.

1. Deshabilitar `_desktop_send` para servicios que no tengan adaptador con identidad de ventana, destinatario y resultado verificables. No basta con devolver `unverified` despues de pulsar Enter: el efecto externo ya podria haberse producido.
2. Hacer que `_open_browser_url` propague el resultado real de `webbrowser.open`; no escribir teclas ni continuar si el navegador no confirma apertura.
3. Mantener el envio WhatsApp desactivado o bloqueado mientras el flujo real no abra el chat correcto y no pueda releer el encabezado y el mensaje. Probar solo en cuenta de prueba y destinatario autorizado; no usar la cuenta principal para los primeros intentos.
4. Eliminar el fallback de Steam que hace click en una coordenada estimada cuando no reconoce el avatar. Los dialogs de instalacion deben seleccionar un control UIA unico o detenerse para que lo resuelva la persona.
5. Por cada app, separar "preparar" de "confirmar efecto": resolver destinatario/archivo/juego, presentar preview, aprobar, ejecutar una vez y verificar. Si el resultado queda ambiguo, no reintentar el efecto automaticamente.
6. Añadir tests mockeados para foco incorrecto, navegador no abierto, selector multiple, ventana que cambia, destinatario que no coincide y resultado ambiguo. Dejar las pruebas reales opt-in y descritas por version de app.

**Criterio de salida:** ninguna mensajeria se envia por una secuencia generica de teclas; ninguna seleccion ambigua usa coordenadas de reserva; las incertidumbres bloquean reintentos.

### Etapa 4 - eliminar privilegios y cambios globales implicitos

**Archivos principales:** `dashboard/server.py`, `main.py`, `actions/computer_settings.py`, pruebas del dashboard.

1. Quitar el monkey patch global de `subprocess.Popen` en `main.py`. Pasar `CREATE_NO_WINDOW` solo en las llamadas que lo necesitan y preservar `startupinfo`/flags entregados por el llamador.
2. Separar "iniciar dashboard" de "configurar firewall". El inicio no debe pedir elevacion ni mutar perfiles de red.
3. No borrar reglas de bloqueo existentes ni cambiar redes publicas a privadas automaticamente. Si el usuario decide publicar en LAN, mostrar una vista previa del puerto, ejecutable, perfil y regla; ofrecer instrucciones/manual u opt-in puntual.
4. Mantener acceso remoto apagado por defecto. Documentar el certificado autofirmado y asegurar que la vinculacion del dispositivo valida la identidad esperada, tiene expiracion, revocacion y limitacion de intentos.
5. Revisar la creacion de directorios y archivos que ocurre al importar `dashboard.server`; importar un modulo no deberia tener efectos persistentes evitables.
6. Probar arranque local sin UAC, cancelacion, reglas preexistentes y certificado invalido; validar HTTPS desde un cliente local y no abrir firewall en estas pruebas.

**Criterio de salida:** importar o iniciar MARK no cambia firewall, perfil de red ni comportamiento de procesos ajenos; control remoto solo se activa por decision explicita.

### Etapa 5 - plugins, tests y calidad continua

**Archivos principales:** `core/plugin_loader.py`, `core/action_loader.py`, manifiestos de requisitos, `tests/`, nueva configuracion CI.

1. Definir la frontera de confianza: plugin local instalado por el usuario es codigo ejecutable, no un archivo de datos. No prometer sandbox por mostrar confirmacion.
2. Para codigo de terceros, planificar proceso aislado con protocolo IPC, permisos por capacidad, limite de tiempo, cancelacion y limite de memoria. Mientras no exista aislamiento, cargar solo plugins confiables y desactivarlos por defecto cuando no se hayan revisado.
3. Separar pruebas puras de las que requieren UI, audio, browser o cuenta. Los tests puros deben poder correr con adaptadores simulados y no depender de PyAutoGUI, PyQt, dispositivos o ventanas reales.
4. Crear CI Windows para Python 3.11, 3.12 y 3.13. Ejecutar unittest, `compileall`, setup dry-run y linter; hacer visible cualquier suite opt-in omitida. No elevar porcentajes del roadmap por tests sinteticos solamente.
5. Elegir Ruff para errores de estilo/imports y Pyright/Pylance o equivalente para tipos; fijar reglas iniciales sin intentar corregir todos los avisos automaticamente en un cambio masivo.
6. Añadir limites reproducibles para dependencias directas y revisar el warning de compatibilidad `Starlette TestClient`/`httpx`. Guardar lockfile o manifiesto de resolucion de release; comprobar avisos y licencias en CI.
7. Crear una prueba limpia que instale en un entorno temporal, importe cada modulo soportado y arranque MARK sin secretos, cuentas ni instalaciones implicitas.

**Criterio de salida:** una maquina limpia reproduce las pruebas; los fallos de dependencias no se confunden con bugs y la compatibilidad publicada coincide con CI.

### Etapa 6 - integrar por aplicacion, no por promesa universal

No iniciar esta etapa hasta cerrar las etapas 1-5. Un conector se considera piloto hasta aportar pruebas propias.

Para cada aplicacion completar la misma ficha:

1. Capacidad exacta incluida y excluida.
2. Interfaz preferida: API oficial, protocolo de aplicacion, UIA/DOM; vision solo como ultimo recurso.
3. Permisos/scopes minimos, consentimientos y procedimiento de revocacion.
4. Version de app, Windows, idioma, escala/resolucion, tipo de cuenta y estado de sesion probados.
5. Preview y confirmacion para escribir, enviar, publicar, instalar, borrar, comprar o cambiar configuracion.
6. Evidencia posterior de solo lectura y estados `done`, `unverified`, `failed`, `ask`.
7. Tests de timeout, expiracion, ambiguedad, duplicado, cancelacion y no repeticion.
8. Cumplimiento de las condiciones del proveedor; no eludir MFA, CAPTCHA, DRM ni controles de acceso.

Orden sugerido por alcance y riesgo:

| Orden | Integracion | Primer alcance recomendado |
|---:|---|---|
| 1 | Spotify | Completar matriz por version/idioma y verificar playback API/UI. Solo controles de musica; no compras/cuenta. |
| 2 | Calendario Google | Lectura primero, luego crear evento con preview, zona horaria explicita, deduplicacion e idempotencia. |
| 3 | Outlook | Microsoft Graph con scopes minimos; lectura antes de crear/contestar/enviar. No empezar con automatizacion de ventana. |
| 4 | Navegador | Sitios/patrones concretos con perfiles separados, permiso para formularios y dominios explicitamente soportados. |
| 5 | Git y VS Code/Visual Studio | API/CLI con directorio de trabajo elegido, diff visible y tests; nunca ejecutar comandos sugeridos por contenido web sin revision. Separar Visual Studio de VS Code. |
| 6 | WinRAR/archivos comprimidos | Usar operacion de archivo acotada y preview de entradas/salidas; traversal, sobrescritura y archivos comprimidos requieren limites. No automatizar UI si hay CLI estable. |
| 7 | WhatsApp | Solo via interfaz oficial permitida para el tipo de uso. No automatizar Web de manera no soportada; envio UI bloqueado hasta demostrar destinatario y resultado en pruebas reales. |
| 8 | Steam | Lectura de biblioteca/estado primero. Instalacion requiere preview de titulo, cuenta, disco y espacio. No automatizar compras ni usar clicks heurísticos. |
| 9 | Ajustes y herramientas administrativas Windows | Comandos/acciones muy concretos, permisos minimos y aprobacion independiente. Device Manager, firewall, servicios y archivos de sistema no se habilitan como una consola root abierta. |
| 10 | Noticias y multimedia | Fuentes identificables, ubicacion elegida/confirmada, fecha y enlace por noticia; verificar estado de reproduccion, no solo apertura de URL. |

**Criterio de salida por integracion:** no se marca completa porque el comando funcione una vez. Se requiere matriz acotada, pruebas de errores y evidencia en la version declarada.

### Etapa 7 - medir y optimizar rendimiento

**Archivos principales:** `providers/engine_pipeline.py`, `main.py`, `core/gemini.py`, `actions/browser_control.py`, `actions/send_message.py`.

1. Medir un recorrido de voz con marcas monotonic: fin de voz, STT, inicio/primer token LLM, llamadas de herramienta, verificacion, primer audio TTS y fin total.
2. Guardar agregados opt-in sin audio, texto, rutas, destinatarios ni capturas. Reportar P50/P95 por motor, hardware y tipo de tarea.
3. Separar latencia de red/proveedor de la latencia local; registrar intentos de fallback y reintentos, sin exponer claves ni cuerpo de mensajes.
4. Reemplazar `sleep` fijos en GUI por polling de una condicion concreta con timeout, cancelacion y pausa de seguridad. No paralelizar acciones que manipulan foco.
5. Reducir contexto/tokens y llamadas de modelo solo donde una medicion demuestre que son el cuello de botella. No cambiar el proveedor/modelo de forma que altere la verificacion sin tests de equivalencia.
6. Comparar baseline y cambio en la misma computadora y tarea; mantener una tabla de P50/P95 y tasa de `unverified`.

**Criterio de salida:** cada optimizacion tiene antes/despues medido, no aumenta efectos incorrectos y documenta el tradeoff de calidad/latencia.

### Etapa 8 - modularizar y podar deuda

Esta etapa va despues de tener regresiones de seguridad y un ciclo CI estable.

1. Extraer de `ui.py` componentes independientes (settings, dashboard, plugins, actividad) sin cambiar conducta publica.
2. Dividir `main.py` en ciclo de sesion, entrada/salida de audio y orquestacion de acciones; retirar el patch global de `Popen` antes de mover imports.
3. Separar en `computer_control.py` UIA, procesos, captura y entrada global; las herramientas de bajo nivel no deben decidir por si solas permisos.
4. Dividir `file_processor.py` por formato/transformacion, conservando limites comunes y comportamiento de lectura.
5. Dividir dashboard por transporte, TLS/emparejamiento y control remoto; firewall es una capacidad separada y opt-in.
6. Unificar nomenclatura MARK/JARVIS/MARK LIV, retirar comentarios y aliases obsoletos solo despues de buscar referencias y probar compatibilidad.
7. Cada extraccion debe ser pequeña, mantener el contrato anterior y pasar tests focales y suite completa. No hacer una reescritura general ni cambios de formato globales.

**Criterio de salida:** cada modulo tiene una responsabilidad clara, imports sin efectos laterales evitables y pruebas que permiten cambiarlo sin tocar el resto de la aplicacion.

## Puertas de release

No habilitar uso desatendido de una capacidad sensible hasta que todas las respuestas sean “si”:

- ¿La accion tiene un efecto y alcance definidos?
- ¿Se mostro una vista previa legible del objetivo y de los datos que saldran?
- ¿La aprobacion se vincula exactamente a esos argumentos y expira al cambiar algo?
- ¿Hay una interfaz oficial/semantica y no una secuencia de teclas ciega?
- ¿El resultado se verifica sin confiar en el texto del modelo?
- ¿Un timeout o cancelacion impide repetir el efecto?
- ¿Se conserva un registro minimo y se pueden revocar permisos/credenciales?
- ¿Las pruebas de esa aplicacion/version pasan y la compatibilidad esta documentada?

Si una respuesta es “no” o “no medido”, el resultado es piloto, asistido por humano o bloqueado, no completado.

## Reglas para mantener el arbol sano

- Un cambio = un riesgo o capacidad concreta; no mezclar refactor, optimizacion y nuevo conector en el mismo cambio.
- Toda correccion de P0/P1 empieza con un test que reproduzca el defecto.
- No borrar/reescribir partes grandes antes de preservar comportamiento con pruebas.
- No usar porcentajes de fases para sugerir madurez; publicar capacidades y evidencia por app.
- No habilitar administrador/root permanente. Elevar solo una accion puntual, con alcance visible y aprobacion.
- Si no hay API o UIA confiable, detenerse; esa limitacion es comportamiento correcto, no un bug que se deba tapar con mas clicks.
