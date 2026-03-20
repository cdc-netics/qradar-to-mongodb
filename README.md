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
| `RUN_CONTINUOUS` | Ejecuta el script en bucle continuo | `true` |
| `RUN_INTERVAL_SECONDS` | Espera entre corridas en modo continuo | `3600` |
| `DEBUG_EXPORT_TXT` | Exporta salida de prueba a TXT (`true`/`false`) | `false` |
| `DEBUG_TXT_FILE` | Nombre del archivo TXT de debug | `debug_qradar_output.txt` |

Prioridad de conexion MongoDB:

- Si `MONGO_USER` y `MONGO_PASSWORD` estan definidos, el script construye la URI con `MONGO_HOST`, `MONGO_PORT`, `MONGO_AUTH_SOURCE` y `MONGO_PARAMS`.
- Si `MONGO_USER` y `MONGO_PASSWORD` estan vacios, el script usa `MONGO_URI`.

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

Comportamiento de ejecucion:

- Si `RUN_CONTINUOUS=false`, ejecuta una sola vez.
- Si `RUN_CONTINUOUS=true`, ejecuta en bucle y espera `RUN_INTERVAL_SECONDS` entre corridas.
- Si no defines `RUN_INTERVAL_SECONDS`, usa `MINUTOS_INTERVALO * 60`.

## Linux

La guia detallada de despliegue Linux esta en `LINUX_SETUP.md`.

## Levantar Servicio En Linux (Paso A Paso)

Ejemplo asumiendo proyecto en `/opt/qradar-to-mongodb`.

1. Preparar entorno y dependencias:

```bash
cd /opt/qradar-to-mongodb
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

1. Editar `.env` con tus valores reales (QRadar, Mongo y scheduler).

1. Validar que las rutas esperadas existen:

```bash
ls -l /opt/qradar-to-mongodb/.venv/bin/python
ls -l /opt/qradar-to-mongodb/.env
ls -l /opt/qradar-to-mongodb/deploy/systemd/qradar-to-mongodb.service
```

1. Instalar y activar el servicio systemd:

```bash
sudo cp /opt/qradar-to-mongodb/deploy/systemd/qradar-to-mongodb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable qradar-to-mongodb
sudo systemctl start qradar-to-mongodb
```

1. Verificar estado y logs:

```bash
sudo systemctl status qradar-to-mongodb
sudo journalctl -u qradar-to-mongodb -f
```

Si no inicia, revisar:

- Que el usuario del servicio exista (`User=` y `Group=` en el .service).
- Que `WorkingDirectory` y `ExecStart` apunten a `/opt/qradar-to-mongodb`.
- Que `.env` tenga credenciales validas de MongoDB.

## Instalacion Automatizada (Script .sh)

Tambien puedes automatizar todo con el instalador:

```bash
cd /opt/qradar-to-mongodb
chmod +x scripts/install_service.sh
sudo ./scripts/install_service.sh
```

Al ejecutarlo sin parametros muestra menu para elegir:

- `Install / Update service`
- `Repair runtime/service (safe)`
- `Safe uninstall service`

Modo no interactivo:

```bash
sudo ./scripts/install_service.sh install
sudo ./scripts/install_service.sh repair
sudo ./scripts/install_service.sh uninstall
# Equivalent short options:
sudo ./scripts/install_service.sh 1
sudo ./scripts/install_service.sh 2
sudo ./scripts/install_service.sh 3
```

`repair` corrige automaticamente el caso mas comun de falla:

- Repara permisos/owner de `.env` para el usuario del servicio.
- Reescribe el unit file de systemd con rutas correctas.
- Ejecuta `daemon-reload`, `enable` y `restart`.

Que hace automaticamente:

- Crea/actualiza `.venv`.
- Instala dependencias desde `requirements.txt`.
- Crea `.env` desde `.env.example` si no existe.
- Genera `/etc/systemd/system/qradar-to-mongodb.service`.
- Ejecuta `daemon-reload`, `enable` y `restart` del servicio.

Si necesitas valores custom:

```bash
sudo APP_DIR=/opt/qradar-to-mongodb SERVICE_USER=<linux_user> SERVICE_GROUP=<linux_group> ./scripts/install_service.sh install
```

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
