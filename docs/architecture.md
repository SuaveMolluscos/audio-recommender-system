# Arquitectura

## Límites del sistema

La aplicación es una herramienta local, de una sola persona y de línea de
comandos. No descarga música, no se conecta a servicios externos y no almacena
el catálogo. La base existente se abre en modo SQLite de solo lectura; las
calificaciones se guardan aparte en un JSON local excluido de Git.

## Flujo

```text
CLI (cli.py)
  ├── búsqueda/validación del catálogo ──> SQLite en solo lectura (database.py)
  ├── calificaciones ────────────────────> JSON local (profile.py)
  └── recomendación ─────────────────────> motor (engine.py)
                                              ├── canciones y tags (database.py)
                                              ├── normalización de features
                                              ├── predicción k-NN y afinidades
                                              ├── filtro por evidencia
                                              └── ranking y diversificación
```

## Responsabilidades

- `database.py`: normaliza cadenas para búsqueda, valida que el esquema esté
  completo y expone operaciones de lectura. Errores del archivo o del esquema
  se comunican de forma explícita.
- `profile.py`: valida las calificaciones `song_id -> 0..10`, gestiona JSON
  privado y reemplaza el perfil de forma atómica para evitar archivos
  parcialmente escritos.
- `engine.py`: transforma los campos acústicos escalares y vectoriales,
  calcula similitud coseno con canciones calificadas, perfila preferencias por
  tags/artista/género, penaliza similitud con elementos rechazados, aplica
  umbrales de abstención y limita canciones por artista.
- `cli.py`: coordina comandos (`check`, `search`, `rate`, `ratings`,
  `recommend`) y convierte errores de entrada o de datos en mensajes visibles
  para la persona usuaria.

## Decisiones importantes

- **Datos separados del código:** la base, los datos de audio y el perfil no
  forman parte de la distribución ni de los tests.
- **Solo lectura:** los comandos de catálogo no escriben en la base original.
- **Abstención conservadora:** si falta evidencia o no se cumplen los umbrales,
  el motor puede devolver una lista vacía.
- **Puntuación interpretable, no probabilidad:** el score híbrido sirve para
  ordenar resultados; `confidence` es una heurística y no una probabilidad
  calibrada.
- **Persistencia sencilla:** JSON es suficiente para un perfil local pequeño;
  la base se considera una fuente externa ya preparada por otro proceso.

## Extensiones sugeridas

1. Extraer umbrales y pesos a una configuración versionada después de medir su
   impacto en un conjunto de evaluación permitido.
2. Añadir métricas de ranking y evaluación offline con un dataset sintético o
   autorizado.
3. Incorporar una interfaz web solo si se define antes dónde y con qué licencia
   se pueden almacenar y servir los datos.
