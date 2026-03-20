# Linux Setup

Guia para ejecutar qradar-to-mongodb en servidores Linux.

## 1. Dependencias del sistema

Para Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ca-certificates
```

Para RHEL/Rocky/AlmaLinux:

```bash
sudo dnf install -y python3 python3-pip ca-certificates
```

## 2. Crear entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Instalar dependencias Python

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con valores reales.

## 5. Ejecutar manualmente

```bash
python3 qradar-to-mongodb.py
```

## 6. Variables requeridas

- `QRADAR_IP`
- `QRADAR_TOKEN`
- `MONGO_URI` o `MONGO_HOST`
- `MONGO_DB`
- `MONGO_COLLECTION`

## 7. Variables opcionales

- `MINUTOS_INTERVALO` (default: `60`)
- `REQUEST_TIMEOUT` (default: `30` segundos)
- `POLL_INTERVAL_SECONDS` (default: `2`)
- `MAX_POLL_ATTEMPTS` (default: `120`)
- `RUN_CONTINUOUS` (default: `false`)
- `RUN_INTERVAL_SECONDS` (default: `MINUTOS_INTERVALO * 60`)

## 8. Ejecucion continua

En `.env` habilita:

```dotenv
RUN_CONTINUOUS=true
RUN_INTERVAL_SECONDS=3600
```

Con eso el script se mantiene en bucle y ejecuta una consulta por cada intervalo.

Para dejarlo siempre activo tras reinicio del servidor, usar systemd:

```bash
sudo cp deploy/systemd/qradar-to-mongodb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable qradar-to-mongodb
sudo systemctl start qradar-to-mongodb
```

### Pasos exactos recomendados (ruta /opt)

```bash
cd /opt/qradar-to-mongodb
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env
sudo cp /opt/qradar-to-mongodb/deploy/systemd/qradar-to-mongodb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable qradar-to-mongodb
sudo systemctl start qradar-to-mongodb
```

Validaciones previas importantes:

```bash
ls -l /opt/qradar-to-mongodb/.venv/bin/python
ls -l /opt/qradar-to-mongodb/.env
ls -l /opt/qradar-to-mongodb/deploy/systemd/qradar-to-mongodb.service
```

Comandos utiles:

```bash
sudo systemctl status qradar-to-mongodb
sudo journalctl -u qradar-to-mongodb -f
```

Si falla el arranque, revisar:

- Usuario/grupo del servicio (`User=` y `Group=`) existentes en el sistema.
- Rutas correctas en `WorkingDirectory`, `EnvironmentFile` y `ExecStart`.
- Credenciales MongoDB validas en `.env`.
- Permisos de lectura sobre `.env` y ejecucion sobre `.venv/bin/python`.

## 9. Recomendaciones operativas Linux

- Crear usuario de servicio sin privilegios de root.
- Proteger `.env` con permisos restrictivos: `chmod 600 .env`.
- Evitar `verify=False` en ambientes productivos. Se recomienda configurar TLS con certificados validos en QRadar.
- Si se requiere ejecucion periodica, usar systemd timer o cron.

## 10. Instalador automatico

Para evitar errores manuales, ejecutar:

```bash
cd /opt/qradar-to-mongodb
chmod +x scripts/install_service.sh
sudo ./scripts/install_service.sh
```

El script muestra menu para elegir instalacion o desinstalacion segura.

Tambien puedes usar modo no interactivo:

```bash
sudo ./scripts/install_service.sh install
sudo ./scripts/install_service.sh uninstall
# Equivalent short options:
sudo ./scripts/install_service.sh 1
sudo ./scripts/install_service.sh 2
```

Este script:

- Prepara `.venv` e instala dependencias.
- Crea `.env` desde `.env.example` si falta.
- Ajusta permisos de `.env`.
- Crea/actualiza el servicio systemd.
- Habilita y reinicia el servicio.

Parametros opcionales:

```bash
sudo APP_DIR=/opt/qradar-to-mongodb SERVICE_USER=<linux_user> SERVICE_GROUP=<linux_group> ./scripts/install_service.sh install
```
