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
- `MONGO_URI`
- `MONGO_DB`
- `MONGO_COLLECTION`

## 7. Variables opcionales

- `MINUTOS_INTERVALO` (default: `60`)
- `REQUEST_TIMEOUT` (default: `30` segundos)
- `POLL_INTERVAL_SECONDS` (default: `2`)
- `MAX_POLL_ATTEMPTS` (default: `120`)

## 8. Recomendaciones operativas Linux

- Crear usuario de servicio sin privilegios de root.
- Proteger `.env` con permisos restrictivos: `chmod 600 .env`.
- Evitar `verify=False` en ambientes productivos. Se recomienda configurar TLS con certificados validos en QRadar.
- Si se requiere ejecucion periodica, usar systemd timer o cron.
