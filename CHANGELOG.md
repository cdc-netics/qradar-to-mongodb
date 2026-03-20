# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato esta basado en Keep a Changelog y versionado semantico.

## [Unreleased]

### Added
- Estructura base del repositorio.
- README inicial con instalacion, uso y variables de entorno.
- Plantillas de GitHub Issues para bug y feature request.
- `.gitignore` para Python y archivos locales.
- `.env.example` con variables requeridas.
- `requirements.txt` para instalacion reproducible de dependencias.
- `LINUX_SETUP.md` con requisitos y pasos para Linux.

### Changed
- Script principal con validacion de variables de entorno requeridas.
- Manejo HTTP con timeout y validacion de respuestas (`raise_for_status`).
- Polling de QRadar con limite de intentos para evitar bucles infinitos.
- Mensajes de salida y cierre explicito de conexion a MongoDB.
