import os
import atexit
import logging
import logging.handlers
import signal
import sys
import traceback
import requests
import time
import urllib3
import json
import argparse
from urllib.parse import quote_plus
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, ServerSelectionTimeoutError

# =============================================================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# =============================================================================

# Carga variables definidas en el archivo .env al entorno del proceso actual.
load_dotenv()

# Tiempos y reintentos para requests HTTP
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 2))
MAX_POLL_ATTEMPTS = int(os.getenv("MAX_POLL_ATTEMPTS", 120))

# Configuración de destino en MongoDB
MONGO_URI = os.getenv("MONGO_URI")
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")
MONGO_PARAMS = os.getenv("MONGO_PARAMS")
DB_NAME = os.getenv("MONGO_DB")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION")

# Intervalo global de sincronización (fallback)
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", 60))

# Zona horaria y Depuración
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Santiago")
DEBUG_EXPORT_TXT = os.getenv("DEBUG_EXPORT_TXT", "false").strip().lower() == "true"
DEBUG_TXT_FILE = os.getenv("DEBUG_TXT_FILE", "debug_qradar_output.txt")

# Control de ejecución continua
RUN_CONTINUOUS = os.getenv("RUN_CONTINUOUS", "false").strip().lower() == "true"
RUN_INTERVAL_SECONDS = int(os.getenv("RUN_INTERVAL_SECONDS", 60))

# Configuración de logging
LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE      = os.getenv("LOG_FILE", "")        # vacío = solo consola
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", 5 * 1024 * 1024))  # 5 MB por defecto
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 5))          # 5 archivos de rotación

_log_fmt  = "%(asctime)s [%(levelname)s] %(message)s"
_log_date = "%Y-%m-%d %H:%M:%S"
_log_handlers = [logging.StreamHandler()]
if LOG_FILE:
    _file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(_log_fmt, _log_date))
    _log_handlers.append(_file_handler)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=_log_fmt,
    datefmt=_log_date,
    handlers=_log_handlers,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Manejadores de salida y señales: detectar crashes y apagados
# ---------------------------------------------------------------------------
def _on_exit():
    log.info("Proceso terminado (PID %d)", os.getpid())

def _on_sigterm(signum, frame):  # noqa: ARG001
    log.warning("Recibida señal SIGTERM — apagando limpiamente...")
    sys.exit(0)

def _on_uncaught_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    log.critical("EXCEPCIÓN NO CAPTURADA — el proceso va a terminar:\n%s",
                 "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

atexit.register(_on_exit)
try:
    signal.signal(signal.SIGTERM, _on_sigterm)
except (OSError, ValueError):
    pass  # Windows o entorno sin señales POSIX
sys.excepthook = _on_uncaught_exception

# Silenciar advertencias de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Rastreo de última ejecución por tarea e instancia (para intervalos independientes).
# { "qradar_name": { "task_id": last_datetime } }
LAST_RUNS = {}

# =============================================================================
# FUNCIONES DE SOPORTE
# =============================================================================

def load_qradars():
    qradars = []
    n = 1
    while True:
        ip = os.getenv(f"QRADAR_{n}_IP")
        if not ip: break
        token = os.getenv(f"QRADAR_{n}_TOKEN")
        if not token: raise ValueError(f"Falta QRADAR_{n}_TOKEN")
        name = os.getenv(f"QRADAR_{n}_NAME", f"qradar_{n}")
        qradars.append({
            "name": name, "ip": ip, "token": token,
            "default_domain_alias": os.getenv(f"QRADAR_{n}_DEFAULT_DOMAIN_ALIAS")
        })
        log.info("QRadar cargado: %s (%s)", name, ip)
        n += 1
    if not qradars: raise ValueError("No hay QRadar configurados.")
    return qradars

def get_mongo_uri():
    use_separate_credentials = bool(MONGO_USER or MONGO_PASSWORD)
    if MONGO_URI and not use_separate_credentials: return MONGO_URI
    if not MONGO_HOST: raise ValueError("Falta configuración de MongoDB")
    auth_part = f"{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}@" if MONGO_USER else ""
    query = f"?authSource={quote_plus(MONGO_AUTH_SOURCE)}" if MONGO_USER else ""
    if MONGO_PARAMS: query += f"&{MONGO_PARAMS.lstrip('?')}" if query else f"?{MONGO_PARAMS.lstrip('?')}"
    return f"mongodb://{auth_part}{MONGO_HOST}:{MONGO_PORT}/{query}"

def request_json(response):
    response.raise_for_status()
    return response.json()

def get_time_context():
    tz = ZoneInfo(APP_TIMEZONE)
    now_utc = datetime.now(timezone.utc)
    return now_utc, now_utc.astimezone(tz)

def calculate_eps(total_eventos, minutos):
    segundos = minutos * 60
    return max(1, int(round(total_eventos / segundos))) if segundos > 0 else 0

def normalize_domain_field(val, task, qradar):
    """
    Traduce domain_id numérico usando el mapeo x instancia en queries.json.
    Si no hay mapeo, intenta usar el alias global de 'Default Domain' si aplica.
    """
    qradar_name = qradar["name"]
    val_str = str(val)
    
    # 1. Intentar mapeo específico por instancia en queries.json
    mapping = task.get("domain_mapping", {}).get(qradar_name, {})
    if val_str in mapping:
        return mapping[val_str]
    
    # 2. Fallback: Si es el ID de dominio por defecto (usualmente "Default Domain" en texto o ID 0)
    # y el usuario definió un alias en el .env
    if val_str == "Default Domain" or val_str == "0":
        return qradar.get("default_domain_alias") or qradar_name
        
    return val

# =============================================================================
# MOTOR DE TAREAS
# =============================================================================

def process_task(task, headers, qr_ip, mongo_uri, qradar):
    task_id = task.get("id", "unnamed")
    task_type = task.get("type", "aql").lower()
    qradar_name = qradar["name"]
    collection_name = task.get("collection", COLLECTION_NAME or "default_col")
    mapping = task.get("mapping", {})
    interval = int(task.get("interval_minutes", SYNC_INTERVAL_MINUTES))
    
    log.info("--- INICIO TAREA: %s [%s] (QRadar: %s) ---", task_id, task_type, qradar_name)
    t_start = time.monotonic()

    try:
        data = []
        # --- OBTENCIÓN DE DATOS ---
        if task_type == "aql":
            query = f"{task.get('aql')} LAST {interval} MINUTES"
            base = f"https://{qr_ip}/api/ariel/searches"
            log.debug("AQL enviado: %s", query)
            res = requests.post(base, headers=headers, params={"query_expression": query}, verify=False, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            sid = res.json().get("search_id")
            log.debug("Search ID obtenido: %s", sid)
            for attempt in range(MAX_POLL_ATTEMPTS):
                poll_res = requests.get(f"{base}/{sid}", headers=headers, verify=False, timeout=REQUEST_TIMEOUT)
                poll_res.raise_for_status()
                poll_data = poll_res.json()
                st = poll_data.get("status")
                log.debug("[%s] Intento %d/%d - estado: %s", task_id, attempt + 1, MAX_POLL_ATTEMPTS, st)
                if st == "COMPLETED": break
                if st == "ERROR":
                    raise RuntimeError(f"Ariel Search ID {sid} reportó ERROR: {poll_data}")
                time.sleep(POLL_INTERVAL_SECONDS)
            else:
                raise TimeoutError(f"Ariel Search ID {sid} no completó en {MAX_POLL_ATTEMPTS} intentos")
            res_data = requests.get(f"{base}/{sid}/results", headers=headers, verify=False, timeout=REQUEST_TIMEOUT)
            res_data.raise_for_status()
            data = res_data.json().get('events', [])
            log.info("AQL completado: %d eventos obtenidos", len(data))
            
        elif task_type == "rest_api":
            url = f"https://{qr_ip}{task.get('endpoint')}"
            params = task.get("params", {})
            # Quitar claves informativas que no son filtros reales
            api_params = {k: v for k, v in params.items() if not k.endswith("_note")}
            log.debug("REST API GET %s params=%s", url, api_params)
            res = requests.get(url, headers=headers, params=api_params, verify=False, timeout=REQUEST_TIMEOUT)
            if not res.ok:
                log.error("REST API respondió HTTP %d para tarea '%s': %s", res.status_code, task_id, res.text[:500])
                res.raise_for_status()
            data = res.json()
            if not isinstance(data, list): data = [data]
            log.info("REST API completado: %d registros obtenidos", len(data))

        # --- CARGA A MONGODB ---
        client = MongoClient(mongo_uri)
        col = client[DB_NAME][collection_name]
        
        # Borrado previo independiente de si trajo datos nuevos o no
        if task.get("clear_before_sync"):
            deleted = col.delete_many({"qradar_source": qradar_name})
            log.info("Limpieza previa en '%s': %d documentos eliminados (qradar_source=%s)",
                     collection_name, deleted.deleted_count, qradar_name)

        if data:
            ahora_utc, ahora_local = get_time_context()
            docs = []
            for row in data:
                doc = {
                    "fecha": ahora_utc,
                    "dia": ahora_local.strftime("%Y-%m-%d"),
                    "hora": ahora_local.strftime("%H:00"),
                    "hora_minuto": ahora_local.strftime("%H:%M"),
                    "timezone": APP_TIMEZONE,
                    "qradar_source": qradar_name
                }
                for q_key, db_key in mapping.items():
                    if q_key in row:
                        val = row[q_key]
                        if db_key in ["cliente", "dominio_id", "dominio"]:
                            val = normalize_domain_field(val, task, qradar)
                        doc[db_key] = val
                    else:
                        log.debug("Campo '%s' no encontrado en fila para tarea '%s'", q_key, task_id)
                
                if task.get("calculate_eps") and task_type == "aql":
                    c_f = next((v for k, v in mapping.items() if "total" in v or "eventos" in v), None)
                    if c_f and c_f in doc:
                        doc["eps"] = calculate_eps(int(doc[c_f]), interval)
                docs.append(doc)
            
            # Log de muestra del primer documento para validación
            if docs:
                log.debug("Muestra primer documento: %s", docs[0])
            
            col.insert_many(docs)
            elapsed = time.monotonic() - t_start
            log.info("FIN TAREA %s: %d documentos insertados en '%s' (%.1fs)",
                     task_id, len(docs), collection_name, elapsed)
        else:
            elapsed = time.monotonic() - t_start
            log.warning("FIN TAREA %s: 0 registros devueltos por la consulta (%.1fs)",
                        task_id, elapsed)

        client.close()

    except requests.exceptions.ConnectionError as e:
        log.error("[%s] Sin conexión con QRadar %s: %s", task_id, qr_ip, e)
        log.error(traceback.format_exc())
    except requests.exceptions.HTTPError as e:
        log.error("[%s] Error HTTP desde QRadar: %s", task_id, e)
        log.error(traceback.format_exc())
    except requests.exceptions.Timeout:
        log.error("[%s] Timeout al conectar con QRadar %s (límite: %ds)",
                  task_id, qr_ip, REQUEST_TIMEOUT)
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        log.error("[%s] No se pudo conectar a MongoDB: %s", task_id, e)
        log.error(traceback.format_exc())
    except OperationFailure as e:
        log.error("[%s] Error de operación en MongoDB (¿permisos?): %s", task_id, e)
        log.error(traceback.format_exc())
    except Exception as e:
        log.error("[%s] FALLA INESPERADA: %s", task_id, e)
        log.error(traceback.format_exc())

def run_sync_cycle(target_task_id=None):
    validate_env_basic()
    qradars = load_qradars()
    m_uri = get_mongo_uri()
    cycle_start = time.monotonic()
    log.info("==== INICIO CICLO DE SINCRONIZACIÓN ====")
    
    with open(os.path.join(os.path.dirname(__file__), "queries.json"), "r", encoding="utf-8") as f:
        tasks = json.load(f)
    log.info("%d tarea(s) cargadas desde queries.json", len(tasks))

    tasks_run = 0
    tasks_skipped = 0
    for qr in qradars:
        qr_n = qr["name"]
        if qr_n not in LAST_RUNS: LAST_RUNS[qr_n] = {}
        headers = {"SEC": qr["token"], "Accept": "application/json"}
        
        for t in tasks:
            t_id = t.get("id", "unnamed")
            
            # Filtro por línea de comandos para testing aislado
            if target_task_id and t_id != target_task_id:
                continue
            
            # Si forzamos una tarea, ignoramos la espera. Si no, respetamos el intervalo.
            if not target_task_id:
                interval = int(t.get("interval_minutes", SYNC_INTERVAL_MINUTES))
                last = LAST_RUNS[qr_n].get(t_id)
                ahora = datetime.now()
                
                if last and (ahora - last).total_seconds() < (interval * 60 - 5):
                    remaining = int((interval * 60 - 5) - (ahora - last).total_seconds())
                    log.debug("Tarea '%s' omitida — próxima ejecución en %ds", t_id, remaining)
                    tasks_skipped += 1
                    continue
                
            task_headers = headers.copy()
            if "headers" in t:
                task_headers.update(t["headers"])
            
            process_task(t, task_headers, qr["ip"], m_uri, qr)
            LAST_RUNS[qr_n][t_id] = datetime.now()
            tasks_run += 1

    elapsed = time.monotonic() - cycle_start
    log.info("==== FIN CICLO: %d ejecutadas, %d omitidas (%.1fs) ====",
             tasks_run, tasks_skipped, elapsed)

def validate_env_basic():
    if not DB_NAME: raise ValueError("Falta MONGO_DB en .env")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QRadar to MongoDB Sync")
    parser.add_argument("--task", help="Ejecuta solo la tarea indicada (ej: offenses_sync) de inmediato", default=None)
    args = parser.parse_args()

    log.info("="*60)
    log.info("Iniciando qradar-to-mongodb | PID=%d | LOG_LEVEL=%s | LOG_FILE=%s",
             os.getpid(), LOG_LEVEL, LOG_FILE or "(solo consola)")
    log.info("="*60)

    if args.task:
        log.info("Modo forzado: ejecutando ÚNICAMENTE la tarea '%s'", args.task)
        run_sync_cycle(target_task_id=args.task)
    elif not RUN_CONTINUOUS:
        run_sync_cycle()
    else:
        log.info("MOTOR ACTIVO - Ciclo cada %ds", RUN_INTERVAL_SECONDS)
        while True:
            try:
                run_sync_cycle()
            except KeyboardInterrupt:
                log.info("Detenido por el usuario (KeyboardInterrupt)")
                break
            except Exception as e:
                log.error("Error en ciclo principal: %s\n%s", e, traceback.format_exc())
            time.sleep(RUN_INTERVAL_SECONDS)
