# Contribuir

Gracias por considerar una contribución.

## Preparar el entorno

Requiere Python 3.11 o posterior. Desde la raíz del repositorio:

```console
python -m venv .venv
```

Activa el entorno virtual e instala el proyecto:

```console
python -m pip install -e ".[dev]"
```

## Ejecutar pruebas

```console
python -m unittest discover -s tests -v
ruff check src tests main.py
```

Las pruebas utilizan un catálogo SQLite sintético. No hace falta ni se debe
adjuntar una base real, archivos de audio, credenciales o perfiles personales.

## Enviar cambios

- Mantén el motor independiente de la interfaz de terminal.
- Añade o actualiza pruebas para cambios de comportamiento.
- Documenta los cambios en el esquema o los comandos cuando corresponda.
- No incluyas datos de terceros sin autorización ni datos personales.
- Antes de abrir un pull request, revisa `git status`, `git diff --check` y los
  archivos incluidos en el commit.
