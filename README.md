# qradar-to-mongodb

Script en Python para consultar eventos en IBM QRadar mediante AQL y guardar metricas por dominio en MongoDB.

## Requisitos

- Linux (Ubuntu, Debian, RHEL, Rocky o AlmaLinux)
- Python 3.10 o superior
- Acceso de red a QRadar API
- MongoDB accesible desde el host donde se ejecuta el script
- Dependencias Python listadas en `requirements.txt`

## Instalacion (Linux)

1. Instalar dependencias del sistema (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ca-certificates
```

1. Crear y activar entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

1. Instalar dependencias:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

1. Crear archivo de entorno a partir de ejemplo:

```bash
cp .env.example .env
```

1. Completar variables en `.env`.

## Variables de entorno

| Variable | Descripcion | Ejemplo |
| --- | --- | --- |
| `QRADAR_IP` | IP o hostname de QRadar | `10.10.10.10` |
| `QRADAR_TOKEN` | Token SEC para API de QRadar | `xxxxxxxx` |
| `MONGO_URI` | URI completa de conexion a MongoDB (prioridad alta) | `mongodb://user:pass@localhost:27017/?authSource=admin` |
| `MONGO_HOST` | Host MongoDB (si no usas `MONGO_URI`) | `localhost` |
| `MONGO_PORT` | Puerto MongoDB (si no usas `MONGO_URI`) | `27017` |
| `MONGO_USER` | Usuario MongoDB (opcional) | `qradar_user` |
| `MONGO_PASSWORD` | Password MongoDB (opcional) | `replace-me` |
| `MONGO_AUTH_SOURCE` | Base de autenticacion de MongoDB | `admin` |
| `MONGO_PARAMS` | Parametros extra URI (sin `?`) | `tls=true&retryWrites=true` |
| `MONGO_DB` | Nombre de base de datos | `qradar_metrics` |
| `MONGO_COLLECTION` | Nombre de coleccion destino | `eps_por_cliente` |
| `MINUTOS_INTERVALO` | Ventana de consulta AQL en minutos | `60` |
| `REQUEST_TIMEOUT` | Timeout HTTP para QRadar en segundos | `30` |
| `POLL_INTERVAL_SECONDS` | Espera entre consultas de estado | `2` |
| `MAX_POLL_ATTEMPTS` | Maximo de intentos de polling | `120` |
| `DEBUG_EXPORT_TXT` | Exporta salida de prueba a TXT (`true`/`false`) | `false` |
| `DEBUG_TXT_FILE` | Nombre del archivo TXT de debug | `debug_qradar_output.txt` |

Prioridad de conexion MongoDB:

- Si `MONGO_URI` existe, el script usa esa URI.
- Si `MONGO_URI` no existe, construye la URI con `MONGO_HOST`, `MONGO_PORT`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_AUTH_SOURCE` y `MONGO_PARAMS`.

## Regla de EPS

- El EPS se calcula sobre la ventana real: `MINUTOS_INTERVALO * 60`.
- El resultado se guarda como entero (sin decimales).
- Si el promedio da `0`, se fuerza a `1` por requerimiento operativo.

## Formato de documento en MongoDB

Cada dominio (cliente) se guarda como un documento con esta estructura:

```json
{
    "cliente": "ACME",
    "eventos_totales": 7200,
    "eps": 2,
    "fecha": "2026-03-20T14:35:10.123456",
    "dia": "2026-03-20",
    "hora": "14:00"
}
```

Tipos almacenados:

- `cliente`: string
- `eventos_totales`: int
- `eps`: int
- `fecha`: BSON Date en MongoDB (en el ejemplo se muestra como texto ISO solo para lectura)
- `dia`: string
- `hora`: string

## Prueba con TXT (opcional)

Para validar facilmente la salida antes de productivo:

1. En `.env`, configurar:

```bash
DEBUG_EXPORT_TXT=true
DEBUG_TXT_FILE=debug_qradar_output.txt
```

1. Ejecutar el script y revisar el archivo generado.

Para productivo, dejar `DEBUG_EXPORT_TXT=false`.

## Ejecucion

```bash
python3 qradar-to-mongodb.py
```

## Linux

La guia detallada de despliegue Linux esta en `LINUX_SETUP.md`.

## Flujo

1. Construye una consulta AQL por dominio.
2. Lanza la busqueda Ariel en QRadar.
3. Hace polling hasta obtener estado `COMPLETED`.
4. Calcula EPS por dominio.
5. Inserta documentos en MongoDB.

## Estructura del proyecto

```text
.
|-- qradar-to-mongodb.py
|-- requirements.txt
|-- .env.example
|-- .gitignore
|-- LINUX_SETUP.md
|-- CHANGELOG.md
`-- .github/
    `-- ISSUE_TEMPLATE/
```

## Contribuciones

- Usa las plantillas de Issues para reportar bugs o proponer mejoras.
- Mantener cambios pequenos y con contexto claro en el PR.
