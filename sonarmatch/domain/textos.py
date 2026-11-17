"""Utilidades de texto del dominio."""


def normalizar_nombre(nombre: str) -> str:
    """Forma canónica para comparar nombres y etiquetas: minúsculas, sin espacios extra."""
    return " ".join(nombre.casefold().split())


def lista_natural(elementos: list[str] | tuple[str, ...]) -> str:
    """'a', 'a y b', 'a, b y c'."""
    if not elementos:
        return ""
    if len(elementos) == 1:
        return elementos[0]
    return ", ".join(elementos[:-1]) + " y " + elementos[-1]
