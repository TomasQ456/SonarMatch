"""Verificación de calidad de SonarMatch (multiplataforma). Falla si cualquier paso falla.

Uso: python scripts/check.py [--rapido]   (--rapido omite las pruebas marcadas como slow)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable
UMBRAL = "80"
FRONTEND = [
    "sonarmatch/adapters/inbound/streamlit_app.py",
    "sonarmatch/adapters/inbound/ui/*",
]
NOQA = re.compile(
    r"#\s*(?:noqa(?::\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?|type:\s*ignore(?:\[[^\]]*\])?)"
    r"(?P<resto>.*)$"
)
MIN_JUSTIFICACION = 5
CLAVE_LASTFM = re.compile(r"LASTFM_API_KEY\s*=\s*['\"]?[0-9a-f]{32}")


def ejecutar(nombre: str, comando: list[str]) -> tuple[bool, str]:
    print(f"\n=== {nombre} ===\n$ {' '.join(comando)}", flush=True)
    proc = subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, check=False)  # noqa: S603 — comandos fijos definidos en este script, sin entrada externa
    salida = proc.stdout + proc.stderr
    print(salida, flush=True)
    return proc.returncode == 0, salida


def archivos_python() -> list[Path]:
    ignorar = {".venv", "venv", ".git", "data", "node_modules", "build", "dist"}
    return [p for p in RAIZ.rglob("*.py") if not ignorar.intersection(p.relative_to(RAIZ).parts)]


def revisar_noqa() -> bool:
    """Cada # noqa / type: ignore debe llevar una justificación en la misma línea."""
    print("\n=== noqa / type: ignore justificados ===", flush=True)
    malos = []
    for ruta in archivos_python():
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            m = NOQA.search(linea)
            if m and len(m.group("resto").strip(" -—:")) < MIN_JUSTIFICACION:
                malos.append(f"{ruta.relative_to(RAIZ)}:{n}: {linea.strip()}")
    print("\n".join(malos) or "OK")
    return not malos


def revisar_secretos() -> bool:
    print("\n=== secretos ===", flush=True)
    problemas = []
    git = shutil.which("git")
    if git:
        rastreados = subprocess.run(  # noqa: S603 — git con argumentos fijos
            [git, "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=False
        ).stdout.split()
        if ".env" in rastreados:
            problemas.append(".env está versionado")
        for nombre in rastreados:
            ruta = RAIZ / nombre
            texto = ruta.suffix in {".py", ".md", ".toml", ".txt", ".yml", ".example"}
            if (
                texto
                and ruta.exists()
                and CLAVE_LASTFM.search(ruta.read_text(encoding="utf-8", errors="ignore"))
            ):
                problemas.append(f"posible clave de Last.fm en {nombre}")
    print("\n".join(problemas) or "OK")
    return not problemas


def cobertura_area(nombre: str, args: list[str]) -> bool:
    ok, salida = ejecutar(
        f"cobertura {nombre}", [PY, "-m", "coverage", "report", f"--fail-under={UMBRAL}", *args]
    )
    if not ok and "No data to report" in salida:
        print(f"(sin código en el área {nombre}: se omite)")
        return True
    return ok


def main() -> int:
    rapido = "--rapido" in sys.argv
    resultados: dict[str, bool] = {}
    resultados["ruff format"] = ejecutar(
        "ruff format", [PY, "-m", "ruff", "format", "--check", "."]
    )[0]
    resultados["ruff check"] = ejecutar("ruff check", [PY, "-m", "ruff", "check", "."])[0]
    resultados["mypy"] = ejecutar("mypy", [PY, "-m", "mypy", "--strict", "sonarmatch"])[0]
    # Con el intérprete actual (no el script lint-imports, cuyo shebang puede apuntar a otro venv).
    lint = "from importlinter.cli import lint_imports_command as c; raise SystemExit(c())"
    resultados["import-linter"] = ejecutar("import-linter", [PY, "-c", lint])[0]
    resultados["noqa"] = revisar_noqa()
    resultados["secretos"] = revisar_secretos()
    pytest = [PY, "-m", "pytest", "--cov=sonarmatch", "--cov-branch", f"--cov-fail-under={UMBRAL}"]
    if rapido:
        pytest += ["-m", "not slow"]
    resultados["pytest + cobertura total"] = ejecutar("pytest", pytest)[0]
    resultados["cobertura backend"] = cobertura_area("backend", [f"--omit={','.join(FRONTEND)}"])
    resultados["cobertura frontend"] = cobertura_area(
        "frontend", [f"--include={','.join(FRONTEND)}"]
    )
    print("\n=== Resumen ===")
    for nombre, ok in resultados.items():
        print(f"{'OK ' if ok else 'FALLA'}  {nombre}")
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
