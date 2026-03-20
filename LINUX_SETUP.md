# Guía de Despliegue en Linux (qradar-to-mongodb)

Esta guía detalla los pasos para instalar y ejecutar el sincronizador de QRadar a MongoDB en servidores Linux (Ubuntu, Debian, RHEL, Rocky, AlmaLinux).

---

## 🏗️ Opción 1: Instalación Automatizada (Recomendado)

El proyecto incluye un script de gestión que automatiza todo el proceso. **Es el método más seguro** para evitar errores de permisos o rutas.

### 1. Preparar el directorio
Se recomienda usar `/opt` para aplicaciones persistentes:
```bash
sudo mkdir -p /opt/qradar-to-mongodb
sudo chown $USER:$USER /opt/qradar-to-mongodb
cd /opt/qradar-to-mongodb
# (Copie aquí los archivos del proyecto)
```

### 2. Ejecutar el instalador
```bash
chmod +x scripts/install_service.sh
sudo ./scripts/install_service.sh install
```
El script realizará:
- Creación del entorno virtual (`.venv`).
- Instalación de dependencias (`requirements.txt`).
- Creación del archivo de configuración `.env` (si no existe).
- Generación y activación del servicio en `systemd`.

---

## 🛠️ Opción 2: Instalación Manual

Si prefiere tener control total sobre cada paso:

### 1. Dependencias del sistema
**Debian / Ubuntu:**
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip ca-certificates
```
**RHEL / Rocky / AlmaLinux:**
```bash
sudo dnf install -y python3 python3-pip ca-certificates
```

### 2. Entorno Virtual y Dependencias Python
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configuración del Entorno
Copie el ejemplo y edite los valores:
```bash
cp .env.example .env
nano .env  # Inserte su Token SEC de QRadar y URI de MongoDB
```

### 4. Configurar como Servicio (systemd)
Copie el archivo de unidad y recargue el daemon:
```bash
sudo cp deploy/systemd/qradar-to-mongodb.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable qradar-to-mongodb
sudo systemctl start qradar-to-mongodb
```

---

## 🔍 Comandos útiles para Operaciones

### Ver estado y Logs
```bash
# Estado en tiempo real
sudo systemctl status qradar-to-mongodb

# Ver logs (muy útil si el script falla al iniciar)
sudo journalctl -u qradar-to-mongodb -f -n 100
```

### Reparar Instalación
Si el servicio falla por problemas de permisos en el archivo `.env` o tras mover los archivos de carpeta, use la opción de reparación:
```bash
sudo ./scripts/install_service.sh repair
```

---

## 🛡️ Mejores Prácticas Operativas

1.  **Seguridad**: Configure el archivo `.env` con permisos restrictivos (`chmod 600 .env`) para que solo el propietario pueda leer los tokens.
2.  **Tokens**: Use un Token SEC en QRadar que tenga permisos limitados solo a las API de búsqueda Ariel.
3.  **Monitoreo**: El script guarda una marca de tiempo `fecha` en cada documento en MongoDB. Puede crear alertas si no se reciben datos nuevos en el intervalo esperado.
4.  **Actualizaciones**: Para actualizar el código, simplemente haga un `git pull` (o reemplace los archivos). Si git reporta errores por cambios locales (ej: `chmod`), use `git stash push -m "local-install-script-fix"` antes del pull. Finalmente, ejecute `sudo ./scripts/install_service.sh install` para refrescar dependencias.
