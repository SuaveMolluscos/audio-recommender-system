# Audio Recommender System

[![Tests](https://github.com/SuaveMolluscos/audio-recommender-system/actions/workflows/tests.yml/badge.svg)](https://github.com/SuaveMolluscos/audio-recommender-system/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Recomendador musical local basado en contenido acústico, etiquetas y afinidad
por artista y género. Es el segundo componente de mi pipeline personal: consume
la base SQLite creada por
[Audio Data Pipeline](https://github.com/SuaveMolluscos/audio-data-pipeline),
un crawler/ETL independiente que recopila y normaliza metadatos y puede analizar
previews de audio.

```text
Audio Data Pipeline (crawler + análisis opcional)
                 │
                 │ data/tracks.db (SQLite local)
                 ▼
Audio Recommender System (búsqueda + perfil + recomendaciones)
```

Este repositorio **no incluye música, metadatos de terceros ni una base de
datos**. Ambos proyectos son herramientas separadas: el crawler obtiene y
prepara el catálogo; el recomendador lee ese catálogo en modo de solo lectura
y guarda tus calificaciones en un archivo local separado.

## Requisitos

- Python 3.11 o posterior
- Una base SQLite creada por Audio Data Pipeline (o compatible con el
  [esquema documentado](docs/database-schema.md))
- NumPy, pandas y Rich (se instalan con el proyecto)

Para recomendaciones que aprovechen las características acústicas, instala en
el crawler su extra opcional de audio y ejecuta análisis de previews. Sin esas
features, el recomendador puede tener menos evidencia para ordenar canciones.
El acceso a las APIs, las previews y el análisis dependen de la configuración
y disponibilidad del crawler y de los términos de cada proveedor.

## Instalación

Desde la raíz del repositorio:

```console
python -m venv .venv
```

Activa el entorno virtual y ejecuta:

```console
python -m pip install -e ".[dev]"
```

En Windows PowerShell, la activación se hace con:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Uso

### Integración con Audio Data Pipeline

El crawler y el recomendador se instalan y ejecutan por separado. La conexión
entre ellos es el archivo SQLite del crawler; no hace falta copiar el catálogo
al repositorio del recomendador ni instalar ambos paquetes en el mismo entorno
virtual.

1. Sigue las instrucciones de instalación del
   [crawler](https://github.com/SuaveMolluscos/audio-data-pipeline).
2. Desde la carpeta del crawler, crea o completa su base:

   ```powershell
   audio-seeds --db data/tracks.db enqueue --categories pop rock
   audio-crawler --db data/tracks.db --workers 2
   ```

   El análisis de audio es opcional en el crawler. Para habilitarlo, instala allí
   el extra `audio` según el README de ese proyecto.
3. Desde este repositorio, activa su propio entorno e inicia el recomendador
   apuntando a **la misma base**:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python main.py --database "C:\ruta\al\audio-data-pipeline\data\tracks.db"
   ```

   Si no pasas `--database`, la interfaz te pedirá la ruta.
4. Para comprobar que el archivo tiene las tablas y columnas esperadas, ejecuta:

   ```powershell
   audio-recommender --database "C:\ruta\al\audio-data-pipeline\data\tracks.db" check
   ```

El esquema actual del crawler contiene las tablas `songs`, `tags` y
`song_tags`, las features acústicas escalares y `features_json` que consume este
proyecto. El contrato que valida el recomendador está descrito en
[docs/database-schema.md](docs/database-schema.md). Si el crawler cambia su
esquema, `check` indicará las columnas que faltan; actualiza el contrato o crea
una exportación compatible antes de recomendar.

**Importante:** la ruta anterior es un ejemplo. Sustituye `C:\ruta\al\...` por
la ubicación real de tu checkout del crawler. El crawler debe terminar sus
operaciones antes de que ejecutes `check` o uses la base para evitar leer un
catálogo que todavía se está actualizando.

### Interfaz interactiva de terminal

Inicia el menú con:

```console
python main.py
```

El programa solicitará la ruta al archivo SQLite, validará el catálogo y
mostrará un menú visual con paneles, estadísticas y tablas para buscar
canciones, guardar calificaciones y generar recomendaciones. También puedes
pasar la ruta directamente:

```console
python main.py --database "C:\ruta\autorizada\tracks.sqlite"
```

El perfil local se guarda en `data/user_profile.json` dentro de este
repositorio; contiene tus calificaciones y **no se comparte con el crawler**.
Puedes cambiarlo con `--profile`, o iniciar la interfaz usando el comando instalado
`audio-recommender-ui --database "C:\ruta\autorizada\tracks.sqlite"`.

### Comandos directos

Proporciona la ruta de la base con `--database`. La aplicación abre la base en
modo de solo lectura. El perfil personal se guarda en `data/user_profile.json`
por defecto; ese archivo está excluido de Git. Puedes elegir otra ruta con
`--profile`.

```console
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" check
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" search --title "Beyonce"
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" search --artist "Daft Punk"
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" rate 123 9
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" ratings
audio-recommender --database "C:\ruta\autorizada\tracks.sqlite" recommend --top 20
```

También se puede ejecutar sin instalar el punto de entrada:

```console
python -m audio_recommender --database "C:\ruta\autorizada\tracks.sqlite" check
```

`rate` recibe el ID de una canción y una calificación de 0 a 10. Se necesitan
al menos tres canciones calificadas para generar recomendaciones. El motor
puede abstenerse cuando la evidencia no supera sus umbrales configurados.

## Arquitectura

Consulta [docs/architecture.md](docs/architecture.md) para el flujo de datos y
las responsabilidades de cada módulo, y el [contrato SQLite](docs/database-schema.md)
para preparar una base compatible.

```text
src/audio_recommender/
├── __init__.py       # API y versión del paquete
├── __main__.py       # python -m audio_recommender
├── cli.py            # comandos y presentación en consola
├── database.py       # lectura, validación del esquema y búsqueda SQLite
├── engine.py         # features, similitud, ranking y explicaciones
└── profile.py        # carga y guardado del perfil personal
tests/
└── test_recommender.py
```

Las pautas para preparar cambios y ejecutar validaciones están en
[CONTRIBUTING.md](CONTRIBUTING.md).

El motor combina vecinos cercanos sobre características de audio, un perfil de
tags con preferencias positivas y negativas, afinidad de metadatos, un filtro
de confianza y un límite de canciones por artista. La puntuación es una señal
de ranking, no una probabilidad calibrada.

## Pruebas

Las pruebas usan una base de datos SQLite sintética generada en memoria; no
requieren ni descargan catálogos reales:

```console
python -m unittest discover -s tests -v
ruff check src tests main.py
```

La integración continua ejecuta estas pruebas en Windows y Linux con Python
3.11–3.14.

## Limitaciones

- La calidad del ranking todavía no se ha medido con una evaluación offline
  independiente. Las puntuaciones y la confianza son señales heurísticas.
- El motor requiere features de audio y metadatos compatibles; no analiza
  archivos de audio ni crea el catálogo.
- La búsqueda normaliza texto en memoria y está pensada para catálogos locales,
  no para servicios de búsqueda distribuidos a gran escala.

## Datos y publicación

- No agregues archivos SQLite, audio, exportaciones de catálogos ni perfiles
  personales al repositorio.
- La base se comparte localmente entre tus dos proyectos; no se versiona ni se
  sube automáticamente a GitHub.
- El `.gitignore` excluye bases SQLite comunes y perfiles locales. Revisa
  `git status` y el contenido de los commits antes de publicar.
- Usa únicamente datos que tengas derecho a procesar. Que un dato sea
  descriptivo no significa automáticamente que sus condiciones de
  redistribución permitan publicarlo.
- Para probar o mostrar el proyecto, usa datos sintéticos o datos con una
  licencia que permita expresamente ese uso.

## Licencia

Este código se distribuye bajo MIT. La licencia del código no concede derechos
sobre catálogos, grabaciones, letras, portadas u otros datos externos.
