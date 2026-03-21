# QRadar to MongoDB - Event Sync

Script en Python diseñado para extraer métricas de eventos desde **IBM QRadar** (mediante consultas AQL) y persistirlas en **MongoDB** para su posterior análisis o visualización.

---

## 🏗️ Cómo funciona (Arquitectura del Proceso)

El script sigue un flujo de trabajo lineal y robusto para garantizar la integridad de los datos:

1.  **Carga de Tareas**: Lee el archivo `queries.json` que contiene el catálogo de consultas AQL y sus destinos en MongoDB.
2.  **Motor Multi-Consulta**: Por cada tarea definida, genera una consulta Ariel Query Language (AQL) usando la ventana de tiempo centralizada en el `.env`.
3.  **Ejecución Ariel**: Envía cada consulta a la API de QRadar y monitoriza su estado de forma independiente.
4.  **Cálculo de EPS**: 
    - Descarga los resultados JSON.
    - Calcula el promedio de **Eventos Por Segundo (EPS)** automáticamente para cada tarea que lo requiera.
5.  **Persistencia Dinámica**: Transforma los datos al esquema de documentos configurado e inserta los resultados en la **colección específica** de MongoDB definida para esa tarea.

---

## 📋 Requisitos

- **Sistema Operativo**: Linux (Ubuntu, Debian, RHEL, Rocky, AlmaLinux).
- **Python**: Versión 3.10 o superior.
- **Conectividad**: Acceso HTTPS (puerto 443) a la consola de QRadar y conectividad al puerto de MongoDB (default 27017).
- **QRadar**: Un *Security Token* (SEC) con permisos para ejecutar búsquedas Ariel.

---

## ⚙️ Configuración (Variables de Entorno)

El script utiliza un archivo `.env` para su configuración. Use `.env.example` como base.

| Variable | Descripción | Valor sugerido |
| :--- | :--- | :--- |
| `QRADAR_IP` | IP o Hostname de la consola QRadar | `10.1.2.3` |
| `QRADAR_TOKEN` | Token SEC de QRadar | `xxxxxxxx-xxxx-...` |
| `MONGO_URI` | URI completa de conexión (Prioridad alta) | `mongodb://...` |
| `MONGO_HOST` | Host de MongoDB | `localhost` |
| `MONGO_DB` | Base de datos destino | `qradar_metrics` |
| `MONGO_COLLECTION`| Colección destino | `eps_stats` |
| `SYNC_INTERVAL_MINUTES`| Ventana AQL y frecuencia (minutos) | `60` |
| `APP_TIMEZONE` | Zona horaria para campos de fecha | `America/Santiago` |
| `RUN_CONTINUOUS` | Ejecutar en bucle infinito | `true` |

---

## 🚀 Instalación y Despliegue

### Opción A: Instalador Automático (Recomendado)
El proyecto incluye un script inteligente que prepara todo el entorno:

```bash
chmod +x scripts/install_service.sh
sudo ./scripts/install_service.sh
```
El instalador creará el entorno virtual, instalará dependencias, configurará el archivo `.env` y levantará el servicio en `systemd`.

### Opción B: Instalación Manual
Consulte la [Guía de Instalación en Linux](LINUX_SETUP.md) para los pasos detallados comando a comando.

---

## 🛠️ Comandos de Administración

Si usó el instalador automático, puede gestionar el proceso como un servicio estándar de Linux:

```bash
# Ver si el servicio está corriendo y sus últimos logs
sudo systemctl status qradar-to-mongodb

# Ver logs en tiempo real
sudo journalctl -u qradar-to-mongodb -f

# Reiniciar tras un cambio en el .env
sudo systemctl restart qradar-to-mongodb
```

---

## 🧪 Prueba de Humo (Smoke Test)

Si desea validar que todo está correctamente configurado (red, QRadar y MongoDB) ejecutando el script una sola vez en el entorno real del sistema:

```bash
sudo systemd-run --unit qradar-smoketest --wait --collect \
  -p WorkingDirectory=/opt/qradar-to-mongodb \
  /bin/bash -lc 'set -a; source /opt/qradar-to-mongodb/.env; set +a; RUN_CONTINUOUS=false SYNC_INTERVAL_MINUTES=5 /opt/qradar-to-mongodb/.venv/bin/python /opt/qradar-to-mongodb/qradar-to-mongodb.py'
```

Este comando:
- Crea una unidad temporal en systemd.
- Carga las variables de `.env`.
- Fuerza `RUN_CONTINUOUS=false` para ejecutar una sola vez.
- Usa una ventana de 5 minutos (`MINUTOS_INTERVALO=5`) para una respuesta rápida.

---

## 🔍 Solución de Problemas (Troubleshooting)

- **Error: search_id no devuelto**: Verifique que el `QRADAR_TOKEN` no haya expirado y que la `QRADAR_IP` sea accesible.
- **El script no inicia (ModuleNotFoundError)**: Asegúrese de estar ejecutando el script dentro del entorno virtual (`source .venv/bin/activate`).
- **Fallas de conexión a MongoDB**: Verifique que `MONGO_USER` y `MONGO_PASSWORD` sean correctos o que la `MONGO_URI` no tenga errores de sintaxis. Use `repair` en el instalador si sospecha de permisos en `.env`.
- **EPS siempre es 1**: Si el volumen de eventos es muy bajo en relación a la ventana de tiempo (ej: menos de 3600 eventos en 60 minutos), el cálculo redondeará a 0 y la regla de negocio lo forzará a 1.
- **Error al bajar cambios (git pull)**: Si git detecta cambios locales (comúnmente tras un `chmod`) que impiden el pull, use: `git stash push -m "local-install-script-fix"` para limpiar el estado temporalmente y reintentar el `git pull`.


---

## ➕ Cómo agregar nuevas consultas

El sistema es extensible sin tocar el código Python. Para añadir una nueva métrica:

1.  **Edite `queries.json`**: Añada un nuevo objeto a la lista.
2.  **Configure los campos**:
    - `id`: Identificador único de la tarea.
    - `aql`: La consulta AQL (el script añade el tiempo automáticamente).
    - `collection`: Nombre de la tabla en MongoDB. **necesitas crearla manualmente**, MongoDB no la va a crear.
    - `mapping`: Asocia columnas de QRadar con campos de Mongo.
3.  **Reinicie**: `sudo systemctl restart qradar-to-mongodb`

#### Ejemplo de `queries.json`:
```json
 {
    "id": "logsource_summary",
    "aql": "SELECT LOGSOURCETYPENAME(devicetype) AS type, SUM(eventcount) AS count FROM events GROUP BY devicetype",
    "collection": "logsource_summary",
    "mapping": {
      "type": "log_source_type",
      "count": "total_eventos"
    },
    "calculate_eps": true
  }
```

---

## 📂 Estructura del Proyecto

```text
.
├── qradar-to-mongodb.py   # Motor de sincronización multi-tarea
├── queries.json           # Catálogo de consultas AQL y mapeo a MongoDB
├── requirements.txt       # Dependencias de Python
├── .env                  # Configuración de infraestructura (IP, Token, DB)
├── .env.example           # Plantilla de configuración
├── scripts/
│   └── install_service.sh # Instalador y gestor automatizado
├── LINUX_SETUP.md         # Documentación detallada de despliegue
└── README.md              # Documentación general
```

---

## 📄 Licencia

Este proyecto está bajo la licencia **Business Source License 1.1** (BSL). Consulte los archivos [LICENSE](LICENSE) (Inglés) y [LICENSE.es](LICENSE.es) (Español) para obtener más detalles sobre los términos de uso comercial y no comercial.
