# MARK — hoja de ruta de control universal verificable

## Cómo leer esta hoja

Esta hoja conserva los **52 hitos originales**. La organización por fases se
limpió para que cada hito tenga una única ubicación y un estado inequívoco.

- **[x] Completado:** implementado y validado dentro del alcance indicado.
- **[~] Parcial:** existe una base funcional, pero faltan casos o cobertura.
- **[ ] Pendiente:** todavía no implementado.
- **[N/A] Fuera de alcance:** no se implementará en esta etapa.

El objetivo de diseño es que MARK atienda solicitudes variadas —correo, hojas
de cálculo, navegador, reproductores y aplicaciones de escritorio— priorizando
API oficial, DOM/Playwright, UI Automation y visión en ese orden. Esa selección
no está implementada como una integración universal. “Universal” no significa
que toda aplicación sea automatizable: cuando no haya una interfaz fiable,
MARK debe explicarlo y detenerse.

## Estado general — revisión de implementación Windows

El porcentaje por fase se calcula como **hitos `[x]` / hitos totales × 100**.
Un hito parcial `[~]` no cuenta como completado. El porcentaje mide estos
hitos y su alcance documentado; no equivale a compatibilidad con cualquier
aplicación ni a una garantía de que toda acción tenga éxito.

| Fase | Hitos | Estado | Avance orientativo |
|---|---:|---|---:|
| 1. Seguridad y contratos | 1–14 | 14 hitos completados dentro del alcance documentado | 14/14 = **100%** |
| 2. Instalación y diagnóstico Windows | 15–20 | 6 hitos completados dentro del alcance documentado | 6/6 = **100%** |
| 3. Control Windows y automatización segura | 21–30 | 10 hitos completados con pruebas sintéticas/locales | 10/10 = **100%** |
| 4. Tareas compuestas generales | 31–40 | 10 hitos completados; incluye vista previa estructurada de formularios | 10/10 = **100%** |
| 5. Integraciones por aplicación | 41–46 | Pilotos parciales; ningún hito cumple todavía sus criterios completos | 0/6 = **0%** |
| 6. Planificación y recuperación avanzada | 47–49 | Pausa manual completada; recuperación e idempotencia parciales | 1/3 = **33%** |
| 7. Calidad, privacidad y compatibilidad | 50–52 | Parcial; falta cobertura operativa y compatibilidad documentada | 0/3 = **0%** |

**Este porcentaje no es un porcentaje de cierre P0/P1.** Corte local vigente:
`python -m unittest discover -s tests -q` pasó **464 pruebas con 13 omitidas**;
compileall, `setup.py --dry-run` y `pip check` también pasaron en Python
3.13.14. Los resultados remotos de CI y la validación real de WhatsApp, Steam
y dashboard siguen pendientes. Por eso no se declara P0/P1 al 100%.

### Puerta P0/P1 vigente

- **Corregido en código y cubierto localmente:** despacho de efectos opacos en
  las rutas revisadas, regresiones de copia/escritura/undo, mensajería genérica
  ciega, selección heurística de Steam, mutación automática del firewall y
  parche global de `subprocess.Popen`.
- **Mitigado, no certificado:** plugins sin confianza explícita no se importan;
  la confianza se ata al hash de un archivo de hasta 2 MiB y la ejecución
  requiere habilitación separada. No hay sandbox para código confiado.
- **Pendiente de validación externa:** WhatsApp con cuenta de prueba, flujo
  manual de Steam, HTTPS del dashboard desde cliente local, matriz CI 3.11–3.13
  y pruebas de archivos con ACL/fallos de disco/volúmenes de red.

## Contratos de seguridad y alcance real

- En las rutas normalizadas, `done` requiere el campo literal
  `verified=true`; los planes compuestos también exigen evidencia observada de
  una acción permitida como lectura. El verificador descarta metadatos de
  resultado (`status`, `action`, `verified`, etc.) para que no puedan satisfacer
  por sí solos la coincidencia esperada.
- Los contratos instruyen al modelo a no convertir `unverified`, `failed`,
  `ask` o `started` en éxito.
- Las acciones desconocidas se clasifican como `unclassified` y se rechazan.
  Las acciones de alto impacto pasan por el HUD central o por un gate revisado
  del handler. Los plugins no confiados no se importan; después de confiar el
  hash y habilitarlo, siguen tratándose como externos en el despacho.
- La confirmación se origina en la interfaz, no en un argumento del modelo.
- La navegación e interacción rutinaria de pantalla no abre un HUD por cada
  clic o tecla. La política reserva la confirmación para acciones de alto
  impacto y objetivos sensibles/destructivos identificables; una coordenada
  opaca no permite inferir el contenido del control.
- Los controles UIA exigen selección única, protegen `CurrentIsPassword` y
  verifican foco/efectos cuando aplica. Los fallos estructurales se reportan
  como error; los fallos de lectura de estado se etiquetan explícitamente y no
  se interpretan como `false`.
- La auditoría `core.tool_audit` no conserva argumentos ni resultado. Esto no
  certifica que ningún otro logger de toda la aplicación pueda registrar datos.
- Las credenciales Gemini, las claves `api_key` de proveedores y los campos
  sensibles de plugins (`password`, `passwd`, `secret`, `token`, `credential`,
  `api_key`, `authorization`, `private_key` y `otp`) se guardan en el almacén
  seguro del sistema; en Windows se requiere `WinVaultKeyring`. Las copias
  heredadas se migran y se eliminan del JSON. Si falla la escritura de limpieza,
  se intenta revertir la nueva credencial y se informa del fallo; una copia
  heredada puede seguir en el archivo hasta que la limpieza se complete.
- Las preferencias y demás campos no sensibles continúan en
  `config/api_keys.json`. La seguridad del almacén no protege frente a malware
  ejecutado con la sesión del usuario, código de plugins que el usuario haya
  confiado (se ejecuta en proceso, sin sandbox) ni copias de seguridad antiguas
  que ya contengan secretos.
- El proyecto establece no eludir MFA, CAPTCHA, DRM o políticas del proveedor;
  no existe una garantía técnica universal que detecte o bloquee esos casos.
- Las integraciones UIA opt-in usan ventanas sintéticas locales; no prueban
  compatibilidad general con Outlook, Excel, TikTok u otras apps reales.

---

## Fase 1 — Seguridad, contratos y pruebas

**Estado: 14/14 hitos de checklist implementados dentro de sus límites
sintéticos/locales; esto no cierra por sí solo todos los P0/P1.** Las
validaciones externas y los bloqueos descritos en la puerta P0/P1 permanecen.

### 1. Inventario de superficies

- [x] **1.** Revisar acciones, plugins, dependencias, dashboard, red,
  navegador, archivos, escritorio, memoria y servicios externos. Las pruebas
  enumeran las acciones declaradas y detectan acciones sin clasificación; el
  inventario de riesgos externos se mantiene como revisión de código.

### 2. Clasificación de riesgo

- [x] **2.** Clasificar explícitamente las acciones declaradas. Las acciones
  desconocidas de `browser_control` y `file_processor` quedan sin clasificar y
  la política las rechaza; una prueba recorre los enums declarados.

### 3. Confirmación humana

- [x] **3.** Centralizar la confirmación HUD y hacer que ausencia de HUD,
  cancelación, expiración o error no ejecuten la acción.

### 4. Política única

- [x] **4.** Aplicar `action_policy.dispatch` a acciones y plugins, rechazar
  riesgos no clasificados y mantener gates de handler explícitos donde se
  necesita una confirmación más específica.

### 5. Contrato de resultados

- [x] **5.** Normalizar resultados en `core/outcome.py` con estados `done`,
  `unverified`, `failed`, `started` y `ask`.

### 6. Éxito verificable

- [x] **6.** Exigir `verified=true` para aceptar `done`. En planes, cada paso
  requiere además una acción de verificación explícitamente de solo lectura y
  evidencia esperada coincidente. La verificación depende de las capacidades
  observables de la aplicación.

### 7. Validación de entradas

- [x] **7.** Combinar límites globales de tamaño/profundidad y compatibilidad
  JSON de argumentos en el despacho de herramientas integradas, acciones y
  plugins, con validaciones específicas por acción (URLs, texto, teclas,
  coordenadas, esperas, scroll, rutas, nombres y títulos). Las herramientas
  internas también rechazan valores semánticamente inválidos o fuera de sus
  límites.

### 8. Protección de archivos

- [x] **8.** Exigir confirmación para borrar, crear, reemplazar, escribir,
  mover, organizar y copiar archivos, incluyendo posibles sobrescrituras.

### 9. Protección de acciones externas

- [x] **9.** Proteger operaciones sensibles revisadas —mensajes, archivos,
  Meet, cambios del sistema, cierres, reinicios, apagado y Wi-Fi— con el HUD;
  los plugins descubiertos reciben riesgo externo por defecto.

### 10. Auditoría privada

- [x] **10.** Mantener auditoría acotada a metadatos: herramienta, estado,
  riesgo, efecto y duración, sin argumentos, mensajes, rutas ni secretos.

### 11. Errores seguros

- [x] **11.** El despacho de herramientas, los registros de acciones/plugins,
  la confirmación y el error exterior de `file_processor` no devuelven ni
  registran mensajes de excepción o tracebacks; exponen el tipo cuando es útil.
  Los plugins de terceros pueden mantener sus propios logs, y los diagnósticos
  auxiliares de plataforma/red no están cubiertos por esta garantía. Los
  errores al guardar credenciales se muestran sin incluir sus valores.

### 12. Límites contra abuso

- [x] **12.** Aplicar límites globales a argumentos y límites específicos a
  las superficies: presupuesto del navegador, clics visuales y dashboard.
  No se impone un rate limit temporal único a todas las acciones locales.

### 13. Cancelación y fallos

- [x] **13.** Cancelar planes entre pasos, reportar `unverified` si se cancela
  durante una acción activa y cerrar el estado ante excepciones. No se fuerza
  la terminación de una llamada UI/API en curso ni se deshacen efectos parciales.

### 14. Regresión de seguridad

- [x] **14.** Probar clasificación de enums declarados, gates HUD, validación,
  despacho de herramientas internas, auditoría, privacidad, resultados,
  errores y flujos sintéticos de acciones protegidas. No equivale a una prueba
  operativa de cada aplicación real.

**Salida:** las acciones declaradas tienen riesgo explícito o se rechazan; el
HUD exige aprobación y el sistema no convierte errores o efectos inciertos en
éxito.

---

## Fase 2 — Instalación, configuración y diagnóstico Windows

**Estado: 6/6 hitos completados para la instalación y diagnóstico local Windows.**

### 15. Diagnóstico de entorno

- [x] **15.** Diagnosticar Python, dependencias, audio, permisos consultables
  de proyecto/configuración/temp, UI Automation, Playwright, caché local de
  navegadores, almacén seguro y herramientas nativas. No hace pruebas remotas.

### 16. Dependencias por capacidad

- [x] **16.** Separar dependencias base y opcionales y documentar qué capacidad
  activa cada grupo.

### 17. Plan de instalación

- [x] **17.** `setup.py --plan` enumera las especificaciones exactas de paquetes
  base/opcionales y los efectos externos; `--dry-run` verifica manifiestos y
  asset sin instalar, descargar ni conectar. No calcula el diff contra paquetes
  ya instalados.

### 18. Instalación explícita

- [x] **18.** Evitar descargas implícitas de navegadores y pedir confirmación
  antes de instalar grupos opcionales. Los motores opcionales tampoco actualizan
  paquetes silenciosamente al detectar incompatibilidades; muestran el comando
  de reparación para que la instalación sea explícita.

### 19. Credenciales locales

- [x] **19.** Guardar y borrar la clave mediante `keyring`; en Windows exigir
  `WinVaultKeyring`; esto cubre la clave Gemini, claves `api_key` de proveedores
  y campos sensibles declarados por plugins. La migración elimina las copias
  heredadas del JSON, usa escritura atómica e intenta revertir las credenciales
  nuevas si no puede completar la limpieza; también informa si el rollback
  falla. Las pruebas usan backend simulado; no
  certifican por sí solas el almacén nativo de cada equipo Windows.

### 20. Copia limpia Windows

- [x] **20.** Probar los inputs mínimos de instalación en una copia temporal
  aislada, sin `config/api_keys.json`, entornos virtuales ni cachés; el dry-run
  valida los manifiestos y el asset sin instalar ni conectarse. No certifica
  el inicio completo de la aplicación desde un clon nuevo.

**Fuera de alcance:** soporte equivalente de instalación y credenciales para
macOS/Linux; el porcentaje de esta fase solo mide el flujo local Windows.

---

## Fase 3 — Control Windows y automatización segura

**Estado: 10/10 hitos completados con pruebas de adapter y escenarios sintéticos Windows.**

### 21. Adaptador de accesibilidad

- [x] **21.** Crear `core/ui_adapter.py` con capacidades declaradas y detección
  local del backend `pywinauto`; cada operación vuelve a manejar y exponer sus
  propios errores UIA.

### 22. Inspección limitada

- [x] **22.** Enumerar ventanas visibles con límites de 50 ventanas, 100
  descendientes y textos acotados. Los fallos estructurales se informan como
  error; fallos por propiedad se anotan por control y sus valores quedan
  desconocidos, no se convierten en `false`.

### 23. Protección de controles sensibles

- [x] **23.** `read_control`, `write_control`, foco e invocación bloquean
  controles sensibles según nombre/tipo y `CurrentIsPassword`; el inspector
  identifica el control y omite su texto. Las pruebas cubren la propiedad UIA
  en un control Edit sintético.

### 24. Selectores exactos

- [x] **24.** Buscar por ventana, nombre, tipo y opcionalmente automation ID,
  rechazando cero coincidencias o coincidencias múltiples.

### 25. Foco y activación

- [x] **25.** Implementar `focus_control` y `activate_window` con validación,
  comprobación de foreground y verificación real de foco. La navegación normal
  no requiere confirmación repetida; las acciones sensibles siguen protegidas.
  `screen_click` confirma solo que la pantalla cambió: el destino final debe
  inspeccionarse por separado antes de declararlo alcanzado. El fallback
  Windows de `open_app` abre Windows Search, exige una única ventana UIA con
  foco y el `SearchTextBox` exacto, y lee el texto antes de enviarlo; no escribe
  en el control Edit de la aplicación que estuviera activa.

### 26. Escritura segura

- [x] **26.** Implementar `write_control` para `Edit`/`Document`, con límite
  de 10.000 caracteres y lectura UIA posterior exacta; se probó también una
  entrada sintética superior a 500 caracteres.

### 27. Invocación semántica

- [x] **27.** Implementar `invoke_control` mediante patrones UIA semánticos,
  sin coordenadas ni repetición automática.

### 28. Transición observable

- [x] **28.** Exigir cambio observable posterior a una invocación y detenerse si
  la ventana pierde el foco o el objetivo desaparece.

### 29. Navegador aislado

- [x] **29.** Endurecer Playwright y visión con perfiles aislados, selectores
  únicos, relocalización, presupuestos y evidencia posterior.

### 30. Integración UIA sintética

- [x] **30.** Validar foco, activación, desaparición de ventana e invocación con
  `MessageBoxW`; esas pruebas se complementan con el flujo editable WinForms
  del hito 40. La suite opt-in de esta revisión pasó 10 pruebas.

**Fuera de alcance:** adaptadores equivalentes para macOS/Linux y certificación
de compatibilidad con aplicaciones Windows reales. La fase cubre primitives y
pruebas sintéticas/locales.

---

## Fase 4 — Tareas compuestas generales

**Estado: 10/10 hitos completados dentro del alcance verificable Windows.**

### 31. Descubrimiento reutilizable

- [x] **31.** Exponer `inspect_windows`, `inspect_controls` y `read_control`
  como primitives de solo lectura para aplicaciones variadas.

### 32. Plan visible

- [x] **32.** Crear `core/task_plan.py` y `actions/task_planner.py` con planes
  de hasta 12 pasos y una previsualización antes de ejecutar.

### 33. Validación del plan

- [x] **33.** Validar herramientas permitidas, argumentos, riesgo, límites y
  verificaciones antes de generar un `task_id`.

### 34. Aprobación exacta

- [x] **34.** Autorizar solo la firma exacta de cada herramienta y argumento
  aprobado, incluyendo handlers UIA anidados.

### 35. Ejecución secuencial

- [x] **35.** Ejecutar pasos en orden, sin anidamiento del planificador ni
  reintentos automáticos, enrutando acciones integradas y plugins descubiertos
  al registro correspondiente. Los plugins deben estar confiados y habilitados,
  mantienen clasificación externa y solo se ejecutan con la aprobación exacta
  del plan; se detiene ante cualquier resultado no verificado.

### 36. Estado y duplicados

- [x] **36.** Implementar estados `pending`, `running`, `completed`, `failed` y
  `cancelled`, además de bloquear la ejecución paralela del mismo `task_id`.

### 37. Cancelación visible

- [x] **37.** Mostrar progreso y botón `CANCEL TASK`; cancelar detiene la
  continuación del plan. Una llamada activa no se termina a la fuerza ni se
  deshace; el resultado queda `unverified` si no puede verificarse.

### 38. Verificación por paso

- [x] **38.** Exigir `tool`, `arguments` y `expect` en cada verificación; usar
  una lista explícita de acciones de lectura y rechazar navegación/efectos.
  El verificador debe devolver `done` con `verified=true` y contener la
  evidencia esperada en valores observados, no en metadatos del contrato ni
  argumentos repetidos (`query`, límites o conteos).
  Los resultados web/documentales conservan el wrapper de contenido no
  confiable; las acciones de lectura sin un resultado estructurado verificable
  no se admiten como verificadores.

### 39. Formularios y envíos

- [x] **39.** Mostrar una vista previa estructurada de campos y valores antes
  de ejecutar el plan. La confirmación HUD expone el plan aprobado; valores de
  credenciales se ocultan y los campos password/OTP se rechazan. Enviar,
  publicar, guardar, comprar o compartir requiere aprobación antes de ejecutar.

### 40. Prueba editable completa

- [x] **40.** Crear una ventana WinForms sintética con campo `Edit` y botón y
  descubrir el campo mediante `computer_control.inspect_controls`, escribir
  texto sintético y verificarlo leyendo UIA mediante un plan. La prueba usa el
  `ActionRegistry` real para ejecutar el paso y un contexto de aprobación de
  plan simulado; la aprobación HUD se cubre en pruebas separadas.

**Salida:** el plan es acotado, visible, aprobado antes de ejecutar y se detiene
ante fallo o falta de evidencia. La vista previa no implica compatibilidad
universal ni sustituye las integraciones específicas de las Fases 5–7.

---

## Fase 5 — Integraciones por aplicación

**Estado: pilotos parciales; ningún hito cumple todavía todos sus criterios.**

### 41. Correo

- [~] **41.** Añadir `gmail_control` como piloto mediante Gmail API oficial:
  solicita solo el scope `gmail.readonly`, ofrece autorización local desde
  Settings y guarda credenciales OAuth en el almacén seguro. La búsqueda limita
  consulta a 500 caracteres, hasta 10 resultados y obtiene únicamente headers
  From/Subject/Date, fecha interna y snippet de hasta 500 caracteres, ordenados
  por fecha interna; el contenido recibido se marca como no confiable. No
  contiene acciones de envío, borrado o modificación. Para probarlo, habilita
  Gmail API en Google Cloud, crea un cliente OAuth de tipo Desktop, configura
  client ID/secret en Settings → Plugins y pulsa **AUTHORIZE GMAIL READ ONLY**;
  el navegador solo se abre por esa acción explícita. Pruebas simuladas cubren
  scope, límites, metadatos, marcador no confiable y descubrimiento. **Parcial:**
  falta consentir una cuenta de prueba y validar revocación, expiración, errores
  de red y comportamiento real; no activar en producción por esta evidencia
  local.

### 42. Hojas de cálculo y documentos

- [~] **42.** Piloto local de solo lectura conectado a `file_processor`:
  búsqueda y vista previa acotadas para DOCX, TXT/MD/RST/LOG, CSV/TSV y XLSX.
  No escribe archivos ni usa Gemini; limita entrada comprimida a 20 MiB,
  contenedores DOCX/XLSX a 64 MiB expandidos y 10.000 entradas, lectura a
  100 filas, 40 columnas y 10 hojas, resultados de búsqueda a 20 coincidencias
  y salida a 12.000 caracteres. El CSV detecta el ancho incrementalmente,
  conserva un campo extra para informar columnas omitidas y rechaza filas con
  más de 41 campos antes de construirlas. Trata el contenido leído como no
  confiable.
  Hay pruebas sintéticas de lectura, búsqueda (incluidas coincidencias después
  de la vista previa de una celda y resultados incompletos por límites), varias
  hojas XLSX, tablas DOCX, rechazo de extensiones no admitidas y contenedores
  grandes, filas CSV extremadamente anchas rechazadas antes del parser,
  delimitadores dentro de comillas, columnas fuera del límite, topes efectivos
  de resultados y salida, lectura CSV sin depender de pandas y ausencia de
  llamadas al modelo/escrituras. **Parcial:** no automatiza Excel ni otras
  aplicaciones, no valida `.xls`/`.ods`, fórmulas, compatibilidad real ni
  fallos en entornos de usuario; no habilita acciones externas.

### 43. Navegación web

- [~] **43.** Ya existen `web_search` y control genérico de navegador con
  perfiles de automatización separados; las lecturas `get_text`/`get_url`
  producen resultados estructurados y mantienen el contenido web no confiable.
  Las noticias ahora limitan DDG primero a 24 horas y luego a 7 días, exigen
  una fecha de publicación interpretable, ordenan y deduplican por fecha,
  ajustan la búsqueda a la ubicación/alcance solicitado y distinguen la falta
  de verificación de la ausencia de noticias. Las pruebas simuladas cubren
  titulares antiguos, fechas ausentes, orden, deduplicación, formato y el
  envoltorio único de resultados. La búsqueda de noticias ya no cae a una
  búsqueda web genérica cuando DDG News falla o devuelve cero resultados; así
  evita filtrar páginas que no son noticias y tareas de red que quedan vivas
  tras vencer un timeout externo.
  **Parcial:** no hay allowlist de dominios y el perfil de automatización es
  persistente. Se comprobó DDG News con consultas reales para Tacna/Perú, pero
  la muestra devolvió pocos resultados y mezcló noticias nacionales al pedir
  una localidad; el filtro de fechas evita titulares fechados fuera de ventana,
  pero no demuestra relevancia geográfica ni exactitud de fechas en todas las
  fuentes. La protección de prompt injection es un límite de datos, no una
  garantía de obediencia del modelo.

### 44. Vídeo y redes

- [~] **44.** `youtube_video` puede buscar/abrir videos de YouTube; la apertura
  ahora informa `unverified` y no afirma que la reproducción empezó.
  **Parcial:** depende de scraping no oficial, TikTok no está integrado y no
  hay lectura posterior del estado real de reproducción.

### 45. Música

- [~] **45.** Spotify conserva la ruta oficial Web API con OAuth PKCE para
  cuentas compatibles. En Windows, si no hay credenciales de API o Spotify
  deniega el control por Premium, el plugin usa UI Automation de la app
  instalada: abre una búsqueda, limita la selección a una fila de canción con
  título/artista exactos (no videos), invoca el botón semántico de esa fila y
  verifica el título, artista y estado de reproducción del reproductor actual.
  Los controles pausa/anterior/siguiente también se limitan a la barra del
  reproductor. No usa coordenadas ni teclas multimedia globales; las filas
  repetidas con el mismo título/artista se consolidan y coincidencias distintas
  siguen requiriendo aclaración. Se corrigió una carrera de carga: una búsqueda
  nueva ya no se confunde con los resultados accesibles de la consulta anterior.
  Se probó en Spotify Free real la búsqueda y reproducción de “COQUETA” de
  Fuerza Regida y Grupo Frontera; UIA confirmó la pista y el estado de
  reproducción.
  **Parcial:** esa comprobación valida el estado mostrado por Spotify, no la
  salida audible de los altavoces ni otras versiones/idiomas de la aplicación.
  Si no se exponen los controles UIA esperados, el plugin falla sin escoger un
  resultado a ciegas. La ruta API sigue requiriendo una app Spotify Developer,
  redirect URI loopback, autorización y compatibilidad Premium.

### 46. Calendario, Meet y mensajería

- [~] **46.** `meet_control` solo abre la página de nueva reunión tras HUD y
  devuelve `unverified`; `send_message` dispone de confirmación, con resultados
  diferentes según plataforma. **Parcial:** no hay conector Calendar, lectura
  de Meet ni verificación uniforme de invitaciones/envíos. Gmail está cubierto
  solo por un piloto separado, limitado a lectura. Las rutas de envío por UI no
  deben confundirse con integración oficial verificable.
- WhatsApp ahora muestra destinatario y texto completos y acepta confirmación
  por voz con una frase afirmativa explícita; correcciones de destinatario o
  mensaje actualizan la vista previa y requieren una nueva confirmación. Las
  respuestas de confirmación se consumen antes de despachar herramientas.
  `plugins/_whatsapp_core.py` enumera ventanas Win32 visibles, envuelve sus HWND
  con UIA y distingue la ventana web accesible `(2) WhatsApp` de la ventana
  nativa; si `set_focus()` no activa la ventana, verifica el resultado de
  `SetForegroundWindow`. El flujo valida y abre primero una coincidencia única,
  y solo después muestra la confirmación; una corrección de destinatario por
  voz también debe resolver una coincidencia antes de habilitar una nueva
  aprobación. Tras aprobar, vuelve a verificar encabezado, compositor y lectura
  posterior del mensaje. Los resultados UIA `DataItem` anidados se reducen a la
  fila directa del `DataGrid`; para resultados de la vista Raw se comprueba que
  el nombre empiece en un límite de palabra y que la fila esté dentro de la
  lista visible. La escritura usa teclado enfocado con lectura de vuelta,
  incluida entrada Unicode, y no usa el portapapeles. **La validación real sigue
  incompleta:** se verificaron el enfoque de la ventana, el campo de búsqueda,
  la entrada Unicode y una única fila candidata para `Yampier`. Esa fila no
  expone `SelectionItem` ni `Invoke`; los intentos de activarla no verificaron
  un encabezado de conversación ni un compositor. Una prueba exploratoria con
  flecha abajo + Enter abrió el chat del propio número, no el destinatario
  buscado; no se envió ningún mensaje. El flujo sigue bloqueado antes de la
  confirmación mientras no pueda abrirse y verificarse inequívocamente la
  conversación correcta. Esta evidencia real es exploratoria e histórica; el
  driver actual conserva un gate cerrado si no verifica la conversación, pero
  todavía no tiene una validación de envío real repetible con una cuenta de
  prueba.

Los plugins confiados y habilitados ya pueden ser pasos de un plan compuesto
después de su registro y clasificación externa; esto habilita una vía de
extensión, no demuestra compatibilidad con aplicaciones no instaladas. Confiar
un plugin no lo aísla del proceso de MARK. Gmail `search` se
añade como verificador explícitamente de solo lectura; otros plugins no obtienen
esa capacidad por defecto. La verificación del plan sigue limitada a las
acciones de lectura enumeradas en el hito 38.

Cada integración necesita pruebas offline, permisos mínimos, revocación,
límites, matriz por tipo de cuenta y comprobación de las políticas del
proveedor. Outlook, Excel, TikTok y otras aplicaciones reales todavía no se
han probado en este proyecto.

---

## Fase 6 — Planificación y recuperación avanzada

**Estado: 1/3 hitos completados; avance 33% por conteo.**

### 47. Pausa y reanudación manual

- [x] **47.** Añadir pausa/reanudación manual en el HUD y estados
  `paused`/`waiting_for_user`. La tarea espera entre llamadas; una llamada
  activa no se interrumpe. Los pasos pueden declarar un punto de intervención
  tras la acción y antes de su verificación de solo lectura, por ejemplo para
  MFA, CAPTCHA, permisos o un diálogo. Tras reanudar, MARK verifica antes de
  comenzar otro efecto. Esto no detecta automáticamente esos eventos: el plan
  debe declararlos o el usuario debe pulsar **PAUSE AT SAFE POINT**.

### 48. Recuperación controlada

- [~] **48.** El coordinador pausa ante resultados ambiguos, excepciones o
  evidencia no coincidente; UIA y navegador clasifican errores, y reanudar
  vuelve a ejecutar solo la verificación de lectura (máximo dos
  intervenciones). Hay regresiones sintéticas de timeout, selección ambigua,
  pestaña/ventana desaparecida y no repetición del efecto; la matriz de ocho
  categorías ejecuta cada efecto una sola vez. **Falta validar fallos con una
  integración/aplicación real**, que aún no existe en la Fase 5.

### 49. Idempotencia y límites de tarea

- [~] **49.** En el proceso actual, el registro acotado rechaza volver a
  ejecutar un `task_id` completado; no reintenta efectos, preserva tareas
  activas al llenarse y limita el tiempo activo a cinco minutos, suspendiendo
  el presupuesto durante esperas humanas. La prueba confirma que recuperación
  y cancelación no repiten efectos. El historial persistente guarda solo
  metadatos: **no restaura planes ejecutables tras reiniciar MARK** y los
  conectores API futuros aún necesitan claves de idempotencia propias. El
  reinicio falla cerrado (ID desconocido), no reanuda la tarea.

La recuperación no debe repetir automáticamente acciones con efectos. Si una
operación externa ya está en curso, cancelar debe impedir el siguiente paso y
reportar que no puede interrumpirla de forma segura.

---

## Fase 7 — Calidad, privacidad y compatibilidad

**Estado: 0/3 hitos completos; los tres tienen evidencia parcial.**

### 50. Aplicación de prueba y métricas

- [~] **50.** El fixture WinForms y diálogos sintéticos verifican foco,
  selector exacto, tres variantes incorrectas, duplicados y cierre de ventana;
  cero efectos incorrectos en esos casos. Es evidencia reproducible del
  fixture, no una tasa de precisión de aplicaciones reales. Los resultados por
  aplicación corresponden a la aceptación de cada integración de Fase 5.

### 51. Matriz de compatibilidad

- [~] **51.** Matriz inicial basada solo en evidencia local; los campos no
  capturados quedan explícitamente como no medidos, no como compatibilidad
  asumida:

  | Entorno/aplicación | Evidencia | Resultado y límites |
  | --- | --- | --- |
  | Windows | Windows 11 Home, build 26300, x64; consultado en este entorno | Una sola configuración; no certifica otras versiones/builds |
  | Python | 3.13.7 corresponde a la medición histórica de esta matriz; el corte actual de pruebas se ejecutó en 3.13.14 | Python 3.11/3.12 y la matriz remota siguen pendientes |
  | Diálogo Win32 | `MessageBoxW` sintético, invocado mediante pywinauto UIA | Fixtures opt-in para foco, selección, ambigüedad y cierre; no cubre aplicaciones reales |
  | Formulario WinForms | Ventana sintética con campo y botón, inspeccionada con pywinauto UIA | Prueba opt-in del flujo editable; no certifica aplicaciones WinForms externas |
  | Idioma, escala, resolución, tipo de cuenta | No registrados/controlados por la prueba | Compatibilidad pendiente de ejecutar en una matriz explícita |
  | Web, Office, aplicaciones de terceros y otros builds de Windows | Sin prueba nativa de compatibilidad documentada | No afirmar compatibilidad |

  Método probado: UI Automation local por `pywinauto` (`backend="uia"`), sin
  cuentas ni servicios externos. La matriz describe un único entorno y fixtures;
  no certifica versiones/builds, escalas, idiomas ni aplicaciones reales. La
  compatibilidad por aplicación debe añadirse con cada integración, no bloquear
  una integración que todavía no existe.

### 52. Privacidad, seguridad continua y regresión

- [~] **52.** Existe envoltura de contenido no confiable y minimización en
  algunas rutas; `core/prompt.txt` indica explícitamente que instrucciones
  recibidas en resultados de herramientas son datos, no órdenes. Las
  credenciales Gemini, de proveedores y de campos sensibles
  de plugins ya usan el almacén seguro en Windows. Faltan pruebas amplias de
  prompt injection desde páginas y documentos, revisión continua de
  dependencias/licencias, retención y borrado de logs/capturas/memoria, y
  políticas operativas. Se añade `task_planner mode=clear_history` para borrar
  solo los metadatos persistidos del historial local, tras confirmación HUD
  explícita; valida el archivo antes de reemplazarlo y reporta errores. Las
  tareas activas pueden escribir snapshots nuevos después del borrado. Esto no
  elimina logs, capturas, memoria ni historiales de otros subsistemas. Se
  agregan regresiones adversariales deterministas para contenido web/documental
  que intenta cerrar el wrapper, inyectar un wrapper anidado o exigir acciones
  sensibles; se verifica que los marcadores de contenido permanecen dentro del
  límite y que la representación para humanos restaura el texto original. Estas
  pruebas verifican el límite de datos, no la obediencia del modelo ni una
  defensa completa contra prompt injection. La captura temporal de `screen_debug`
  ahora se elimina también si Gemini no responde; si falla el borrado, se
  reporta `unverified` con la ruta para borrado manual, en vez de ocultarlo.
  El panel de memoria ofrece un borrado explícito, confirmado por el usuario,
  de hechos recordados y resúmenes de sesión; preserva la configuración de
  monitores y no toca capturas/logs. La escritura es atómica, y si el archivo
  está corrupto o no se puede reemplazar, se conserva y se informa el error.
  El reemplazo lógico no garantiza borrado forense de bloques, SSD, copias de
  seguridad ni snapshots del sistema. Hay pruebas de UI que verifican que
  cancelar conserva el archivo y que confirmar ejecuta el borrado sobre un
  archivo temporal, sin tocar la memoria real durante las pruebas.
  El historial permite borrar sus metadatos con confirmación; la auditoría
  acotada es volátil. La captura de depuración usa temporales y limpieza
  acotada; la captura solicitada por el usuario es persistente. **No hay política
  ni borrado unificado de capturas/logs/copias de seguridad**, ni revisión
  automatizada continua de dependencias/licencias. Los controles probados son
  locales; la resistencia del modelo a prompt injection no está demostrada.

---

## Puerta de entrada a Fase 5

**Causa del estancamiento:** la puerta anterior exigía cerrar 47–52 antes de
empezar la Fase 5, pero 48, 50 y 51 requieren evidencia de integraciones reales
que solo se puede obtener durante esa fase. Es una dependencia circular, no una
falta de pruebas sintéticas. Por eso los hitos permanecieron parciales aunque
los casos acotados añadidos sí pasan.

La fase 5 queda **sin autorización para efectos externos no verificados o uso
de producción**,
pero se puede iniciar un piloto de lectura local/acotado. Requisitos del piloto:
47 operativo; pruebas locales de no repetición, timeout y cancelación de 48–49
aprobadas; permisos mínimos y retención definida para el conector elegido.
Cada integración debe aportar sus propias pruebas de fallo, recuperación,
idempotencia y matriz de entorno antes de habilitar escrituras o comunicaciones
externas. No se generaliza compatibilidad desde fixtures. La evidencia actual
demuestra regresiones locales, no ausencia de errores en producción.

## Evidencia actual

- Suite general verificada en el corte más reciente: **464 pruebas aprobadas y
  13 omitidas** (`python -m unittest discover -s tests -q`) con Python
  3.13.14. Las omitidas no cuentan como validación de hardware, cuentas o apps
  reales.
- `python -m compileall -q .`, `python setup.py --dry-run` y
  `python -m pip check` pasan en el entorno local actual. La matriz remota
  Windows/Python 3.11–3.13 no se ejecutó en este corte.
- La integración Windows UIA sintética opt-in pasó **10/10** en esta revisión,
  incluidos el flujo editable de Fase 4 con `ActionRegistry`, la matriz de
  localización, el rechazo de ventanas duplicadas y el cierre no verificable
  tras invocar un botón. La ventana WinForms se marca `TopMost` en el fixture y
  el descubrimiento se acota a 10 ventanas para que no quede enterrada en
  escritorios con muchas ventanas.
- El subconjunto enfocado de regresiones de planes, política, navegador,
  documentos, proveedores y almacenamiento seguro de secretos de plugins pasó
  **139/139**; incluye ejecución de plugins dentro de planes con aprobación
  exacta y verificación, además del contrato Gmail; no sustituye pruebas con
  cuentas ni aplicaciones de terceros.
- Gmail tiene pruebas **simuladas** de OAuth/scope, búsqueda, límites, lectura
  solo de metadatos y marcado no confiable; no se inició OAuth ni se contactó
  Gmail, y la integración no certifica cuentas reales.
- El conteo histórico de **121 archivos Python** y la ejecución **139/139**
  pertenecen a una revisión anterior, no a la suite actual. La sintaxis de los
  archivos actuales pasó con `compileall`; esto no certifica el flujo de audio
  ni las aplicaciones reales.
- Pruebas de credenciales Gemini, proveedores y plugins usan keyring simulado;
  cubren migración, rollback por fallo de escritura, borrado y ausencia de
  secretos nuevos en el JSON. No prueban el backend nativo de Windows Vault.
- La integración usa `MessageBoxW` y una ventana WinForms sintética; no usa
  cuentas, cookies, navegación real, mensajes, compras ni datos externos.
- El código de setup y los tests del repositorio no prueban WinVault en sí ni
  certifican una copia limpia completa; esas comprobaciones requieren evidencia
  de ejecución documentada por separado.

## Orden recomendado para continuar

1. Usar el registro de plugins como extensión para conectores por aplicación,
   con riesgo externo, plan aprobado y verificación independiente; no crear un
   supuesto controlador universal que ejecute acciones arbitrarias.
2. Ejecutar el conector Gmail de solo lectura en una cuenta de prueba
   configurada por el usuario, revisar consentimiento y revocación OAuth y
   validar expiración/errores antes de considerar completo el hito 41. Las
   pruebas simuladas no autorizan acceso a una cuenta ni habilitan envíos.
3. Después medir por separado navegador/UIA en aplicaciones concretas —por
   ejemplo Outlook, Excel y TikTok— según la interfaz disponible y las
   políticas del proveedor. Cada aplicación necesita sus propios resultados
   observados y pruebas; no hereda compatibilidad de otro conector.
4. Mantener escrituras/envíos y los hitos 48–49 parciales hasta probar
   recuperación, no repetición e idempotencia en la integración real. Medir
   compatibilidad y retención por piloto; no elevar porcentajes por añadir más
   fixtures sintéticos.

La meta no es prometer que MARK controla cualquier programa, sino que siempre
puede descubrir, actuar, verificar o detenerse con una explicación clara.
