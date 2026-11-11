"""Small runtime localization helpers for the desktop and remote dashboard."""
from __future__ import annotations

from PyQt6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget


_ES = {
    "English": "Inglés",
    "Spanish": "Español",
    "Automatic": "Automático",
    "OFF": "NO",
    "ON": "SÍ",
    "Select": "Seleccionar",
    "Language": "Idioma",
    "News location": "Ubicación de noticias",
    "City, country (e.g. Tacna, Peru)": "Ciudad, país (p. ej., Tacna, Perú)",
    "Entered manually; no IP geolocation. This value is included in "
    "news search queries sent to the configured search providers.":
    "Se introduce manualmente; no se obtiene la ubicación por IP. Este valor "
    "se incluye en las consultas de noticias enviadas a los proveedores de "
    "búsqueda configurados.",
    "◈ SETUP": "◈ CONFIGURACIÓN",
    "◈ CONTROLS": "◈ CONTROLES",
    "◈ CAMERA FEED": "◈ IMAGEN DE LA CÁMARA",
    "✕ CLOSE": "✕ CERRAR",
    "◈ VISUAL INPUT": "◈ ENTRADA VISUAL",
    "▸ INITIALISE SYSTEMS": "▸ INICIAR SISTEMAS",
    "DEFAULT": "PREDETERMINADO",
    "▸ APPLY CHANGES": "▸ APLICAR CAMBIOS",
    "CANCEL": "CANCELAR",
    "🧩 PLUGIN MANAGER": "🧩 ADMINISTRADOR DE COMPLEMENTOS",
    "CLOSE": "CERRAR",
    "⚠ CONFIRM": "⚠ CONFIRMAR",
    "▸ CONFIRM": "▸ CONFIRMAR",
    "🎧 AUDIO DEVICES": "🎧 DISPOSITIVOS DE AUDIO",
    "▸ APPLY": "▸ APLICAR",
    "🧠 WHAT JARVIS REMEMBERS": "🧠 LO QUE JARVIS RECUERDA",
    "HEARING": "ESCUCHANDO",
    "THINKING": "PENSANDO",
    "SPEAKING": "HABLANDO",
    "☁ GEMINI LIVE": "☁ GEMINI LIVE",
    "🖥 MY OWN SETUP": "🖥 MI PROPIA CONFIGURACIÓN",
    "▸ SAVE & APPLY": "▸ GUARDAR Y APLICAR",
    "▸  SAVE  &  APPLY": "▸  GUARDAR  Y  APLICAR",
    "CLOSE": "CERRAR",
    "⚡ BACKGROUND REQUESTS": "⚡ SOLICITUDES EN SEGUNDO PLANO",
    "◈ CLIPBOARD DETECTED": "◈ TEXTO DEL PORTAPAPELES DETECTADO",
    "NEW KEY": "CLAVE NUEVA",
    "DISMISS": "DESCARTAR",
    "▶ VIDEO": "▶ VÍDEO",
    "🔇 SOUND OFF": "🔇 SONIDO DESACTIVADO",
    "◈ SYS MONITOR": "◈ MONITOR DEL SISTEMA",
    "✋ INTERRUPT [ESC]": "✋ INTERRUMPIR [ESC]",
    "🎙 MICROPHONE ACTIVE": "🎙 MICRÓFONO ACTIVO",
    "🔇 MICROPHONE MUTED": "🔇 MICRÓFONO SILENCIADO",
    "◈ INITIALISATION REQUIRED": "◈ CONFIGURACIÓN INICIAL",
    "◉  REMOTE CONTROL": "◉  CONTROL REMOTO",
    "⊞  CREATE DESKTOP SHORTCUT": "⊞  CREAR ACCESO DIRECTO",
    "◉  AUTO-START: OFF": "◉  INICIO AUTOMÁTICO: NO",
    "◉  AUTO-START: ON": "◉  INICIO AUTOMÁTICO: SÍ",
    "⚙  CUSTOMISE ASSISTANT": "⚙  PERSONALIZAR ASISTENTE",
    "🎧  AUDIO DEVICES": "🎧  DISPOSITIVOS DE AUDIO",
    "🧠  MEMORY": "🧠  MEMORIA",
    "🧩  PLUGINS": "🧩  COMPLEMENTOS",
    "⚙  PLUGIN SETTINGS": "⚙  AJUSTES DE COMPLEMENTOS",
    "🔌  ENGINE & PROVIDERS": "🔌  MOTOR Y PROVEEDORES",
    "🔌  ENGINE  &  PROVIDERS": "🔌  MOTOR Y PROVEEDORES",
    "⛶  FULLSCREEN  [F11]": "⛶  PANTALLA COMPLETA [F11]",
    "⛶ FULLSCREEN [F11]": "⛶ PANTALLA COMPLETA [F11]",
    "🎙  WAKE WORD": "🎙  PALABRA DE ACTIVACIÓN",
    "input": "entrada",
    "output": "salida",
    "🎚  PUSH-TO-TALK": "🎚  PULSAR PARA HABLAR",
    "🎚  PUSH-TO-TALK: OFF": "🎚  PULSAR PARA HABLAR: NO",
    "🎚  PUSH-TO-TALK: {key}": "🎚  PULSAR PARA HABLAR: {key}",
    "🧑  HUD: ANIMATED FACE": "🧑  INTERFAZ: ROSTRO ANIMADO",
    "◉  HUD: REACTOR CORE": "◉  INTERFAZ: NÚCLEO DEL REACTOR",
    "⬇  WAKE WORD: DOWNLOAD": "⬇  DESCARGAR PALABRA DE ACTIVACIÓN",
    "🎙  WAKE WORD: ON": "🎙  PALABRA DE ACTIVACIÓN: SÍ",
    "🎙  WAKE WORD: OFF": "🎙  PALABRA DE ACTIVACIÓN: NO",
    "😴  SLEEP NOW": "😴  DORMIR AHORA",
    "👂  WAKE NOW": "👂  ACTIVAR AHORA",
    "🎙  DOWNLOADING… (one-time)": "🎙  DESCARGANDO… (solo una vez)",
    "☀  MORNING BRIEF: ON": "☀  RESUMEN MATUTINO: SÍ",
    "☀  MORNING BRIEF: OFF": "☀  RESUMEN MATUTINO: NO",
    "MICROPHONE stays closed until you hold the key — nothing is sent "
    "until you choose to speak.": "El micrófono permanece cerrado hasta que mantengas "
    "pulsada la tecla; no se envía nada hasta que decidas hablar.",
    "Microphone stays closed until you hold the key — nothing is sent "
    "while you are not holding it.":
    "El micrófono permanece cerrado hasta que mantengas pulsada la tecla; "
    "no se envía nada mientras no la mantengas pulsada.",
    "An animated head that speaks your words and shows what JARVIS is "
    "doing. Tap to switch to the reactor core.":
    "Un rostro animado que articula tus palabras y muestra lo que hace JARVIS. "
    "Pulsa para cambiar al núcleo del reactor.",
    "A reactor core that turns with the state and moves with your voice. "
    "Tap to switch to the animated head.":
    "Un núcleo de reactor que gira según el estado y reacciona a tu voz. "
    "Pulsa para cambiar al rostro animado.",
    "Type a command or question…": "Escribe una orden o pregunta…",
    "◈  INITIALISATION REQUIRED": "◈  CONFIGURACIÓN INICIAL",
    "Configure J.A.R.V.I.S. before first boot.": "Configura J.A.R.V.I.S. antes de iniciarlo.",
    "GEMINI API KEY": "CLAVE DE API DE GEMINI",
    "OPERATING SYSTEM": "SISTEMA OPERATIVO",
    "INITIALISE SYSTEMS": "INICIAR SISTEMAS",
    "ASSISTANT NAME": "NOMBRE DEL ASISTENTE",
    "ASSISTANT VOICE": "VOZ DEL ASISTENTE",
    "YOUR NAME (leave blank for default sir / efendim)":
        "TU NOMBRE (déjalo vacío para usar el tratamiento predeterminado)",
    "OUTPUT VOLUME": "VOLUMEN DE SALIDA",
    "TRANSLATE": "TRADUCIR",
    "SUMMARISE": "RESUMIR",
    "EXPLAIN": "EXPLICAR",
    "FIX": "CORREGIR",
    "e.g. Tony (leave blank for auto)": "Ejemplo: Tony (déjalo vacío para elegir automáticamente)",
    "#00d4ff (custom hex colour)": "#00d4ff (código de color personalizado)",
    "Choose what powers the conversation. Gemini is the default and needs nothing set up here.":
        "Elige qué motor mantiene la conversación. Gemini es el predeterminado y no requiere configuración aquí.",
    "Gemini Live. Nothing on this panel changes the conversation.":
        "Gemini Live. Este panel no cambia la conversación.",
    "One connection carries your voice, its voice, the transcript and the tools together. The fastest option — about half a second to the first word.":
        "Una sola conexión gestiona tu voz, la respuesta hablada, la transcripción y las herramientas. Es la opción más rápida: medio segundo hasta la primera palabra.",
    "Your choice of hearing, thinking and speaking. Can run entirely on this computer, with nothing leaving it. Slower: 1.5 to 4 seconds.":
        "Elige cómo escuchar, razonar y hablar. Puede funcionar por completo en este equipo, sin enviar datos fuera. Es más lento: de 1,5 a 4 segundos.",
    "Gemini only — the way it has always been":
        "Solo Gemini — como siempre",
    "Try Gemini first — faster": "Probar Gemini primero — más rápido",
    "Try the other one first — keeps more on your machine":
        "Probar primero el otro — mantiene más datos en tu equipo",
    "Phone connected — JARVIS ready": "Teléfono conectado — JARVIS está listo",
    "No configurable plugins are installed. Drop a plugin that needs settings (like the 3D-printer suite) into the plugins folder and it will show up here.":
        "No hay complementos configurables. Añade a la carpeta de complementos uno que requiera ajustes (como el de impresoras 3D) y aparecerá aquí.",
    "⚠ ② THINKING is not set — without it the assistant falls back to Gemini Live and says so in the log.":
        "⚠ ② No está activado el razonamiento. Sin él, el asistente usará Gemini Live y lo indicará en el registro.",
    "— default —": "— predeterminado —",
    "Forget this": "Olvidar esto",
    "↻ REFRESH": "↻ ACTUALIZAR",
    "BRIEFING": "RESUMEN",
    "QUIZ": "CUESTIONARIO",
    "TEST": "PROBAR",
    "pip install qrcode[pil]": "pip install qrcode[pil]",
    "Video playback is not available in this Qt install.":
        "La reproducción de vídeo no está disponible en esta instalación de Qt.",
    "Just A Rather Very Intelligent System": "Solo Un Sistema Muy Inteligente",
    "Personal AI Assistant": "Asistente personal de IA",
    "◈ REMOTE ACCESS": "◈  ACCESO REMOTO",
    "— not set —": "— sin configurar —",
    "AI CORE ACTIVE": "NÚCLEO DE IA ACTIVO",
    "SEC CLEARED": "SEGURIDAD APROBADA",
    "ACTIVITY LOG": "REGISTRO DE ACTIVIDAD",
    "FILE UPLOAD": "CARGA DE ARCHIVOS",
    "COMMAND INPUT": "ENTRADA DE ÓRDENES",
    "◈  CAMERA FEED": "◈  IMAGEN DE LA CÁMARA",
    "✕  CLOSE": "✕  CERRAR",
    "Select a file for JARVIS": "Selecciona un archivo para JARVIS",
    "Drop file here  or  Click to Browse": "Suelta el archivo aquí o haz clic para buscar",
    "Images · Video · Audio · PDF · Docs · Code · Data": "Imágenes · Vídeo · Audio · PDF · Documentos · Código · Datos",
    "Release to load": "Suelta para cargar",
    "Settings & Controls": "Ajustes y controles",
    "Setup — things you set once": "Configuración inicial",
    "Controls — the everyday switches": "Controles de uso diario",
    "Saved ✓": "Guardado ✓",
    "CONNECTED": "CONECTADO",
    "BROKEN": "SIN CONEXIÓN",
    "DISMISS ✕": "CERRAR ✕",
    "NEXT →": "SIGUIENTE →",
    "FINISH →": "FINALIZAR →",
    "✓ correct": "✓ correcto",
    "your answer": "tu respuesta",
    "◉ AUTO-START: ON": "◉ INICIO AUTOMÁTICO: SÍ",
    "◉ AUTO-START: OFF": "◉ INICIO AUTOMÁTICO: NO",
    "⬇ DOWNLOADING… (one-time)": "⬇ DESCARGANDO… (solo una vez)",
    "⬇  DOWNLOADING… (one-time)": "⬇  DESCARGANDO… (solo una vez)",
    "🎙 WAKE WORD: ON": "🎙 PALABRA DE ACTIVACIÓN: SÍ",
    "🎙 WAKE WORD: OFF": "🎙 PALABRA DE ACTIVACIÓN: NO",
    "😴 SLEEP NOW": "😴 DORMIR AHORA",
    "👂 WAKE NOW": "👂 ACTIVAR AHORA",
    "☀ MORNING BRIEF: ON": "☀ RESUMEN MATUTINO: SÍ",
    "☀ MORNING BRIEF: OFF": "☀ RESUMEN MATUTINO: NO",
    "Testing…": "Probando…",
    "—": "—",
    "All three set. SAVE & APPLY reconnects; the conversation is kept.":
        "Las tres opciones están listas. GUARDAR Y APLICAR reconecta y conserva la conversación.",
    "MICROPHONE — what JARVIS hears you with": "MICRÓFONO — por donde JARVIS te escucha",
    "SPEAKERS — what JARVIS talks through": "ALTAVOCES — por donde JARVIS te habla",
    "Applying reconnects the session. Your conversation is kept.":
        "Al aplicar, se reconecta la sesión y se conserva la conversación.",
    "No file loaded — drop or click above to upload":
        "No hay ningún archivo. Suéltalo o haz clic arriba para cargarlo.",
    "A Friendly Assistant": "Un asistente amigable",
    "UI COLOUR — drag the handle": "COLOR DE LA INTERFAZ — arrastra el control",
    "No plugins found in /plugins.": "No se encontraron complementos en /plugins.",
    "Speak now…": "Habla ahora…",
    "Playing a tone…": "Reproduciendo un tono…",
    "Nothing stored yet.": "Todavía no hay nada guardado.",
    "found on this server — pick one above.":
        "encontrados en este servidor; elige uno arriba.",
    "available — pick one above.": "disponibles; elige uno arriba.",
    "— this can take a minute…": "— puede tardar un minuto…",
    "Key expires in": "El código caduca en",
    "[F4] Mute · [F11] Fullscreen": "[F4] Silenciar · [F11] Pantalla completa",
    "By FatihMakes": "Por FatihMakes",
    "Hold a key to talk instead of streaming the mic continuously.":
        "Mantén una tecla pulsada para hablar sin transmitir el micrófono continuamente.",
    "J.A.R.V.I.S AI Assistant": "Asistente de IA J.A.R.V.I.S.",
}

_ES_REVERSE = {translated: source for source, translated in _ES.items()}


def current_language() -> str:
    from memory.config_manager import get_language
    return get_language()


def tr(text: str, language: str | None = None) -> str:
    """Translate a known interface label; unknown text remains unchanged."""
    language = language or current_language()
    if language == "es":
        return _ES.get(text, text)
    if language == "en":
        return _ES_REVERSE.get(text, text)
    return text


def translate_widget_tree(root: QWidget, language: str) -> None:
    """Translate visible Qt labels while leaving widget data and behavior intact."""
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QAbstractButton)):
            text = widget.text()
            translated = tr(text, language)
            if translated != text:
                widget.setText(translated)
        if isinstance(widget, QLineEdit):
            text = widget.placeholderText()
            translated = tr(text, language)
            if translated != text:
                widget.setPlaceholderText(translated)
        tooltip = widget.toolTip()
        translated_tooltip = tr(tooltip, language)
        if translated_tooltip != tooltip:
            widget.setToolTip(translated_tooltip)
