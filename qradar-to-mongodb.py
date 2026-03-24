import os
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
    
    print(f"\n>>> TAREA: {task_id} [{task_type}] (QRadar: {qradar_name})")

    try:
        data = []
        # --- OBTENCIÓN DE DATOS ---
        if task_type == "aql":
            query = f"{task.get('aql')} LAST {interval} MINUTES"
            base = f"https://{qr_ip}/api/ariel/searches"
            res = requests.post(base, headers=headers, params={"query_expression": query}, verify=False, timeout=REQUEST_TIMEOUT)
            sid = request_json(res).get("search_id")
            for _ in range(MAX_POLL_ATTEMPTS):
                st = request_json(requests.get(f"{base}/{sid}", headers=headers, verify=False, timeout=REQUEST_TIMEOUT)).get("status")
                if st == "COMPLETED": break
                if st == "ERROR": raise RuntimeError("Ariel Search Error")
                time.sleep(POLL_INTERVAL_SECONDS)
            res_data = request_json(requests.get(f"{base}/{sid}/results", headers=headers, verify=False, timeout=REQUEST_TIMEOUT))
            data = res_data.get('events', [])
            
        elif task_type == "rest_api":
            url = f"https://{qr_ip}{task.get('endpoint')}"
            res = requests.get(url, headers=headers, params=task.get("params", {}), verify=False, timeout=REQUEST_TIMEOUT)
            data = request_json(res)
            if not isinstance(data, list): data = [data]

        # --- CARGA A MONGODB ---
        if data:
            client = MongoClient(mongo_uri)
            col = client[DB_NAME][collection_name]
            
            # Borrado previo si el usuario lo solicita (sobrescritura por instancia)
            if task.get("clear_before_sync"):
                print(f"Limpiando registros previos de '{qradar_name}' en '{collection_name}'...")
                col.delete_many({"qradar_source": qradar_name})

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
                        # Normalizar si el campo mapeado es cliente o dominio
                        if db_key in ["cliente", "dominio_id", "dominio"]:
                            val = normalize_domain_field(val, task, qradar)
                        doc[db_key] = val
                
                if task.get("calculate_eps") and task_type == "aql":
                    c_f = next((v for k, v in mapping.items() if "total" in v or "eventos" in v), None)
                    if c_f and c_f in doc:
                        doc["eps"] = calculate_eps(int(doc[c_f]), interval)
                docs.append(doc)
            
            col.insert_many(docs)
            print(f"Éxito: {len(docs)} registros insertados.")
            client.close()
        else:
            print("Sin datos en este ciclo.")

    except Exception as e:
        print(f"FALLA EN TAREA '{task_id}': {e}")

def run_sync_cycle(target_task_id=None):
    validate_env_basic()
    qradars = load_qradars()
    m_uri = get_mongo_uri()
    
    with open(os.path.join(os.path.dirname(__file__), "queries.json"), "r", encoding="utf-8") as f:
        tasks = json.load(f)

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
                    continue
                
            task_headers = headers.copy()
            if "headers" in t:
                task_headers.update(t["headers"])
            
            process_task(t, task_headers, qr["ip"], m_uri, qr)
            LAST_RUNS[qr_n][t_id] = datetime.now()

def validate_env_basic():
    if not DB_NAME: raise ValueError("Falta MONGO_DB en .env")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QRadar to MongoDB Sync")
    parser.add_argument("--task", help="Ejecuta solo la tarea indicada (ej: offenses_sync) de inmediato", default=None)
    args = parser.parse_args()

    if args.task:
        print(f"Modo forzado: Ejecutando ÚNICAMENTE la tarea '{args.task}'")
        run_sync_cycle(target_task_id=args.task)
    elif not RUN_CONTINUOUS:
        run_sync_cycle()
    else:
        print(f"MOTOR ACTIVO - Ciclo: {RUN_INTERVAL_SECONDS}s")
        while True:
            try:
                run_sync_cycle()
            except KeyboardInterrupt: break
            except Exception as e: print(f"Error ciclo: {e}")
            time.sleep(RUN_INTERVAL_SECONDS)
