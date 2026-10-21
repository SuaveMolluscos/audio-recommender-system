# Esquema de base de datos

El programa consume una base SQLite existente en modo de solo lectura. No
crea ni modifica tablas. Los datos se quedan en la máquina local.

## Tablas requeridas

### `songs`

| Columna | Uso |
|---|---|
| `id` | Identificador entero y estable |
| `title` | Título que se presenta en la consola |
| `artist_display` | Nombre visible del artista |
| `genre` | Señal contextual; la columna debe existir y el valor puede ser `NULL` |
| `year` | Año; la columna debe existir, el valor puede ser `NULL` y actualmente no afecta el ranking |
| `features_json` | JSON con vectores acústicos; puede ser `NULL` |
| `tempo_mean`, `tempo_std` | Tempo |
| `energy_rms_mean`, `energy_rms_std` | Energía RMS |
| `energy_norm_peak_mean`, `energy_norm_peak_std` | Pico normalizado |
| `acousticness_zcr_mean`, `acousticness_zcr_std` | Feature calculada por el analizador |
| `brightness_mean`, `brightness_std` | Brillo espectral |
| `zcr_mean`, `zcr_std` | Zero-crossing rate |
| `rolloff_mean`, `rolloff_std` | Rolloff espectral |
| `onset_mean`, `onset_std` | Onset |
| `rhythm_mean`, `rhythm_std` | Feature de ritmo |

Todas las columnas listadas deben existir. Los campos escalares pueden ser
`NULL`; se imputan con la media de la biblioteca durante la normalización.
Features escalares sin variación aportan un vector cero. Los vectores ausentes,
mal formados o con longitud incorrecta se ignoran y se imputan como cero tras
la normalización.

`features_json` sigue esta forma para incluir vectores (cada vector debe tener
el tamaño indicado):

```json
{
  "statistics": {
    "mfcc_mean": {"mean": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]},
    "chroma_mean": {"mean": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]},
    "tonnetz_mean": {"mean": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]},
    "spectral_contrast_mean": {"mean": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}
  }
}
```

Cada arreglo debe tener exactamente 13 valores MFCC, 12 chroma, 6 tonnetz o 7
de contraste espectral. Los valores del ejemplo son ficticios y solo muestran
la estructura esperada.

### `tags`

| Columna | Uso |
|---|---|
| `id` | Identificador de etiqueta |
| `name` | Etiqueta |

### `song_tags`

| Columna | Uso |
|---|---|
| `song_id` | Referencia a `songs.id` |
| `tag_id` | Referencia a `tags.id` |
| `weight` | Peso numérico de la etiqueta; `NULL` se trata como 1 |

La tabla `song_tags` se une con `tags` usando `tag_id` y puede tener varias
filas por canción.

## Generar un catálogo de prueba

Las pruebas del repositorio crean un esquema mínimo con datos sintéticos en
memoria. No se incluye un catálogo real ni un generador de metadatos de
canciones en este proyecto.
