#!/usr/bin/env bash
# =============================================================================
# QRadar to MongoDB - Service Installer & Manager
# =============================================================================
# Este script automatiza el despliegue del servicio en sistemas Linux.
# Realiza las siguientes tareas:
# 1. Valida dependencias del sistema.
# 2. Prepara un entorno virtual (venv) de Python.
# 3. Instala las dependencias listadas en requirements.txt.
# 4. Configura el archivo de entorno .env.
# 5. Genera y activa una unidad de systemd para ejecución automática.
# =============================================================================

set -euo pipefail

# --- CONFIGURACIÓN POR DEFECTO ---
SERVICE_NAME="qradar-to-mongodb"
APP_DIR="${APP_DIR:-/opt/qradar-to-mongodb}"
# Intenta obtener el usuario que ejecutó sudo, si no, usa el usuario actual.
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SELECTED_ACTION=""

# --- FUNCIONES DE LOGGING ---
log() {
  printf "[INFO] %s\n" "$*"
}

warn() {
  printf "[WARN] %s\n" "$*"
}

err() {
  printf "[ERROR] %s\n" "$*" >&2
}

# --- VALIDACIONES INICIALES ---

# Verifica que un comando necesario esté instalado en el sistema.
require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "Comando no encontrado: $cmd. Por favor instálelo antes de continuar."
    exit 1
  fi
}

# Asegura que el script se ejecute con privilegios de root (necesario para systemd).
require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "Este script debe ejecutarse como root (use sudo)."
    exit 1
  fi
}

# Valida que el usuario y grupo definidos existan en el sistema Linux.
validate_service_identity() {
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    err "El usuario de servicio no existe: $SERVICE_USER"
    exit 1
  fi

  if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    err "El grupo de servicio no existe: $SERVICE_GROUP"
    exit 1
  fi
}

# Muestra el encabezado principal y el resumen de configuración.
show_program_info() {
  cat <<EOF
=============================================
 QRadar to MongoDB - Gestor de Servicio
=============================================
Nombre servicio: ${SERVICE_NAME}
Directorio app : ${APP_DIR}
Usuario        : ${SERVICE_USER}
Grupo          : ${SERVICE_GROUP}
Binario Python : ${PYTHON_BIN}

Acciones disponibles:
  1) install   -> Prepara venv, dependencias, .env, systemd y arranca el servicio.
  2) repair    -> Corrige permisos de .env, reescribe el unit file y reinicia.
  3) uninstall -> Detiene/desactiva el servicio y elimina el unit file de forma segura.
  4) test      -> Prueba conectividad y token de todas las instancias QRadar.
EOF
}

# Verifica que los archivos críticos del proyecto estén presentes en el APP_DIR.
check_paths() {
  if [[ ! -d "$APP_DIR" ]]; then
    err "Directorio de aplicación no encontrado: $APP_DIR"
    exit 1
  fi

  if [[ ! -f "$APP_DIR/qradar-to-mongodb.py" ]]; then
    err "Script principal no encontrado: $APP_DIR/qradar-to-mongodb.py"
    exit 1
  fi

  if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
    err "requirements.txt no encontrado en $APP_DIR"
    exit 1
  fi
}

# --- FLUJOS DE TRABAJO ---

# Configura el Virtual Environment de Python para aislar dependencias.
setup_venv() {
  log "Configurando entorno virtual (venv)..."
  if [[ ! -d "$APP_DIR/.venv" ]]; then
    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  fi

  log "Actualizando pip e instalando dependencias..."
  "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
}

# Gestiona la creación inicial del archivo .env y sus permisos.
setup_env_file() {
  if [[ ! -f "$APP_DIR/.env" ]]; then
    if [[ -f "$APP_DIR/.env.example" ]]; then
      log "Creando .env desde .env.example..."
      cp "$APP_DIR/.env.example" "$APP_DIR/.env"
      warn "¡IMPORTANTE! Edite $APP_DIR/.env con sus credenciales reales."
    else
      err "No se encontró .env ni .env.example en $APP_DIR"
      exit 1
    fi
  fi

  # Asegura que solo el usuario del servicio (y root) puedan leer el archivo de secretos.
  chown "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR/.env"
  chmod 640 "$APP_DIR/.env"
}

# Corrige permisos de .env (útil si se copiaron archivos como root manualmente).
repair_env_permissions() {
  if [[ ! -f "$APP_DIR/.env" ]]; then
    warn ".env no encontrado. Reintentando creación desde .env.example..."
    setup_env_file
  else
    log "Corrigiendo owner y permisos para .env"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR/.env"
    chmod 640 "$APP_DIR/.env"
  fi
}

# Crea el archivo de log definido en LOG_FILE (si existe en .env) con los permisos correctos.
setup_log_file() {
  if [[ ! -f "$APP_DIR/.env" ]]; then
    return
  fi

  local log_file
  log_file=$(grep -E '^LOG_FILE=' "$APP_DIR/.env" | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)

  if [[ -z "$log_file" ]]; then
    log "LOG_FILE no definido en .env — los logs irán solo a journalctl."
    return
  fi

  local log_dir
  log_dir=$(dirname "$log_file")

  log "Preparando archivo de log: $log_file"

  if [[ ! -d "$log_dir" ]]; then
    mkdir -p "$log_dir" || { warn "No se pudo crear el directorio $log_dir. Verifique permisos."; return; }
  fi

  if [[ ! -f "$log_file" ]]; then
    touch "$log_file" || { warn "No se pudo crear $log_file. Verifique permisos del directorio $log_dir."; return; }
    log "Archivo de log creado: $log_file"
  else
    log "Archivo de log existente: $log_file"
  fi

  chown "$SERVICE_USER:$SERVICE_GROUP" "$log_file"
  chmod 640 "$log_file"
  log "Permisos aplicados: owner=$SERVICE_USER:$SERVICE_GROUP modo=640"
}

# Asegura que WAIT_ON_START=true quede activo en .env al instalar.
# Evita que el primer ciclo inmediato tras un restart genere datos duplicados.
ensure_wait_on_start() {
  if [[ ! -f "$APP_DIR/.env" ]]; then
    return
  fi

  if grep -qE '^WAIT_ON_START=' "$APP_DIR/.env"; then
    # La variable ya existe: reemplazar su valor por true
    sed -i 's/^WAIT_ON_START=.*/WAIT_ON_START=true/' "$APP_DIR/.env"
    log "WAIT_ON_START=true activado en .env (evita datos duplicados al reiniciar)."
  else
    # La variable no existe: agregarla al final
    printf '\n# Espera un intervalo antes del primer ciclo para evitar datos duplicados al reiniciar\nWAIT_ON_START=true\n' >> "$APP_DIR/.env"
    log "WAIT_ON_START=true agregado a .env (evita datos duplicados al reiniciar)."
  fi
}

# Escanea el .env buscando valores de ejemplo que aún no han sido cambiados.
validate_env_placeholders() {
  if grep -q "replace-with.*token" "$APP_DIR/.env"; then
    warn "Detectado placeholder en un QRADAR_TOKEN. El servicio fallará hasta que lo cambie."
  fi

  if grep -q "^MONGO_PASSWORD=$" "$APP_DIR/.env"; then
    warn "MONGO_PASSWORD parece estar vacío en el archivo .env."
  fi
}

# Prueba de conectividad y validación de token para todas las instancias QRadar.
test_qradar_flow() {
  log "Iniciando prueba de conectividad QRadar..."

  if [[ ! -f "$APP_DIR/.env" ]]; then
    err "No se encontró $APP_DIR/.env — No se puede leer la configuración QRadar."
    exit 1
  fi

  # Cargar variables del .env (sin exportar al entorno global del shell).
  local env_content
  env_content=$(grep -v '^#' "$APP_DIR/.env" | grep -v '^$')

  local n=1
  local found=0
  local passed=0
  local failed=0

  while true; do
    # Extraer QRADAR_N_IP del archivo .env
    local ip_var="QRADAR_${n}_IP"
    local token_var="QRADAR_${n}_TOKEN"
    local name_var="QRADAR_${n}_NAME"

    local ip=$(echo "$env_content" | grep "^${ip_var}=" | head -1 | cut -d'=' -f2-)
    local token=$(echo "$env_content" | grep "^${token_var}=" | head -1 | cut -d'=' -f2-)
    local name=$(echo "$env_content" | grep "^${name_var}=" | head -1 | cut -d'=' -f2-)

    # Si no encontramos IP, terminamos el escaneo.
    if [[ -z "$ip" ]]; then
      break
    fi

    found=$((found + 1))
    name="${name:-qradar_$n}"

    printf "\n─────────────────────────────────────\n"
    printf "  QRadar #%d: %s (%s)\n" "$n" "$name" "$ip"
    printf "─────────────────────────────────────\n"

    # --- Test 1: Ping (conectividad de red) ---
    printf "  [1/2] Ping a %s ... " "$ip"
    if ping -c 2 -W 3 "$ip" >/dev/null 2>&1; then
      printf "✅ OK\n"
    else
      printf "❌ SIN RESPUESTA\n"
      warn "No se puede alcanzar $ip. Verifique la red o firewall."
      failed=$((failed + 1))
      n=$((n + 1))
      continue
    fi

    # --- Test 2: API + Token (HTTPS a la API de QRadar) ---
    if [[ -z "$token" ]]; then
      printf "  [2/2] Token ... ❌ NO CONFIGURADO\n"
      warn "$token_var esta vacío o no existe en .env"
      failed=$((failed + 1))
      n=$((n + 1))
      continue
    fi

    printf "  [2/2] API + Token ... "
    local http_code
    # Usa /api/help/versions — endpoint ligero de QRadar que funciona
    # con cualquier token válido sin importar el rol asignado.
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
      --connect-timeout 10 --max-time 15 \
      -k -H "SEC: $token" -H "Accept: application/json" \
      "https://${ip}/api/help/versions" 2>/dev/null) || http_code="000"

    case "$http_code" in
      200)
        printf "✅ OK (HTTP %s)\n" "$http_code"
        passed=$((passed + 1))
        ;;
      401|403)
        printf "❌ TOKEN INVÁLIDO (HTTP %s)\n" "$http_code"
        warn "El token de $name fue rechazado. Verifique que sea correcto y no haya expirado."
        failed=$((failed + 1))
        ;;
      000)
        printf "❌ SIN CONEXIÓN HTTPS (HTTP %s)\n" "$http_code"
        warn "No se pudo conectar al puerto 443 de $ip. Verifique firewall / certificados."
        failed=$((failed + 1))
        ;;
      *)
        printf "⚠️  RESPUESTA INESPERADA (HTTP %s)\n" "$http_code"
        warn "Respuesta no esperada de $ip. Puede ser un problema temporal."
        failed=$((failed + 1))
        ;;
    esac

    n=$((n + 1))
  done

  # --- Resumen final ---
  printf "\n=============================================\n"
  if [[ $found -eq 0 ]]; then
    err "No se encontraron instancias QRadar en $APP_DIR/.env"
    err "Asegúrese de definir al menos QRADAR_1_IP y QRADAR_1_TOKEN"
    exit 1
  fi

  printf " RESULTADO: %d instancias encontradas\n" "$found"
  printf "   ✅ Exitosas: %d\n" "$passed"
  printf "   ❌ Fallidas:  %d\n" "$failed"
  printf "=============================================\n"

  if [[ $failed -gt 0 ]]; then
    warn "Algunas instancias fallaron. Revise los mensajes anteriores."
  else
    log "¡Todas las instancias QRadar están accesibles y autenticadas!"
  fi
}

# Genera el archivo de unidad de systemd con las rutas dinámicas detectadas.
write_systemd_unit() {
  log "Generando unidad systemd en: $UNIT_FILE"
  cat > "$UNIT_FILE" <<EOF
[Unit]
Description=QRadar to MongoDB Sync Service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/qradar-to-mongodb.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
}

# Realiza el despliegue efectivo en systemd.
enable_service() {
  log "Recargando daemon de systemd y habilitando servicio..."
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  log "Reiniciando servicio..."
  systemctl restart "$SERVICE_NAME"
}

# Muestra el estado final y comandos útiles al usuario.
show_status() {
  log "Resumen del estado del servicio:"
  systemctl --no-pager --full status "$SERVICE_NAME" || true

  cat <<MSG

¡Proceso completado con éxito!
Comandos útiles para administración:
  - Ver estado:    sudo systemctl status ${SERVICE_NAME}
  - Ver logs:      sudo journalctl -u ${SERVICE_NAME} -f
  - Reiniciar:     sudo systemctl restart ${SERVICE_NAME}
  - Detener:       sudo systemctl stop ${SERVICE_NAME}

Configuración avanzada:
  Puede ejecutar este script con variables personalizadas:
  sudo APP_DIR=/ruta/custom SERVICE_USER=usuario ./scripts/install_service.sh install
MSG
}

# Orquestador del flujo de instalación completa.
install_flow() {
  check_paths
  setup_venv
  setup_env_file
  ensure_wait_on_start
  validate_env_placeholders
  setup_log_file
  write_systemd_unit
  enable_service
  show_status
}

# Orquestador del flujo de desinstalación.
uninstall_flow() {
  log "Desinstalación segura iniciada para: ${SERVICE_NAME}"
  cat <<WARN
[ADVERTENCIA]
Esto detendrá el servicio, lo deshabilitará y eliminará el archivo $UNIT_FILE.
Los archivos en $APP_DIR (código, .env, venv) se mantendrán intactos.
WARN

  local confirm
  read -r -p "¿Está seguro de que desea desinstalar? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[yY]$ ]]; then
    warn "Desinstalación cancelada por el usuario."
    exit 0
  fi

  # Detener y deshabilitar de forma proactiva.
  log "Deteniendo servicio..."
  systemctl stop "$SERVICE_NAME" || true

  log "Deshabilitando servicio de systemd..."
  systemctl disable "$SERVICE_NAME" || true

  # Limpiar el archivo de unidad para que no aparezca en 'systemctl list-units'.
  if [[ -f "$UNIT_FILE" ]]; then
    log "Eliminando archivo de unidad: $UNIT_FILE"
    rm -f "$UNIT_FILE"
  fi

  # Refrescar systemd para que reconozca que el servicio ya no existe.
  systemctl daemon-reload
  log "Desinstalación completada. El directorio de la aplicación se ha preservado."
}

# Orquestador para reparar instalaciones rotas (permisos o rutas).
repair_flow() {
  check_paths

  if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    warn "No se encontró el ejecutable de Python en el venv."
    warn "Se recomienda ejecutar la acción 'install' para reconstruir dependencias."
  fi

  repair_env_permissions
  validate_env_placeholders
  setup_log_file
  write_systemd_unit
  enable_service
  show_status
}

# --- MANEJO DE ENTRADA Y ARGUMENTOS ---

# Menú interactivo si el script se llama sin argumentos.
prompt_action() {
  local choice
  local normalized

  while true; do
    printf "\nSeleccione una acción:\n" >&2
    printf "  1) Instalar / Actualizar servicio\n" >&2
    printf "  2) Reparar permisos/servicio (Seguro)\n" >&2
    printf "  3) Desinstalar servicio (Seguro)\n" >&2
    printf "  4) Probar conectividad QRadar\n" >&2
    read -r -p "Opción [1/2/3/4]: " choice

    normalized="$(normalize_action "$choice")"
    if [[ -n "$normalized" ]]; then
      SELECTED_ACTION="$normalized"
      return
    fi

    err "Opción inválida: $choice"
  done
}

# Normaliza la entrada del usuario a términos internos (install, repair, uninstall).
normalize_action() {
  local input_action="$1"
  local normalized

  # Limpiar espacios en blanco.
  input_action="${input_action#"${input_action%%[![:space:]]*}"}"
  input_action="${input_action%"${input_action##*[![:space:]]}"}"

  # Convertir a minúsculas.
  normalized="${input_action,,}"

  case "$normalized" in
    1|install)   echo "install" ;;
    2|repair)    echo "repair" ;;
    3|uninstall) echo "uninstall" ;;
    4|test)      echo "test" ;;
    *)           echo "" ;;
  esac
}

# Punto de entrada principal (Main).
main() {
  show_program_info
  
  # Validaciones previas de entorno root y herramientas necesarias.
  require_root
  require_cmd "$PYTHON_BIN"
  require_cmd systemctl
  require_cmd grep
  require_cmd chmod
  require_cmd chown
  require_cmd getent
  require_cmd id
  validate_service_identity

  local raw_action="${1:-}"
  local action

  # Si no hay argumentos, preguntar al usuario.
  if [[ -z "$raw_action" ]]; then
    prompt_action
    raw_action="$SELECTED_ACTION"
  fi

  action="$(normalize_action "$raw_action")"

  case "$action" in
    install)   install_flow ;;
    repair)    repair_flow ;;
    uninstall) uninstall_flow ;;
    test)      test_qradar_flow ;;
    *)
      err "Acción desconocida: $raw_action"
      err "Uso: sudo $0 [install|repair|uninstall|test|1|2|3|4]"
      exit 1
      ;;
  esac
}

# Ejecutar el script.
main "$@"
