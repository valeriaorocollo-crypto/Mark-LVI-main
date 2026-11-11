# Plan detallado de seguimiento — MARK LVI

**Actualizado:** 11 de noviembre de 2026
**Documento de estado:** [informe.md](./informe.md)
**Ideas y alcance futuro:** [ideas.md](./ideas.md)
**Regla de ejecución:** cerrar primero privacidad y efectos; después
estabilizar, validar integraciones y ampliar el producto. Ningún porcentaje de
checklist equivale a seguridad o compatibilidad universal.

## 1. Resultado que buscamos

Entregar un asistente Windows útil y mantenible que:

- actúe solo mediante capacidades declaradas y con efectos comprensibles;
- pida aprobación antes de efectos relevantes, y la vincule al objetivo y los
  argumentos mostrados;
- distinga éxito comprobado de acción iniciada, fallo y resultado incierto;
- no repita efectos externos por timeout o ambigüedad;
- explique qué datos consulta, envía y conserva;
- admita cuando una aplicación no expone una interfaz fiable.

**No es objetivo de esta etapa:** control absoluto de Windows, compatibilidad
con toda aplicación, ejecución ilimitada de plugins, envío remoto silencioso o
automatización administrativa genérica.

## 2. Línea base y reglas para no perder el rumbo

### Estado conocido al 11-11-2026

| Evidencia | Estado | Uso correcto |
|---|---|---|
| Suite local del árbol actual | Python 3.11/3.12/3.13; 505 pruebas por versión; 0 fallos; 0 errores; 13/12/13 omitidas | Ejecutada sobre el mismo árbol de trabajo local, todavía sin commit. Los skips están clasificados abajo; no cuentan como aprobados. |
| `evidence/stage0-windows-2026-11-10.json` | Evidencia anterior: 474 tests, 13 skips por cada versión 3.11/3.12/3.13; incluye run 42948215095 | Antecedente; no sustituye un run de la revisión actual. |
| Run 42951554253 | Documentado como verde para Python 3.11–3.13 y commit `2d21993...` | Referencia histórica de otro commit; no atribuirlo al HEAD actual `4461d77`. |
| Workflow Windows | Existe `.github/workflows/windows-tests.yml` con matriz 3.11/3.12/3.13 | Ejecutar después de corregir y subir un commit revisable. |
| HEAD y árbol local | HEAD `4461d77bd108ec49794ff08c8d75c45c2a1b96fe`; árbol sucio con cambios locales y de esta tarea | Las pruebas identifican el HEAD base y se ejecutaron sobre el árbol modificado; no se atribuyen a un commit integrado. |
| Validaciones locales adicionales | `compileall`, `setup.py --dry-run` y `pip check` pasan en Python 3.11/3.12/3.13 | No sustituyen CI ni una instalación limpia. |
| UI holográfica | `ui_holo.py` no existe ni está versionado; la suite observó el fallback | El arranque funciona con paneles simples; reintroducir el módulo sería un cambio separado. |

### Reglas de trabajo

1. Un cambio debe resolver un hallazgo o una capacidad concreta.
2. Para cada P0/P1: primero una prueba de regresión que falle antes del arreglo.
3. No ejecutar pruebas de envío, pago, instalación o cambios de red sin cuenta/
   equipo de prueba y aprobación explícita.
4. `unverified` significa detenerse y consultar; nunca reintentar por defecto.
5. Los tests UIA sintéticos validan el adaptador, no una aplicación real.
6. Los resultados de CI siempre incluyen commit, versión Python, número de
   pruebas, skips y artefacto sanitizado.
7. No copiar código, configuraciones, certificados, secretos ni dependencias de
   otra aplicación desde `AAAA`.
8. Actualizar este plan y el informe cuando cambie la evidencia; retirar cifras
   viejas en vez de apilarlas al final del archivo.

## 3. Mapa de etapas y prioridad

| Orden | Etapa | Prioridad | Estado al corte | Bloquea |
|---:|---|---|---|---|
| 0 | Línea base, árbol y CI reproducibles | P0 de gestión | Parcial: matriz local verde; snapshot previo y CI integrada pendientes | Toda declaración de release |
| 1 | Consentimiento de captura y permisos de pantalla | P0 privacidad | Implementado y probado localmente; aceptación UIA/visual pendiente | Uso sensible desatendido y declaración de cierre integral |
| 2 | Efectos visibles de planes | P1 alto | Parcial: preview y aprobación existen, efecto no representa operación | Habilitar planes con efectos no triviales |
| 3 | Archivos, undo e interrupciones | P1 alto | Base implementada; matriz completa pendiente | Escrituras/borrados desatendidos |
| 4 | Mensajería, Steam y acciones de escritorio reales | P1 alto | Fail-closed parcial; resultados reales incompletos | Envío/instalación automatizados |
| 5 | Dashboard, plugins y confianza | P1 alto | Varias mitigaciones implementadas; identidad remota/sandbox pendientes | Uso remoto y plugins de terceros |
| 6 | Dependencias, pruebas y diagnóstico | P1/P2 | Matriz local 3.11–3.13 verde; CI integrada, reproducibilidad de instalación y warnings pendientes | Publicar compatibilidad |
| 7 | Integraciones por aplicación | P2, bajo gate | Pilotos; no cerrar por una ejecución sintética | Expansión de capacidades |
| 8 | Privacidad, manual, onboarding y UX | P2 | Parcial/no consolidado | Incorporación de usuarios externos |
| 9 | Métricas, modularización e instalador | P3 | Ideas, no requisito inmediato | Escalado/distribución |

Las etapas 1–5 se pueden trabajar con ramas/cambios cortos en secuencia. No
empezar integraciones con efectos externos mientras una puerta P0 relacionada
esté abierta.

## 4. Etapa 0 — línea base y evidencia para el equipo

**Objetivo:** que cada colaborador sepa qué commit probó y qué significan los
resultados.
**Estado:** parcial; no asumir que la evidencia histórica cubre el árbol local.

### Tareas

- [ ] Registrar el hash de HEAD y `git status --short` antes de cambios. El
  snapshot previo no quedó conservado como artefacto; el HEAD base y el estado
  actual se registran arriba/abajo sin reconstruir el pasado.
- [ ] Acordar cómo se integran los cambios locales preexistentes; se
  conservaron, sin commit ni reversión.
- [x] Ejecutar unittest completo en Python 3.11, 3.12 y 3.13: 505 pruebas por
  versión, 0 fallos y 0 errores; 13, 12 y 13 skips, respectivamente.
- [x] Clasificar los skips: `test_stale_cleanup_does_not_follow_or_remove_symlinks`
  se omite porque el entorno no permite crear enlaces simbólicos (3.11–3.13);
  `test_local_docx_search_includes_table_cells_without_writing` se omite por
  falta de `python-docx` en 3.11 y 3.13 (pasa en 3.12);
  `test_local_excel_preview_reads_all_supported_sheets_without_writing` se
  omite por dependencias opcionales `pandas`/`openpyxl` en las tres versiones.
  Los otros 10 skips son pruebas opt-in de UI Automation: se omiten porque no
  se definió `MARK_RUN_UIA_INTEGRATION=1` y crean/interactúan con ventanas:
  `test_focus_control_on_local_synthetic_window`,
  `test_uia_focus_selector_matrix_measures_exact_and_near_miss_targets`,
  `test_focus_control_stops_when_window_disappears`,
  `test_focus_window_activates_local_synthetic_window`,
  `test_uia_activate_window_verifies_local_synthetic_window`,
  `test_uia_invoke_control_reports_closed_window_as_unverified`,
  `test_uia_invoke_control_rejects_wrong_selector_without_effect`,
  `test_uia_invoke_control_rejects_duplicate_windows`,
  `test_task_plan_activates_and_verifies_synthetic_window` y
  `test_task_plan_writes_and_reads_synthetic_edit`. No equivalen a pruebas
  aprobadas ni a validación de aplicaciones reales.
- [x] Ejecutar unittest en Python 3.11 y 3.13 del mismo árbol local.
- [x] Ejecutar `python -m compileall -q .`, `python setup.py --dry-run` y
  `python -m pip check` con Python 3.11, 3.12 y 3.13; los tres comandos pasan
  en cada intérprete.
- [ ] Lanzar workflow Windows desde el commit integrado y guardar links/
  artefactos por intérprete; confirmar que los runs 42948215095 y 42951554253
  son referencias históricas. No hay commit integrado de este árbol.
- [x] Registrar que el módulo UI opcional `ui_holo.py` no está en el árbol y
  que se observó el fallback funcional; no se decidió reintroducirlo.
- [x] Documentar solo versiones, estados, conteos y motivos técnicos de skips;
  no se incorporaron secretos, texto de usuario, capturas ni rutas personales.

### Salida

- La matriz 3.11/3.12/3.13 del mismo commit está verde o cada fallo queda
  asignado y explicado.
- Los skips se explican y no se presentan como aprobados.
- La línea base local está registrada; la CI reproducible del commit integrado
  sigue abierta.

## 5. Etapa 1 — consentimiento de pantalla/cámara y grants

**Prioridad:** P0 privacidad.
**Archivos orientativos:** `main.py`, `core/action_policy.py`,
`core/session_grants.py`, `core/confirm.py`, `core/tool_audit.py`, `ui.py`,
`actions/computer_control.py`, pruebas de captura/grants.

### Decisión acordada de producto

- MARK debe recordar permisos específicos entre reinicios para evitar pedir la
  misma autorización cada vez que inicia.
- Cada permiso recordado vence **30 días después de concederse** (no renovar
  automáticamente el plazo al usarlo), se puede revocar individualmente o en
  conjunto desde el HUD y queda asociado al usuario/perfil local; no se
  sincroniza ni se amplía a otras cuentas o equipos.
- La aprobación se origina siempre en un control humano del HUD. El modelo no
  puede crear, ampliar ni renovar permisos.
- Los permisos son exactos por capacidad, integración/proveedor y recurso u
  objetivo visible. Cambiar destinatario, ventana, cuenta, archivo, calendario
  o argumentos que alteren el efecto exige una aprobación nueva.
- Enviar mensajes, borrar/sobrescribir, publicar, comprar/pagar y cambios
  administrativos o de seguridad **siempre requieren confirmación por
  operación**, aunque exista otro permiso recordado.
- Lectura/captura de pantalla es sensible: no se habilita en segundo plano.
  Cada uso debe tener una tarea o petición clara, mostrar un indicador antes de
  transmitir y respetar el alcance concedido. Si no se puede fijar el objetivo,
  se pregunta otra vez.
- El almacén local persistente, el vencimiento fijo, el alcance por tarea y la
  revocación están implementados. La aceptación integral sigue pendiente de
  pruebas opt-in de UIA y validación visual del HUD en una sesión real.

### 1A. Captura del modelo

- [x] Inventariar las entradas a `_capture_screen` y `_capture_camera`,
  incluida `screen_process`, `screen_find`, herramientas de código y debug.
- [x] No existe una ruta de captura por petición directa que salte el gate:
  las llamadas de herramienta pasan por la misma aprobación HUD o por un
  permiso persistente exacto. Una petición del usuario por sí sola no concede
  compartir la imagen con el proveedor.
- [x] Bloquear captura solicitada por el modelo hasta que exista consentimiento
  humano o una tarea explícita cubierta por un permiso persistente exacto.
- [x] Mostrar indicador de captura/transmisión antes de capturar; cubrir
  también pantalla, no solo el stream de cámara.
- [x] Incluir fuente/alcance en el panel y el proveedor que recibirá la imagen;
  la captura local no se transmite y exige destino local explícito.
- [x] Permitir detener la operación y comprobar que el siguiente paso no se
  ejecuta.
- [x] Mantener en memoria las capturas enviadas; cubrir fallos/cancelación y
  eliminar el archivo temporal de `screen_debug`. No se guarda una captura de
  debug persistente; las capturas locales solo se escriben en el destino
  explícito elegido para esa operación.
- [x] Mantener cooldown y límites como control de abuso adicional, nunca como
  sustituto del consentimiento.

### 1B. Permiso reutilizable

- [x] Cambiar el almacén en memoria por un almacén local persistente, versionado
  y escrito atómicamente. Al leer un registro inválido, expirado o de otra
  cuenta/perfil, ignorarlo y fallar cerrado.
- [x] Persistir solo metadatos de permiso: ID, capacidad, integración,
  objetivo/recurso, fecha concedida, fecha de vencimiento, etiqueta revisable y
  estado de revocación; no guardar argumentos sensibles ni contenido capturado.
- [x] Implementar vencimiento fijo a 30 días desde la aprobación; no extenderlo
  por uso. Renovar requiere una nueva decisión explícita en el HUD.
- [x] Migrar o eliminar el grant actual de `screen_find` si su alcance no puede
  delimitarse; nunca convertir automáticamente el antiguo
  `active_screen` en una autorización más amplia.
- [x] Mantener en memoria los tokens de aprobación de planes y las sesiones
  efímeras; persistir únicamente grants explícitos, no una tarea aprobada para
  ejecución futura.
- [x] Revocar automáticamente al cambiar la cuenta/perfil dueño del almacén;
  mantener el permiso entre reinicios de MARK en el mismo perfil.
- [x] Mostrar permiso activo, alcance, caducidad y uso reciente; ofrecer
  “revocar seleccionado” y “revocar todo”.
- [x] Mostrar el botón de permiso recordado con su vigencia (“Recordar este
  permiso por 30 días”), separado de “Aprobar esta vez”; no presentar un
  permiso persistente como un grant temporal de una sola sesión.
- [x] Proteger los handlers de alto impacto para que grants nunca omitan su
  confirmación por operación.
- [x] Registrar solo metadatos de creación/uso/revocación; no guardar imágenes,
  contenido ni argumentos sensibles.
- [x] Usar una decisión tipada de HUD; asegurar que texto, red o salida del
  modelo nunca puedan conceder permiso.
- [x] El HUD aclara que el permiso se guarda aunque la operación falle; la
  elección de “recordar” precede a la ejecución y no se revierte ante un fallo.

**Estado de aceptación:** implementación y pruebas unitarias completadas en el
árbol local. La prueba de timeout/cancelación, las rutas de captura y el almacén
de grants pasan; también pasan las suites de la matriz local. No cerrar la
aceptación integral hasta ejecutar la CI sobre un commit integrado y la prueba
opt-in/visual del HUD en un entorno autorizado. Las 10 pruebas UIA omitidas no
se consideran aprobadas.

### Pruebas de salida

- Sin usuario/plan aprobado, no se llama a captura ni al proveedor.
- La indicación aparece antes de cada captura autorizada y desaparece al
  terminar.
- Un grant para una ventana/tarea no autoriza otra; cambiar destino/argumentos
  invalida el grant.
- Un permiso aprobado sobrevive al reinicio de MARK en el mismo perfil y no
  aparece en otro perfil/equipo.
- El permiso vence exactamente 30 días tras su aprobación; usarlo no reinicia
  el plazo; una renovación requiere aprobación humana nueva.
- Las acciones de alto impacto siempre crean una confirmación por operación.
- Revocación individual y global impiden la siguiente operación inmediatamente.
- `revoke_all` limpia permisos y no deja la UI mostrando estados obsoletos.
- No aparecen bytes de imagen/texto en los eventos de auditoría.

## 6. Etapa 2 — efecto legible y exacto en planes

**Prioridad:** P1 alto.
**Archivos orientativos:** `core/task_plan.py`, `core/tool_audit.py`,
`core/action_policy.py`, `ui.py`, tests `test_task_plan*`.

### Tareas

- [ ] Sustituir `classify_effect("started" if action else "unknown")` por
  clasificación desde herramienta, acción y argumentos del paso.
- [ ] Incluir en cada paso del preview: objetivo, efecto, alcance/datos,
  riesgo, verificación esperada y punto de intervención.
- [ ] Devolver error/fallo si efecto no se conoce o no cabe completo en la
  confirmación; no presentar una vista parcial como aprobación suficiente.
- [ ] Redactar secretos sin ocultar el destinatario, ruta o cuenta que se debe
  revisar para decidir.
- [ ] Revalidar la misma firma y efecto al ejecutar, no solo al crear el plan.
- [ ] Mantener autorización de plan ligada a las firmas exactas y sin crear
  permisos para tareas futuras.
- [ ] Mostrar estados por paso y evidencia legible; distinguir el resultado
  observado del texto recibido del modelo.
- [ ] Probar argumentos modificados, selector ambiguo, efecto desconocido,
  fallo de verificación, cancelación y continuidad tras timeout.

### Salida

La persona puede explicar qué efecto producirá cada paso antes de aprobar; un
paso desconocido se detiene antes del handler; la aprobación vieja no cubre
cambios de objetivo.

## 7. Etapa 3 — integridad de archivos, undo y fallos reales

**Prioridad:** P1 alto.
**Archivos orientativos:** `actions/file_controller.py`, `core/undo.py`,
pruebas del controlador.

### Tareas

- [ ] Conservar los arreglos ya descritos: destino de copy no se sobrescribe,
  snapshot estricto de escritura, reemplazo atómico y undo condicionado a
  identidad/contenido.
- [ ] Completar matriz de archivo destino preexistente, binario/no UTF-8,
  archivo grande, lectura denegada, ACL, nombre largo/Unicode, archivo abierto
  y enlace simbólico.
- [ ] Probar interrupción antes/durante/después de reemplazo y limpieza de
  temporales.
- [ ] Definir undo de carpetas/copia recursiva y cambios hechos por otra
  aplicación después de la operación.
- [ ] Cubrir volumen local, medio extraíble y recurso de red solo con
  fixtures/cuentas de prueba; registrar entorno y evidencia cuando se realice
  una prueba real.
- [ ] Garantizar que cualquier operación que no pueda respaldarse de forma
  recuperable falle antes de alterar el original.
- [ ] Mantener confinamiento a rutas permitidas; no ampliar acceso al disco
  completo para “hacerlo más universal”.

### Salida

Ningún destino preexistente se pierde silenciosamente; undo restaura los bytes
originales solo si el estado actual coincide; los fallos informan el resultado
real y no prometen recuperación no disponible.

## 8. Etapa 4 — mensajería, Steam y desktop

**Prioridad:** P1 alto.
**Archivos orientativos:** `actions/send_message.py`,
`plugins/_whatsapp_core.py`, `actions/game_updater.py`,
`actions/computer_control.py`.

### Mensajería

- [ ] Conservar apagado el sender genérico de PyAutoGUI/navegador para
  plataformas no verificadas.
- [ ] No repetir un mensaje cuyo estado sea `unverified`; informar que puede
  haberse enviado y pedir al usuario que revise la conversación.
- [ ] Validar WhatsApp únicamente con una cuenta de prueba, un destinatario
  acordado, chat/encabezado y texto observado. El texto en el compositor no
  equivale a entrega.
- [ ] Si el driver no puede identificar exactamente una conversación,
  detenerse antes de escribir.
- [ ] Registrar versión de app, idioma, escala, estado de sesión y resultados
  sin conservar cuerpo de mensaje.
- [ ] No desarrollar grants de contactos hasta que se decida scope y política
  de consentimiento; el flujo actual no debe heredar permisos amplios.

### Steam y automatización local

- [ ] Mantener instalación manual desde el diálogo oficial; validar título,
  cuenta, biblioteca y espacio antes de abrirlo.
- [ ] Confirmar que no haya fallbacks por coordenada ni “éxito” si el estado de
  Steam solo indica que abrió un diálogo.
- [ ] No automatizar compras ni completar acciones de cuenta.
- [ ] Para otros controles de escritorio, incluir pruebas de foco incorrecto,
  selector múltiple, ventana cambiada, cancelación y revalidación antes del
  efecto.
- [ ] Mapear herramientas inline en `main.py`: lectura, captura, memoria,
  cierre y cambios. Cada mutación debe tener política/confirmación equivalente
  al dispatcher.

### Salida

Plataformas no soportadas fallan sin teclear; ningún selector ambiguo usa una
coordenada de reserva; el resultado externo es verificado o se informa como
incierto sin reintento.

## 9. Etapa 5 — dashboard remoto y frontera de plugins

**Prioridad:** P1 alto.

### Dashboard

- [ ] Confirmar por lectura y tests que iniciar el servidor no cambia
  firewall/perfil, no eleva privilegios y no altera procesos ajenos.
- [ ] Mantener control remoto opt-in y apagado por defecto donde la UX lo
  permita.
- [ ] Validar emparejamiento, rate limit, expiración/revocación y flujo ante
  certificado incorrecto.
- [ ] Probar identidad HTTPS desde cliente separado sin desactivar validación
  TLS; documentar cómo se confía en el certificado o reemplazarlo por una
  identidad apropiada al producto.
- [ ] Mantener prueba loopback con certificado temporal; no abrir puertos en
  CI.
- [ ] Definir explícitamente el riesgo si el usuario fuerza HTTP, con advertencia
  visible antes de transmitir tokens/comandos.

### Plugins

- [ ] Documentar que hash + aprobación + habilitación solo prueban
  consentimiento/integridad del archivo, no la seguridad del código.
- [ ] Mantener plugins externos como `external` en clasificación; no elevarlos
  a confianza por pasar un test o mostrar un panel.
- [ ] Añadir pruebas de archivo modificado después de confiarlo, fuente
  demasiado grande, import side effect y plugin deshabilitado.
- [ ] Decidir si el producto soportará solo código local confiable o si necesita
  sandbox por proceso antes de plugins de terceros.
- [ ] Si se decide sandbox: diseñar IPC tipado, lista de capacidades, acceso
  limitado, timeout, cancelación y memoria; revisar amenazas antes de
  implementarlo.

### Salida

La configuración local no se modifica al iniciar el dashboard; remoto exige
identidad verificable; la interfaz explica de forma honesta los permisos del
plugin y no sugiere que existe sandbox.

## 10. Etapa 6 — calidad continua, dependencias y diagnóstico

**Prioridad:** P1/P2.

### Tareas

- [ ] Ejecutar matriz CI del mismo commit en Python 3.11/3.12/3.13 y retener
  artefacto sanitizado.
- [ ] Reducir warnings de `Starlette TestClient`/`httpx` y `pynvml`; elegir
  dependencia recomendada en vez de ocultar el warning.
- [ ] Revisar límites de versión y necesidad de cada dependencia base; mover
  Playwright/OpenCV/documentos/integraciones pesadas a extras si no son
  requeridas por arranque mínimo.
- [ ] Agregar lockfile o procedimiento de resolución reproducible para release
  sin romper instalación por extras.
- [ ] Seleccionar Ruff y un verificador de tipos; aplicar al código tocado y
  luego fijar una línea base gradual.
- [ ] Añadir prueba de instalación temporal/importación/startup sin secretos ni
  cuentas; no usar `setup.py --dry-run` como sustituto de instalar.
- [ ] Convertir los skips en una tabla versionada: test, razón, alternativa,
  responsable y condición para eliminar el skip.
- [ ] Inventariar módulos que crean archivos/red/conexiones al importarse y
  aislar efectos secundarios.

### Salida

El mismo commit instala y prueba en la matriz publicada; los extras no
necesarios no son obligatorios; la CI informa sin ambigüedad de cada skip y
ninguna prueba requiere secreto real.

## 11. Etapa 7 — integraciones por aplicación

**Prioridad:** P2. Iniciar una integración a la vez después de cerrar las
puertas P0 relacionadas.

### Ficha obligatoria por conector

1. Alcance soportado y explícitamente excluido.
2. API oficial/protocolo preferido y fallback limitado.
3. Permisos/scopes mínimos, consentimiento, revocación y datos enviados.
4. Cuenta/dispositivo de prueba; versiones, idioma, escala y sistema probados.
5. Preview y confirmación para toda escritura/envío/cambio irreversible.
6. Verificación independiente y estados `done`, `unverified`, `failed`, `ask`.
7. Timeouts, cancelación, duplicados, reintento, idempotencia y revocación.
8. Política de proveedor cumplida; no eludir CAPTCHA, MFA, DRM ni controles.

### Orden sugerido

1. **Spotify:** ampliar matriz de UI/API y límites de cuenta; verificar el
   estado mostrado sin afirmar salida audible.
2. **Gmail:** cuenta de prueba, consentimiento/revocación OAuth, expiración,
   red y errores; mantener solo lectura.
3. **Calendario:** decidir proveedor; lectura primero, zona horaria y calendario
   explícitos; después crear evento con preview y sin invitación automática.
4. **Outlook:** Microsoft Graph con permisos mínimos, lectura y borradores
   antes de envío.
5. **Navegador:** perfiles/dominos soportados, política de formularios y
   pruebas ante cambio de página.
6. **Git / VS Code / Visual Studio:** tratarlos por separado; empezar con
   inspección de diff y tests en workspace elegido.
7. **WinRAR/archivos comprimidos y herramientas Windows:** solo operaciones
   delimitadas, preview y límites de expansión/permisos.
8. **WhatsApp:** continuar únicamente si la ruta está autorizada y una cuenta
   de prueba permite validar destinatario y resultado de forma repetible.

### Salida por integración

Una ejecución correcta no cierra un conector. Debe pasar la ficha completa,
pruebas offline, prueba real de bajo riesgo y evidencia reproducible para la
versión declarada. Si el proveedor no expone una vía segura, la capacidad queda
limitada o deshabilitada.

## 12. Etapa 8 — privacidad, documentación, onboarding y UX

**Prioridad:** P2; empezar documentación técnica después de cerrar contratos de
Etapas 1–2, para que el manual no prometa funciones inexistentes.

- [ ] Inventariar memoria, historial, auditoría, logs, capturas temporales,
  capturas persistentes, dashboard y credenciales: datos, ubicación, acceso,
  retención y borrado.
- [ ] Crear guía consultable por tema, en español, para funciones reales,
  configuración y solución de problemas.
- [ ] Añadir ayuda contextual por integración: requisito, permisos, datos,
  ejemplos, errores, riesgo y desactivación.
- [ ] Crear onboarding con pruebas de micrófono/proveedor y permisos opcionales,
  sin bloquear por integraciones no configuradas.
- [ ] Construir un panel de salud que no exponga secretos y que sugiera pasos
  de solución de problemas.
- [ ] Mostrar actividad con estado verificado/no verificado y opción de cancelar.
- [ ] Probar accesibilidad de HUD/teclado/lector de pantalla, sin depender solo
  de color o animación.
- [ ] Asegurar que términos sobre privacidad se basen en rutas comprobadas y
  revisión de proveedores; no reutilizar afirmaciones de Torvis.

### Salida

El usuario puede entender qué ofrece su build, qué se comparte y cómo
desactivar/borrar datos sin tener que inferirlo del código.

## 13. Etapa 9 — observabilidad, modularización y distribución

**Prioridad:** P3; no anteponer a brechas de privacidad/efectos.

### Medición

- [ ] Medir con reloj monotónico fin de voz, STT, primer resultado LLM,
  herramientas, verificación, primer audio y tiempo total.
- [ ] Guardar agregados opt-in sin audio, texto, destinatarios, rutas ni
  capturas; publicar P50/P95 por tarea y dispositivo.
- [ ] Medir tasa de `unverified`, fallos y cancelaciones además de latencia.
- [ ] Reemplazar sleeps de UI por espera de condición + timeout; no paralelizar
  operaciones que comparten foco.

### Refactor

- [ ] Extraer de `ui.py` paneles independientes con API estable y tests.
- [ ] Separar `main.py` en ciclo de sesión, entrada/salida y coordinación de
  herramientas.
- [ ] Dividir `computer_control.py` entre UIA, captura, procesos y entrada,
  manteniendo política en la capa de despacho.
- [ ] Separar dashboard por transporte, TLS/pairing y acceso remoto.
- [ ] Revisar `file_processor.py` por formato solo después de asegurar pruebas.
- [ ] Unificar nombre MARK/JARVIS gradualmente, conservando compatibilidad
  donde sea necesario.

### Distribución

- [ ] Decidir si se va a crear instalador Windows.
- [ ] Si sí: definir arquitectura, instalación por usuario, firma, actualización
  verificable, accesos directos, desinstalación y tratamiento de datos locales.
- [ ] Inventariar licencias/atribuciones de modelos y dependencias distribuidas.
- [ ] Mantener fallback funcional si UI holográfica u otro recurso cosmético
  falta.

## 14. Dependencias entre etapas

```text
Etapa 0 (baseline) ──┬──> Etapa 1 (captura/grants) ──┬──> Etapa 2 (efectos de plan)
                     │                                ├──> Etapa 3 (archivos)
                     │                                └──> Etapa 4 (mensajería/desktop)
                     ├──> Etapa 5 (dashboard/plugins) ──┐
                     └──> Etapa 6 (calidad)             │
                                                        v
                                  Etapa 7 (conectores por aplicación)
                                                        v
                                   Etapa 8 (ayuda/UX/política documentada)
                                                        v
                                      Etapa 9 (medición/refactor/distribución)
```

La documentación y los tests pueden avanzar en paralelo, pero la activación de
funciones no debe saltar su puerta técnica.

## 15. Puertas de aceptación para efectos sensibles

Antes de permitir uso autónomo/desatendido, responder “sí” a todo:

- ¿El efecto y el objetivo están identificados sin inferirlos de coordenadas?
- ¿La persona vio destinatario, cuenta, ruta, contenido y proveedor relevantes?
- ¿La aprobación está vinculada a argumentos exactos y deja de ser válida si
  cambia el objetivo?
- ¿Se pidió permiso antes de capturar/enviar datos?
- ¿Se usa una API/UIA confiable y no un clic ciego como plan de respaldo?
- ¿El resultado se verifica por una observación independiente del texto del
  modelo?
- ¿Timeout/cancelación impiden repetir el efecto?
- ¿Hay revocación de permisos y una política de retención clara?
- ¿La prueba cubre la aplicación/versión que se anuncia?

Si hay un “no” o “no medido”, limitar a lectura, piloto supervisado o dejar la
capacidad bloqueada.

## 16. Prioridades para la siguiente sesión

1. Confirmar con el compañero el árbol de trabajo y ejecutar CI sobre el commit
   que se entregará.
2. Ejecutar las 10 pruebas opt-in UIA y la aceptación visual del HUD en un
   entorno autorizado; adjuntar evidencia sin datos sensibles.
3. Validar el flujo de grants en el HUD, incluido reinicio y perfil, y mantener
   la política de tarea exacta/30 días ya implementada.
4. Mostrar efecto por paso en los planes y validar argumentos al ejecutar.
5. Conservar mensajería genérica bloqueada y no repetir WhatsApp ambiguo.
6. Validar panel TLS/remoto y plugin trust en pruebas controladas.
7. Solo después, elegir una integración de lectura de alto valor y completar su
   matriz.

## 17. Relación con los documentos anteriores

Este archivo sustituye como plan operativo a
`ROADMAP_CONTROL_UNIVERSAL.md`; el detalle de hallazgos de seguridad está
integrado en [informe.md](./informe.md). Los
documentos antiguos pueden quitarse del directorio después de comprobar que se
quiere descartar su formato/registro histórico. `SECURITY-REVIEW.md` tenía
cambios locales sin commit antes de esta consolidación: revisar/preservar esos
textos únicos antes de eliminarlo, porque no necesariamente existen en Git.
No se borraron aquí. No usar los porcentajes antiguos como estado actual.
