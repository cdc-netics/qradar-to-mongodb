# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato esta basado en Keep a Changelog y versionado semantico.

## [Unreleased]

### Changed

- Soporte dual para credenciales MongoDB: usa MONGO_URI si existe, o construye URI desde variables separadas.
- Documentacion y env example actualizados con variables MONGO_HOST, MONGO_PORT, MONGO_USER, MONGO_PASSWORD, MONGO_AUTH_SOURCE y MONGO_PARAMS.

## [0.1.0-beta.1] - 2026-03-20

### Added

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

### Changed

- Script principal con validacion de variables de entorno requeridas.
- Manejo HTTP con timeout y validacion de respuestas mediante raise_for_status.
- Polling de QRadar con limite de intentos para evitar bucles infinitos.
- Mensajes de salida y cierre explicito de conexion a MongoDB.
- Carga de variables de entorno al inicio para asegurar lectura correcta desde env.
- Calculo de EPS ajustado a ventana real en segundos (MINUTOS_INTERVALO x 60).
- EPS almacenado como entero sin decimales.
- Regla operativa aplicada: si EPS promedio resulta 0, se almacena 1.
- Script ampliamente comentado para facilitar mantenimiento y transferencia tecnica.
