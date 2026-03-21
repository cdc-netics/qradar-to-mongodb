# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato esta basado en Keep a Changelog y versionado semantico.

## [Unreleased]

### Changed

- **Simplificación de configuración**: Se consolidaron `MINUTOS_INTERVALO` y `RUN_INTERVAL_SECONDS` en una única variable maestra: `SYNC_INTERVAL_MINUTES`.
- El script ahora calcula automáticamente los segundos de espera basándose en los minutos de la ventana de consulta para evitar errores humanos de desincronización.
- Limpieza integral del archivo `.env` para eliminar redundancias y seguir el estándar de `.env.example`.
- Retrocompatibilidad mantenida para `MINUTOS_INTERVALO` si `SYNC_INTERVAL_MINUTES` no está definido en el entorno.

### Added

- Nueva accion repair para corregir permisos de .env y reparar systemd sin reinstalacion completa.

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
