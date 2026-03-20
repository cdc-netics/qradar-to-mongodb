#!/usr/bin/env bash
set -euo pipefail

# Automated installer for qradar-to-mongodb service on Linux.
# It prepares venv, installs dependencies, creates systemd unit, enables and starts service.

SERVICE_NAME="qradar-to-mongodb"
APP_DIR="${APP_DIR:-/opt/qradar-to-mongodb}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
SERVICE_GROUP="${SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SELECTED_ACTION=""

log() {
  printf "[INFO] %s\n" "$*"
}

warn() {
  printf "[WARN] %s\n" "$*"
}

err() {
  printf "[ERROR] %s\n" "$*" >&2
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "Missing required command: $cmd"
    exit 1
  fi
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "Run as root (or with sudo)."
    exit 1
  fi
}

show_program_info() {
  cat <<EOF
=============================================
 QRadar to MongoDB - Service Manager
=============================================
Service name : ${SERVICE_NAME}
App directory: ${APP_DIR}
Service user : ${SERVICE_USER}
Service group: ${SERVICE_GROUP}
Python bin   : ${PYTHON_BIN}

Actions:
  install   -> prepare venv, dependencies, .env, systemd and start service
  uninstall -> stop/disable service and remove systemd unit safely
EOF
}

check_paths() {
  if [[ ! -d "$APP_DIR" ]]; then
    err "Application directory not found: $APP_DIR"
    exit 1
  fi

  if [[ ! -f "$APP_DIR/qradar-to-mongodb.py" ]]; then
    err "Main script not found: $APP_DIR/qradar-to-mongodb.py"
    exit 1
  fi

  if [[ ! -f "$APP_DIR/requirements.txt" ]]; then
    err "requirements.txt not found in $APP_DIR"
    exit 1
  fi
}

setup_venv() {
  log "Preparing Python virtual environment..."
  if [[ ! -d "$APP_DIR/.venv" ]]; then
    "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  fi

  "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
}

setup_env_file() {
  if [[ ! -f "$APP_DIR/.env" ]]; then
    if [[ -f "$APP_DIR/.env.example" ]]; then
      cp "$APP_DIR/.env.example" "$APP_DIR/.env"
      warn "Created $APP_DIR/.env from .env.example. Please edit with real values."
    else
      err "Missing both .env and .env.example in $APP_DIR"
      exit 1
    fi
  fi

  chmod 600 "$APP_DIR/.env"
}

validate_env_placeholders() {
  if grep -q "replace-with-qradar-token" "$APP_DIR/.env"; then
    warn "QRADAR_TOKEN still has placeholder value."
  fi

  if grep -q "^MONGO_PASSWORD=$" "$APP_DIR/.env"; then
    warn "MONGO_PASSWORD is empty in .env"
  fi
}

write_systemd_unit() {
  log "Writing systemd unit: $UNIT_FILE"
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

enable_service() {
  log "Reloading systemd and enabling service..."
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
}

show_status() {
  log "Service status summary:"
  systemctl --no-pager --full status "$SERVICE_NAME" || true

  cat <<MSG

Done. Useful commands:
  sudo systemctl status ${SERVICE_NAME}
  sudo journalctl -u ${SERVICE_NAME} -f
  sudo systemctl restart ${SERVICE_NAME}

If needed, run with custom values:
  sudo APP_DIR=/opt/qradar-to-mongodb SERVICE_USER=<linux_user> SERVICE_GROUP=<linux_group> ./scripts/install_service.sh
MSG
}

install_flow() {
  check_paths
  setup_venv
  setup_env_file
  validate_env_placeholders
  write_systemd_unit
  enable_service
  show_status
}

uninstall_flow() {
  log "Safe uninstall selected for service: ${SERVICE_NAME}"
  warn "This will stop/disable the service and remove ${UNIT_FILE}."
  warn "Application files in ${APP_DIR} will NOT be deleted."

  local confirm
  read -r -p "Type UNINSTALL to continue: " confirm
  if [[ "$confirm" != "UNINSTALL" ]]; then
    warn "Uninstall canceled by user."
    exit 0
  fi

  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
    log "Stopping service..."
    systemctl stop "$SERVICE_NAME" || true

    log "Disabling service..."
    systemctl disable "$SERVICE_NAME" || true
  else
    warn "Service ${SERVICE_NAME}.service not found in systemd registry."
  fi

  if [[ -f "$UNIT_FILE" ]]; then
    log "Removing unit file: $UNIT_FILE"
    rm -f "$UNIT_FILE"
  else
    warn "Unit file does not exist: $UNIT_FILE"
  fi

  systemctl daemon-reload
  log "Safe uninstall complete. Application directory preserved: ${APP_DIR}"
}

prompt_action() {
  local choice
  printf "\nChoose an action:\n" >&2
  printf "  1) Install / Update service\n" >&2
  printf "  2) Safe uninstall service\n" >&2
  read -r -p "Selection [1/2]: " choice

  case "$choice" in
    1) SELECTED_ACTION="install" ;;
    2) SELECTED_ACTION="uninstall" ;;
    *)
      err "Invalid selection: $choice"
      exit 1
      ;;
  esac
}

main() {
  show_program_info
  require_root
  require_cmd "$PYTHON_BIN"
  require_cmd systemctl
  require_cmd grep
  require_cmd chmod

  local action="${1:-}"
  if [[ -z "$action" ]]; then
    prompt_action
    action="$SELECTED_ACTION"
  fi

  case "$action" in
    install)
      install_flow
      ;;
    uninstall)
      uninstall_flow
      ;;
    *)
      err "Unknown action: $action"
      err "Use: ./scripts/install_service.sh [install|uninstall]"
      exit 1
      ;;
  esac
}

main "$@"
