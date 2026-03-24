# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato esta basado en Keep a Changelog y versionado semantico.

## [v0.4.0] - 2026-03-24

### Añadido
- **Soporte API REST**: El motor ahora soporta tareas de tipo `"rest_api"`, permitiendo sincronizar recursos nativos como Ofensas (`/api/siem/offenses`).
- **Intervalos Independientes**: Soporte para `interval_minutes` en `queries.json`, permitiendo que AQL y REST corran en ciclos de tiempo completamente distintos.
- **Filtro CLI (`--task`)**: Argumento de línea de comandos para aislar y forzar la ejecución inmediata de una única tarea (ideal para testing y debug).
- **Mapeo de Dominios por Instancia**: Nueva propiedad `domain_mapping` en `queries.json` para traducir IDs numéricos a nombres de cliente, diferenciando lógicamente entre múltiples QRadars.
- **Sobrescritura Inteligente**: Nueva opción `clear_before_sync` que purga los datos anteriores de MongoDB **solo para el QRadar conectado**, manteniendo colecciones limpias como en el caso de las Ofensas "OPEN".
- **Cabeceras Personalizadas**: Soporte para pasar `headers` específicos por tarea en `queries.json` (ej. `Version`, `Range`).

### Cambiado
- El bucle de ejecución continua (`RUN_CONTINUOUS`) ahora despierta cada 60 segundos (o lo que dicte `RUN_INTERVAL_SECONDS`) para evaluar de forma granular si le toca el turno a alguna tarea de intervalo corto.

## [0.3.1-beta.1] - 2026-03-24

### Added

- **Normalización de "Default Domain"**: Cuando QRadar devuelve `"Default Domain"` como nombre de cliente (limitación de IBM), el script lo reemplaza automáticamente por el `QRADAR_N_NAME` configurado en `.env`.
- **Variable `QRADAR_N_DEFAULT_DOMAIN_ALIAS`**: Nueva variable opcional por instancia que permite definir un alias personalizado para el "Default Domain" de cada QRadar. Si no se define, se usa `QRADAR_N_NAME` por defecto.
- **Campo `cliente_original`**: Se preserva el valor original devuelto por QRadar antes de la normalización, para trazabilidad.

### Fixed

- **Colisión de datos entre múltiples QRadar**: Resuelto problema donde dos instancias QRadar con clientes en "Default Domain" mezclaban sus datos en MongoDB al compartir el mismo nombre de cliente.

---

## [0.3.0-beta.1] - 2026-03-23

### Added

- **Soporte Multi-QRadar**: El script ahora puede conectarse a múltiples instancias de QRadar en un mismo ciclo de sincronización.
- **Auto-descubrimiento**: Nueva función `load_qradars()` que detecta automáticamente todas las instancias configuradas (`QRADAR_1_*`, `QRADAR_2_*`, ..., `QRADAR_N_*`).
- **Campo `qradar_source`**: Cada documento insertado en MongoDB incluye un nuevo campo que identifica la instancia QRadar de origen.
- **Test de conectividad**: Nueva opción 4 en el instalador (`test`) que prueba ping y token de todas las instancias QRadar configuradas.

### Changed

- **Migración de variables de entorno**: `QRADAR_IP` y `QRADAR_TOKEN` reemplazados por convención numérica (`QRADAR_1_IP`, `QRADAR_1_TOKEN`, `QRADAR_1_NAME`, etc.).
- **Validación actualizada**: `validate_required_env()` ya no busca variables únicas de QRadar; delega la validación a `load_qradars()`.

### Removed

- Variables `QRADAR_IP` y `QRADAR_TOKEN` del `.env` (migradas a formato multi-instancia).
- Bloque `__main__` duplicado al final del script.

## [0.2.0-beta.2] - 2026-03-21

### Added

- **Motor Multi-Tarea**: Soporte para ejecutar múltiples consultas AQL en cada ciclo.
- **Configuración Externa (`queries.json`)**: Las consultas y su mapeo a colecciones de MongoDB ahora se gestionan de forma externa sin tocar el código.
- **Aislamiento de Errores**: Sistema robusto que permite que una tarea falle sin detener la ejecución de las demás.
- **Formato Dinámico**: Mapeo flexible de columnas de QRadar a campos técnicos de MongoDB definido por tarea.
- **Nueva métrica**: Añadida tarea `logsource_summary` con formato detallado y cálculo automático de EPS.
- **Licencia**: Se ha incorporado la licencia **Business Source License 1.1** al proyecto.

### Changed

- **Simplificación de configuración**: Consolidación definitiva de `MINUTOS_INTERVALO` y `RUN_INTERVAL_SECONDS` en la variable maestra `SYNC_INTERVAL_MINUTES`.
- **Auto-sincronización**: El tiempo de espera del script ahora se calcula automáticamente basándose en los minutos de la ventana de consulta.
- **Limpieza de `.env`**: Estructura simplificada y alineada con las mejores prácticas.

### Changed

- Documentacion Linux actualizada para ejecucion permanente.
- Manejo horario ajustado a zona de negocio configurable (`APP_TIMEZONE`, default `America/Santiago`).
- Nuevo campo `hora_minuto` para reflejar hora local exacta y evitar confusion con `hora` truncada (`HH:00`).

## [0.1.0-beta.1] - 2026-03-20

### Added (0.1.0-beta.1)

- Estructura base del repositorio.
- README orientado a Linux con instalacion, uso, variables y flujo.
- Plantillas de GitHub Issues para bug y feature request.
- Configuracion de Issues para deshabilitar issues en blanco.
- Archivo gitignore para Python y archivos locales.
- Archivo env example con variables requeridas y opcionales.
- Archivo requirements.txt para instalacion reproducible de dependencias.
- Archivo LINUX_SETUP.md con requisitos y pasos para Linux.
- Seccion en README con formato del documento MongoDB y tipos de datos.
- Export opcional a TXT para pruebas mediante DEBUG_EXPORT_TXT y DEBUG_TXT_FILE.

### Changed (0.1.0-beta.1)

- Script principal con validacion de variables de entorno requeridas.
- Manejo HTTP con timeout y validacion de respuestas mediante raise_for_status.
- Polling de QRadar con limite de intentos para evitar bucles infinitos.
- Mensajes de salida y cierre explicito de conexion a MongoDB.
- Carga de variables de entorno al inicio para asegurar lectura correcta desde env.
- Calculo de EPS ajustado a ventana real en segundos (MINUTOS_INTERVALO x 60).
- EPS almacenado como entero sin decimales.
- Regla operativa aplicada: si EPS promedio resulta 0, se almacena 1.
- Script ampliamente comentado para facilitar mantenimiento y transferencia tecnica.
