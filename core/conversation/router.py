"""Router de intenciones: decide el camino del mensaje del usuario.

Responsabilidad única: clasificar un mensaje como "conversacional" o "trabajo"
para enrutar al fast-path (una sola llamada al modelo, sin parser ni reflexión)
o al ciclo completo de agente.

La heurística es deliberadamente CONSERVADORA: ante cualquier duda, asume
"trabajo" para no perder potencial uso de tools. Sólo marca conversacional
cuando hay alta confianza.
"""

from __future__ import annotations

import re


# Patrones inequívocamente conversacionales (saludos, acknowledgements)
_CONVERSATIONAL_PATTERNS = [
    re.compile(r"^(hola|hi|hey|buenos?\s+d[íi]as?|buenas?\s+(tardes?|noches?))[!.\s]*$", re.IGNORECASE),
    re.compile(r"^(gracias|thanks?|thx|ok|okay|vale|perfecto|excelente|genial|bien)[!.\s]*$", re.IGNORECASE),
    re.compile(r"^(adi[óo]s|chao|chau|nos\s+vemos|hasta\s+(luego|pronto|ma[ñn]ana))[!.\s]*$", re.IGNORECASE),
    re.compile(r"^(s[íi]|no|tal\s+vez|quiz[áa]s?|claro|por\s+supuesto)[!.\s]*$", re.IGNORECASE),
    re.compile(r"^(c[óo]mo\s+est[áa]s|qu[ée]\s+tal|how\s+are\s+you)[?!.\s]*$", re.IGNORECASE),
]

# Palabras que indican intención de acción → NO es conversacional
_ACTION_KEYWORDS = {
    # Lectura/análisis
    "lee", "leer", "lea", "leé", "leeme", "leéme",
    "analiza", "analizar", "analice", "analícame",
    "revisa", "revisar", "revise", "inspecciona", "inspeccionar",
    "muestra", "mostrar", "muéstrame", "ver", "veme",
    "lista", "listar", "liste", "listame", "lístame",
    "busca", "buscar", "busque", "encuentra", "encontrar",
    # Escritura
    "crea", "crear", "cree", "créame", "créeme",
    "escribe", "escribir", "escriba", "escríbeme",
    "modifica", "modificar", "modifique",
    "edita", "editar", "edite",
    "actualiza", "actualizar", "actualice",
    "elimina", "eliminar", "elimine", "borra", "borrar",
    # Ejecución
    "ejecuta", "ejecutar", "ejecute", "corre", "correr", "corra",
    "instala", "instalar", "instale",
    # Generación
    "genera", "generar", "genere", "implementa", "implementar",
    "documenta", "documentar", "refactoriza", "refactorizar",
    # Sustantivos técnicos
    "archivo", "archivos", "directorio", "directorios", "carpeta", "carpetas",
    "comando", "script", "código", "función", "clase",
    "workspace", "proyecto", "repo", "repositorio",
    # English
    "read", "analyze", "review", "show", "list", "find", "search",
    "create", "write", "modify", "edit", "update", "delete", "remove",
    "execute", "run", "install", "generate", "implement",
    "file", "directory", "folder", "command", "script", "code",
    "project", "repo", "repository", "workspace",
}

# Umbral de longitud: mensajes más cortos sin keywords de acción → conversacional
_SHORT_MESSAGE_THRESHOLD = 20


class ConversationRouter:
    """Clasifica mensajes como conversacionales o de trabajo."""

    @staticmethod
    def is_conversational(message: str) -> bool:
        """Decide si un mensaje es puramente conversacional.

        Returns:
            True si el mensaje parece ser solo conversación (saludo,
            agradecimiento, etc.) y NO requiere acceso a tools.
            False ante cualquier duda — el ciclo completo del agente lo
            resolverá correctamente.
        """
        msg = message.strip()
        if not msg:
            return False

        # 1) Match exacto contra patrones conversacionales conocidos
        for pattern in _CONVERSATIONAL_PATTERNS:
            if pattern.match(msg):
                return True

        # 2) Si tiene cualquier keyword de acción → NO es conversacional
        words = set(re.findall(r"\b\w+\b", msg.lower()))
        if words & _ACTION_KEYWORDS:
            return False

        # 3) Si es corto (sin signos de pregunta/exclamación complejos)
        #    y sin keywords de acción → asumimos conversacional
        if len(msg) <= _SHORT_MESSAGE_THRESHOLD:
            return True

        # 4) Por defecto: tratar como trabajo (conservador)
        return False
