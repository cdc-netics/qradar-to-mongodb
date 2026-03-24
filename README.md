# QRadar to MongoDB - Event Sync

Sincronización automatizada de eventos (AQL) y alertas/ofensas (API REST) desde múltiples instancias de IBM QRadar hacia MongoDB. Diseñado con una arquitectura multi-tarea guiada por configuración (JSON), ideal para consolas SIEM distribuidas o entornos con múltiples arrendatarios (MSSP).

## Novedades Recientes (v0.4.0)
- **Multi-Protocolo**: Ahora soporta consultas SQL (AQL) y llamadas directas a la API REST (ej. Ofensas).
- **Intervalos Independientes**: Las métricas globales pueden actualizarse cada hora, mientras las ofensas se revisan cada 5 minutos de forma paralela.
- **Mapeo Multi-QRadar**: Soporta múltiples QRadars, traduciendo dinámicamente el `domain_id` o el `cliente` al nombre comercial de la empresa correspondiente sin conflictos.
- **Testing Aislado**: Soporte para `--task <id>` en consola para probar integraciones específicas al instante.
---

## 🏗️ Cómo funciona (Arquitectura del Proceso)

El script sigue un flujo de trabajo lineal y robusto para garantizar la integridad de los datos:

1.  **Descubrimiento de QRadar**: Detecta automáticamente todas las instancias configuradas en `.env` (`QRADAR_1_*`, `QRADAR_2_*`, ...).
2.  **Carga de Tareas**: Lee el archivo `queries.json` que contiene el catálogo de consultas AQL y sus destinos en MongoDB.
3.  **Motor Multi-Consulta**: Por cada instancia QRadar y cada tarea definida, genera y ejecuta una consulta AQL usando la ventana de tiempo centralizada.
4.  **Ejecución Ariel**: Envía cada consulta a la API de QRadar y monitoriza su estado de forma independiente.
5.  **Cálculo de EPS**: 
    - Descarga los resultados JSON.
    - Calcula el promedio de **Eventos Por Segundo (EPS)** automáticamente para cada tarea que lo requiera.
6.  **Persistencia Dinámica**: Transforma los datos al esquema configurado, agrega el campo `qradar_source` para identificar el origen, e inserta los resultados en la **colección específica** de MongoDB.

---

## 📋 Requisitos

- **Sistema Operativo**: Linux (Ubuntu, Debian, RHEL, Rocky, AlmaLinux).
- **Python**: Versión 3.10 o superior.
- **Conectividad**: Acceso de red a las consolas QRadar y al servidor MongoDB.
- **QRadar**: Un *Security Token* (SEC) con permisos para ejecutar búsquedas Ariel.

### Puertos de Red Requeridos

| Origen | Destino | Puerto | Protocolo | Descripción |
| :--- | :--- | :---: | :---: | :--- |
| Servidor del script | Cada consola QRadar | **443** | TCP/HTTPS | API REST Ariel Searches |
| Servidor del script | Servidor MongoDB | **27017** | TCP | Conexión a la base de datos (configurable con `MONGO_PORT`) |

> **Firewall**: Asegúrese de que estos puertos estén abiertos **desde** el servidor donde corre el script **hacia** cada QRadar y MongoDB.

---

## ⚙️ Configuración (Variables de Entorno)

El script utiliza un archivo `.env` para su configuración. Use `.env.example` como base.

| Variable | Descripción | Valor sugerido |
| :--- | :--- | :--- |
| `QRADAR_N_IP` | IP de la consola QRadar N (N=1,2,3...) | `10.1.2.3` |
| `QRADAR_N_TOKEN` | Token SEC de la consola QRadar N | `xxxxxxxx-xxxx-...` |
| `QRADAR_N_NAME` | Nombre descriptivo (opcional, default: `qradar_N`) | `qradar_principal` |
| `QRADAR_N_DEFAULT_DOMAIN_ALIAS` | Alias para reemplazar "Default Domain" (opcional) | `NombreCliente` |
| `MONGO_URI` | URI completa de conexión (Prioridad alta) | `mongodb://...` |
| `MONGO_HOST` | Host de MongoDB | `localhost` |
| `MONGO_DB` | Base de datos destino | `qradar_metrics` |
| `MONGO_COLLECTION`| Colección por defecto (se sobreescribe por `queries.json`) | `eps_stats` |
| `SYNC_INTERVAL_MINUTES`| Ventana AQL y frecuencia (minutos) | `60` |
| `APP_TIMEZONE` | Zona horaria para campos de fecha | `America/Santiago` |
| `RUN_CONTINUOUS` | Ejecutar en bucle infinito | `true` |

> **Nota**: Puede configurar múltiples instancias QRadar usando la convención numérica: `QRADAR_1_IP`, `QRADAR_1_TOKEN`, `QRADAR_2_IP`, `QRADAR_2_TOKEN`, etc. El script las detecta automáticamente.

---

## 🚀 Instalación y Despliegue

Para preparar el entorno y activar el servicio:

1. **Dar permisos**: `chmod +x scripts/install_service.sh`
2. **Ejecutar**: `./scripts/install_service.sh`
3. **Seleccionar Opción 1**: "Instalar / Actualizar servicio".

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
sEl script puede ejecutarse interactuando con el programador o ejecutando tareas específicas al instante:

```bash
# 1. Ejecutar el ciclo completo una vez frente a todas las instancias (cron mode).
python3 qradar-to-mongodb.py

# 2. Ejecutar SOLO UNA tarea ignorando intervalos (ideal para pruebas y debug).
python3 qradar-to-mongodb.py --task offenses_sync
```

Si desea ejecución continua (daemon), asegúrese de tener `RUN_CONTINUOUS=true` en su `.env`. El servicio evaluará independientemente los intervalos (`interval_minutes`) de cada tarea definida en `queries.json`.

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

## 🔌 Test de Conectividad QRadar

Para verificar rápidamente que todas las instancias QRadar configuradas en `.env` son alcanzables y sus tokens son válidos:

```bash
sudo ./scripts/install_service.sh test
# o seleccionar opción 4 del menú interactivo
```

El test realiza dos pruebas por cada instancia:
1. **Ping** — Verifica conectividad de red a la IP.
2. **API + Token** — Hace un request HTTPS al endpoint `/api/help/versions` para validar que el token SEC funciona.

Ejemplo de salida:
```
─────────────────────────────────────
  QRadar #1: qradar_principal (10.0.105.100)
─────────────────────────────────────
  [1/2] Ping a 10.0.105.100 ... ✅ OK
  [2/2] API + Token ... ✅ OK (HTTP 200)
=============================================
 RESULTADO: 1 instancias encontradas
   ✅ Exitosas: 1
   ❌ Fallidas:  0
=============================================
```

---

## 🔍 Solución de Problemas (Troubleshooting)

- **Error: search_id no devuelto**: Verifique que el `QRADAR_N_TOKEN` no haya expirado y que la `QRADAR_N_IP` sea accesible.
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
    - `description`: Descripción breve de lo que hace la consulta.
    - `aql`: La consulta AQL base. El script concatena automáticamente `LAST X MINUTES`.
    - `collection`: **Nombre de la colección (tabla) de destino en MongoDB.** Cada consulta puede apuntar a una colección diferente. MongoDB la crea automáticamente si no existe.
    - `mapping`: Diccionario que asocia las columnas del resultado AQL con los nombres de campo deseados en MongoDB.
    - `calculate_eps`: Si es `true`, el script calcula y añade el campo `eps` al documento.
3.  **Reinicie el servicio**: `sudo systemctl restart qradar-to-mongodb`

#### Ejemplo de entrada en `queries.json`:
```json
{
    "id": "logsource_summary",
    "description": "Resumen de eventos por tipo de fuente de log",
    "aql": "SELECT LOGSOURCETYPENAME(devicetype) AS type, SUM(eventcount) AS count FROM events GROUP BY devicetype",
    "collection": "logsource_summary",
    "mapping": {
      "type": "log_source_type",
      "count": "total_eventos"
    },
    "calculate_eps": true
}
```

> **Nota**: La variable `MONGO_DB` del `.env` define la base de datos, y el campo `collection` de cada tarea en `queries.json` define en qué colección (tabla) dentro de esa base de datos se guardan los resultados. No es necesario crear las colecciones previamente. Cada documento incluye el campo `qradar_source` para identificar de qué instancia QRadar proviene.

---

## 🔗 Cómo agregar otra instancia QRadar

Para conectar una nueva consola QRadar, solo agregue las variables al `.env`:

```env
QRADAR_2_NAME=qradar_datacenter_b
QRADAR_2_IP=10.0.106.50
QRADAR_2_TOKEN=tu-token-sec-aqui
# (Opcional) Alias para el "Default Domain" de este QRadar
#QRADAR_2_DEFAULT_DOMAIN_ALIAS=NombreCliente
```

El script auto-descubre todas las instancias (`QRADAR_1`, `QRADAR_2`, ..., `QRADAR_N`) y ejecuta todas las consultas de `queries.json` contra cada una. Los resultados se identifican en MongoDB mediante el campo `qradar_source`.

> **Nota sobre "Default Domain"**: QRadar siempre devuelve `"Default Domain"` como nombre de cliente cuando no hay dominios personalizados (limitación de IBM). Para evitar colisiones entre instancias, el script reemplaza automáticamente este valor por el `QRADAR_N_NAME`. Si necesita un nombre distinto, use `QRADAR_N_DEFAULT_DOMAIN_ALIAS`. El valor original se preserva en el campo `cliente_original`.

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
