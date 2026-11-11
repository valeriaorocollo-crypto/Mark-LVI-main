# Security review — MARK LVI

## Alcance

Revisión de código y pruebas locales de las rutas P0/P1 descritas en
[informe.md](./informe.md). No es una auditoría exhaustiva, prueba de
penetración, revisión de dependencias ni certificación de seguridad. Se
intentó un envío autorizado por WhatsApp; el último resultado quedó
`unverified`, por lo que no se afirma que haya sido entregado. Steam abrió
el diálogo real, pero no se completó ninguna instalación. No se cambió el
firewall ni se inspeccionaron credenciales locales.

Entorno de pruebas: Windows, Python 3.11.9, 3.12.10 y 3.13.14. En local, en
cada versión: **474 ejecutadas, 461 aprobadas y 13 omitidas**, compilación,
setup dry-run y `pip check` aprobados. Playwright Python 1.64.1 y driver
1.64.0-beta comparten la línea 1.64; Chromium 156.0.8078.4 se abrió en los
tres intérpretes. Se añadió una prueba HTTPS local con certificado temporal
confiado por HTTPX, que obtuvo HTTP 200. Dos omitidas requieren dependencias
documentales opcionales, una prueba de symlink no disponible en el entorno y
10 pruebas UIA opt-in que pasaron por separado en Python 3.13 con ventanas
sintéticas. La primera CI remota (run 42947058149, commit `57542f3`) encontró
dos tests frágiles ante alias corto/largo de rutas Windows. Se corrigieron las
aserciones y la matriz remota final ([run 42948215095](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42948215095),
commit `bd6c9ccd61dd6f83854b13e7b42fe0ccc7dfabde`) pasó en Python 3.11.9,
3.12.10 y 3.13.17; cada job ejecutó tests, compilación, setup dry-run,
consistencia de dependencias y smoke test de Chromium, y cargó evidencia
sanitizada. Las omisiones locales y validaciones externas no se consideran
aprobadas por la matriz general.

## Hallazgos y estado

| Prioridad | Superficie | Estado | Riesgo residual |
|---|---|---|---|
| P0 | Política de efectos y confirmación | Se añadió un contrato de efectos por acción; los efectos desconocidos, entradas de teclado/ratón opacas y controles sin alcance verificable fallan cerrados. Se exige confirmación para escritura/invocación UIA sin depender de etiquetas, y se gatean registries de acciones/plugins, planes y handlers directos. La suite completa pasa localmente y la matriz remota [run 42951554253](https://github.com/valeriaorocollo-crypto/Mark-LVI-main/actions/runs/42951554253) pasa en Python 3.11/3.12/3.13. | Pruebas sintéticas no prueban cada semántica de aplicación real; acciones deliberadamente opacas quedan bloqueadas, no habilitadas por confirmación genérica. |
| P0/P1 | Copia, escritura y undo en [file_controller.py](./actions/file_controller.py) | Se corrigieron sobrescrituras y undo destructivo reproducidos; pruebas inyectan fallos de `fsync`, reemplazo, lectura y restauración. ACL NTFS denegada, escritura/undo en medio removible y SMB UNC, ENOSPC real en un VHDX temporal y cancelación real en el HUD pasaron; original y recursos temporales quedaron correctamente preservados/limpiados. | La evidencia cubre escenarios acotados, no toda combinación de ACL, volumen y fallo del sistema. |
| P1 | Mensajería | En [send_message.py](./actions/send_message.py), plataformas sin transporte verificado fallan antes de escribir/enviar. El driver UIA acepta resultados cuyo nombre exacto va seguido de metadatos, vuelve a comprobar el encabezado real y ahora intenta recuperar el foco de forma acotada antes de releer controles. El chat “Mi Princesa” se abrió y el encabezado coincidió. Las 19 pruebas del driver pasan en Python 3.11, 3.12 y 3.13. | El HUD mostró el destinatario y texto autorizados. Un intento informó `status=failed`; el último informó `status=unverified`. Una consulta UIA no encontró el texto, pero el usuario indicó que sí se envió. No puede afirmarse entrega ni resultado visual; no se reintentó tras el estado ambiguo. |
| P1 | Steam | En [game_updater.py](./actions/game_updater.py), se retiraron los clics heurísticos y la automatización del diálogo de instalación. Sesión real detectada y diálogo real de instalación abierto; la selección final queda a cargo de la persona. | No se completó ni verificó la instalación; no se probó compra ni se debe automatizarla. |
| P1 | Firewall y procesos | Se eliminó el mutador automático del firewall de [server.py](./dashboard/server.py) y el parche global de `subprocess.Popen` de `main.py`. El cliente de prueba HTTPS local valida el certificado temporal y recibe HTTP 200; el cliente sin confianza rechaza un certificado autofirmado. El ASUS alcanzó la pantalla de acceso remoto HTTPS, sin ingresar una clave. | La confianza del certificado autofirmado no se validó/instaló en el ASUS. El dashboard permite HTTP solo como opción explícita, sin cifrado. |
| P1 | Plugins Python | [plugin_loader.py](./core/plugin_loader.py) no importa código sin confianza explícita; la confianza se liga al hash de un archivo de hasta 2 MiB, y ejecución requiere habilitación separada. | No existe aislamiento. Un plugin confiado ejecuta con los permisos del proceso y puede acceder a recursos locales/red. |

## Controles de permisos implementados

Los grants de sesión son explícitos y diferenciados de «confirmar esta
operación». Actualmente solo autorizan `screen_find` enviando capturas
solicitadas a Gemini. Se mantienen en memoria, vencen a la hora, pueden
revocarse desde la interfaz y no sobreviven al cierre de MARK. No autorizan
clics, mensajería, calendario, compras, borrados ni administración. Los
controles de riesgo alto conservan su confirmación por operación.

La confianza de plugin y el grant de sesión son mecanismos distintos: el
primero autoriza ejecutar código local revisado; el segundo permite repetir una
capacidad concreta y limitada. Ninguno es un sandbox ni un permiso global.

## Seguridad del dashboard

- HTTPS está habilitado por defecto; si no se puede preparar el certificado,
  el servidor no debe degradarse silenciosamente a HTTP.
- HTTP explícito expone comandos y tokens a observación/modificación de red;
  no usarlo en redes compartidas o no confiables.
- El certificado es autofirmado. TLS cifra la conexión, pero el cliente debe
  validar la identidad esperada del servidor.
- El arranque ya no configura reglas, elimina reglas de bloqueo, cambia el
  perfil de red ni solicita elevación. La función de lectura de reglas de
  bloqueo es diagnóstica y no muta el firewall.
- Control remoto sigue siendo una superficie de alto impacto; mantenerlo
  desactivado cuando no se usa y validar emparejamiento/revocación antes de
  exponerlo a una red.

## Acciones requeridas antes de declarar P0/P1 cerrados para este alcance

1. Etapas 0 y 1: matrices remotas aprobadas en los runs 42948215095 y
   42951554253, respectivamente; conservar los artefactos por intérprete.
2. WhatsApp: el encabezado “Mi Princesa” se verificó tras corregir el driver,
   y el usuario lo identificó como el contacto autorizado para
   `+51 988 681 776`. La sesión nueva cargó la recuperación de foco y mostró el
   HUD exacto. Un intento terminó con `status=failed`; el último terminó con
   `status=unverified`. La consulta UIA no encontró el texto, pero el usuario
   confirmó que lo vio enviado. El resultado no tiene verificación
   independiente; no reintentar. Las 19 pruebas focales pasan en Python
   3.11/3.12/3.13.
3. La prueba HTTPS desde el ASUS alcanzó la pantalla de acceso remoto sin
   ingresar una clave. Aún falta verificar la confianza del certificado
   autofirmado, sin cambiar el firewall.
4. La cancelación real en el HUD quedó verificada: una prueba registró
   `Awaiting confirmation` seguido de `Cancelled`, y el archivo de prueba no
   fue creado. Dos intentos previos no completan esa prueba: uno fue aceptado
   y su archivo vacío se eliminó; otro no se procesó porque MARK estaba
   dormido. Los tests automatizados también verifican que cancelar no ejecuta
   la acción.
5. Las 13 omisiones están clasificadas: una prueba de symlink no está
   disponible en el entorno, dos pruebas documentales dependen de extras
   opcionales y las diez UIA opt-in pasaron por separado en Python 3.13 sobre
   ventanas sintéticas. La validación con aplicaciones/cuentas reales sigue
   pendiente donde se indica arriba.
6. Antes de ejecutar plugins de terceros en P2, decidir si la confianza
   explícita en proceso es suficiente o si se requiere aislamiento por
   proceso/IPC. La implementación actual no es un sandbox.

## Dictamen

No se declara un P0/P1 «100% cerrado». La Etapa 0 ya cumplió su criterio de
salida, incluida la matriz remota verde y HTTPS local. La matriz local completa
y las pruebas acotadas de ACL, medio removible, SMB y disco lleno pasaron; la cancelación
real del HUD registró `Cancelled` y no creó el archivo de prueba. El ASUS
alcanzó la pantalla HTTPS de acceso remoto, sin emparejamiento. El encabezado
del chat “Mi Princesa” y el HUD exacto se verificaron. El último intento real
terminó con `status=unverified`; UIA no encontró el texto, aunque el usuario
indicó que sí se envió. No puede afirmarse resultado verificado y no se debe
reintentar. La recuperación de foco pasa 19 pruebas dirigidas en Python
3.11/3.12/3.13. Aún falta completar y verificar Steam y obtener evidencia
verificable del envío de WhatsApp; por tanto, la validación real de P1 no está
cerrada.
No se recomienda reescribir todo el proyecto; sí mantener cerradas las
capacidades no verificadas y evitar presentar confianza de plugin como
aislamiento.
