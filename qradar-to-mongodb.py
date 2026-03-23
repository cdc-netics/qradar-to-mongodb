import os
import requests
import time
import urllib3
import json
from urllib.parse import quote_plus
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pymongo import MongoClient

# =============================================================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# =============================================================================

# Carga variables definidas en el archivo .env al entorno del proceso actual.
# Load values from .env file into environment variables.
load_dotenv()

# Tiempo máximo (segundos) para cada request HTTP hacia la API de QRadar.
# Ayuda a evitar que el script quede colgado por problemas de red persistentes.
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))

# Intervalo de espera (en segundos) entre cada consulta de estado (polling) 
# mientras QRadar procesa la búsqueda Ariel.
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 2))

# Límite máximo de intentos de polling. Si la búsqueda no termina tras este 
# número de intentos, el script asume un error o demora excesiva y aborta.
MAX_POLL_ATTEMPTS = int(os.getenv("MAX_POLL_ATTEMPTS", 120))

# La configuración de QRadar ahora se carga dinámicamente desde variables
# QRADAR_1_IP, QRADAR_1_TOKEN, QRADAR_2_IP, QRADAR_2_TOKEN, etc.
# Ver función load_qradars() más abajo.

# Configuración de destino en MongoDB (URI o componentes separados).
MONGO_URI = os.getenv("MONGO_URI")
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")
MONGO_PARAMS = os.getenv("MONGO_PARAMS")
DB_NAME = os.getenv("MONGO_DB")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION")

# Ventana de tiempo (en minutos) para la consulta AQL y frecuencia de ejecución.
# Esta es la única variable necesaria para controlar el ritmo del script.
# Window in minutes for AQL query and sync frequency.
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", os.getenv("MINUTOS_INTERVALO", 60)))

# Zona horaria para los campos 'dia' y 'hora' que se guardan en el documento.
# Esto permite que los reportes en MongoDB coincidan con el horario local de negocio.
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Santiago")

# Opciones de depuración (Debug). Habilitan la exportación de resultados a un archivo TXT plano.
DEBUG_EXPORT_TXT = os.getenv("DEBUG_EXPORT_TXT", "false").strip().lower() == "true"
DEBUG_TXT_FILE = os.getenv("DEBUG_TXT_FILE", "debug_qradar_output.txt")

# Control de ejecución continua (Daemon mode).
# Si es true, el script entra en un bucle infinito consultando periódicamente.
RUN_CONTINUOUS = os.getenv("RUN_CONTINUOUS", "false").strip().lower() == "true"

# Tiempo entre ejecuciones completas en SEGUNDOS.
# Se deriva automáticamente de SYNC_INTERVAL_MINUTES a menos que se fuerce otro valor.
RUN_INTERVAL_SECONDS = int(os.getenv("RUN_INTERVAL_SECONDS", SYNC_INTERVAL_MINUTES * 60))

# Silenciar advertencias de certificados auto-firmados o inválidos (InsecureRequestWarning).
# IMPORTANTE: En producción, use certificados válidos y cambie verify=False a True.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def load_qradars():
    """
    Auto-descubre instancias QRadar desde variables de entorno.
    Busca QRADAR_1_IP, QRADAR_2_IP, ... hasta que no encuentre más.
    Retorna lista de dicts: [{"id": 1, "name": "...", "ip": "...", "token": "..."}]
    """
    qradars = []
    n = 1
    while True:
        ip = os.getenv(f"QRADAR_{n}_IP")
        if not ip:
            break

        token = os.getenv(f"QRADAR_{n}_TOKEN")
        if not token:
            raise ValueError(f"QRADAR_{n}_IP está definido pero falta QRADAR_{n}_TOKEN")

        name = os.getenv(f"QRADAR_{n}_NAME", f"qradar_{n}")

        qradars.append({
            "id": n,
            "name": name,
            "ip": ip,
            "token": token,
        })
        n += 1

    if not qradars:
        raise ValueError(
            "No se encontraron instancias QRadar. "
            "Defina al menos QRADAR_1_IP y QRADAR_1_TOKEN en el archivo .env"
        )

    return qradars


def validate_required_env():
    """
    Verifica que las variables de entorno esenciales estén presentes.
    Lanza ValueError si falta información crítica antes de iniciar el proceso.
    """
    required = {
        "MONGO_DB": DB_NAME,
        "MONGO_COLLECTION": COLLECTION_NAME,
    }

    # Identificar claves nulas o vacías.
    missing = [key for key, value in required.items() if not value]

    if missing:
        raise ValueError(f"Faltan variables de entorno requeridas: {', '.join(missing)}")

    # Validar también que la configuración de MongoDB sea coherente.
    get_mongo_uri()

    # Validar que hay al menos una instancia QRadar configurada.
    load_qradars()


def get_mongo_uri():
    """
    Resuelve la cadena de conexión a MongoDB basándose en las variables de entorno.
    Soporta URI completa (MONGO_URI) o construcción por piezas (USER, PASS, HOST, etc).
    """
    # Si existen credenciales explícitas, se prioriza el modo manual para asegurar auth.
    use_separate_credentials = bool(MONGO_USER or MONGO_PASSWORD)

    # Caso 1: URI completa provista (ej: mongodb+srv://...)
    if MONGO_URI and not use_separate_credentials:
        return MONGO_URI

    # Caso 2: Construcción manual dinámica.
    if not MONGO_HOST:
        raise ValueError("Debe definir MONGO_URI o MONGO_HOST para conectar a MongoDB")

    if (MONGO_USER and not MONGO_PASSWORD) or (MONGO_PASSWORD and not MONGO_USER):
        raise ValueError("Debe definir ambos MONGO_USER y MONGO_PASSWORD, o ninguno")

    auth_part = ""
    if MONGO_USER and MONGO_PASSWORD:
        # quote_plus asegura que caracteres especiales en el password no rompan la URI.
        auth_part = f"{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}@"

    query_parts = []
    if MONGO_AUTH_SOURCE:
        query_parts.append(f"authSource={quote_plus(MONGO_AUTH_SOURCE)}")
    if MONGO_PARAMS:
        query_parts.append(MONGO_PARAMS.lstrip("?"))
    query_string = f"?{'&'.join(query_parts)}" if query_parts else ""

    return f"mongodb://{auth_part}{MONGO_HOST}:{MONGO_PORT}/{query_string}"


def request_json(response):
    """
    Wrapper para procesar respuestas de la API de QRadar.
    Lanza excepción si el código HTTP es 4xx o 5xx.
    """
    response.raise_for_status()
    return response.json()


def calculate_eps(total_eventos, minutos_intervalo):
    """
    Calcula el promedio de Eventos Por Segundo (EPS) basado en el total de eventos
    detectados en una ventana de tiempo específica.
    """
    segundos_ventana = minutos_intervalo * 60
    if segundos_ventana <= 0:
        raise ValueError("MINUTOS_INTERVALO debe ser mayor que 0")

    # EPS = Total de eventos / Segundos totales de la ventana.
    eps_decimal = total_eventos / segundos_ventana
    
    # Redondeo al entero más cercano.
    eps_entero = int(round(eps_decimal))
    
    # REGLA OPERATIVA: El EPS mínimo registrado siempre debe ser 1 si hubo eventos,
    # para evitar que dominios con muy poca carga desaparezcan del monitoreo.
    return max(1, eps_entero)


def export_debug_txt(documentos):
    """
    Exporta los documentos generados a un archivo de texto plano para validación manual.
    Solo se ejecuta si DEBUG_EXPORT_TXT=true.
    """
    if not DEBUG_EXPORT_TXT:
        return

    try:
        with open(DEBUG_TXT_FILE, "w", encoding="utf-8") as f:
            for doc in documentos:
                doc_copy = doc.copy()
                # Serializar objetos datetime a string para el JSON de salida.
                if isinstance(doc_copy.get("fecha"), datetime):
                    doc_copy["fecha"] = doc_copy["fecha"].isoformat()
                f.write(json.dumps(doc_copy, ensure_ascii=True) + "\n")
    except Exception as e:
        print(f"[DEBUG] Error exportando archivo TXT: {e}")


def get_time_context():
    """
    Genera marcas de tiempo tanto en UTC (para MongoDB) como en Hora Local 
    (para campos de negocio y reportes).
    """
    try:
        tz = ZoneInfo(APP_TIMEZONE)
    except Exception as exc:
        raise ValueError(f"Zona horaria inválida en APP_TIMEZONE: {APP_TIMEZONE}") from exc

    now_utc = datetime.now(timezone.utc)
    # Conversión a la zona horaria definida (Chile por defecto).
    now_local = now_utc.astimezone(tz)
    return now_utc, now_local


# --- PASO 5: Motor de Ejecución Multi-Tarea ---

def process_task(task, headers, base_url, mongo_uri, qradar_name):
    """
    Procesa una tarea individual definida en queries.json contra una instancia QRadar.
    """
    task_id = task.get("id", "unnamed_task")
    print(f"\n>>> PROCESANDO TAREA: {task_id} (QRadar: {qradar_name})")
    
    # 1. Preparar Query AQL con el intervalo actual.
    raw_aql = task.get("aql")
    if not raw_aql:
        print(f"Error: Tarea {task_id} no tiene consulta AQL definida.")
        return
    
    aql_query = f"{raw_aql} LAST {SYNC_INTERVAL_MINUTES} MINUTES"
    collection_name = task.get("collection", "default_collection")
    mapping = task.get("mapping", {})
    do_eps = task.get("calculate_eps", False)

    try:
        # --- PASO 1: Iniciar la búsqueda en QRadar ---
        print(f"Enviando consulta AQL a QRadar...")
        res = requests.post(
            base_url,
            headers=headers,
            params={"query_expression": aql_query},
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )
        search_id = request_json(res).get("search_id")

        if not search_id:
            raise RuntimeError("QRadar no devolvió search_id")

        # --- PASO 2: Polling (Esperar a que termine) ---
        for i in range(MAX_POLL_ATTEMPTS):
            status_res = request_json(
                requests.get(
                    f"{base_url}/{search_id}",
                    headers=headers,
                    verify=False,
                    timeout=REQUEST_TIMEOUT,
                )
            )
            status = status_res.get("status")
            if status == "COMPLETED":
                break
            if status == "ERROR":
                raise RuntimeError(f"QRadar devolvió estado ERROR para búsqueda {search_id}")
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            raise TimeoutError(f"Excedido tiempo de espera para búsqueda {search_id}")

        # --- PASO 3: Descargar resultados ---
        results = request_json(
            requests.get(
                f"{base_url}/{search_id}/results",
                headers=headers,
                verify=False,
                timeout=REQUEST_TIMEOUT,
            )
        )
        
        # --- PASO 4: Mapeo dinámico e inserción en MongoDB ---
        client = MongoClient(mongo_uri)
        col = client[DB_NAME][collection_name]
        
        ahora_utc, ahora_local = get_time_context()
        documentos = []

        for row in results.get('events', []):
            # Crear documento base con metadatos de tiempo comunes.
            doc = {
                "fecha": ahora_utc,
                "dia": ahora_local.strftime("%Y-%m-%d"),
                "hora": ahora_local.strftime("%H:00"),
                "hora_minuto": ahora_local.strftime("%H:%M"),
                "timezone": APP_TIMEZONE,
                "qradar_source": qradar_name,
            }

            # Aplicar mapeo de columnas dinámicamente.
            for q_col, db_field in mapping.items():
                if q_col in row:
                    doc[db_field] = row[q_col]
            
            # Lógica especial para EPS si se requiere.
            if do_eps:
                # Intentamos detectar el campo de conteo basándonos en el mapping.
                # Normalmente mapeamos 'value' o 'total' a algo que contenga 'eventos'.
                count_field = next((v for k, v in mapping.items() if "total" in v or "eventos" in v), None)
                if count_field and count_field in doc:
                    total_eventos = int(doc[count_field]) if doc[count_field] else 0
                    doc["eps"] = calculate_eps(total_eventos, SYNC_INTERVAL_MINUTES)

            documentos.append(doc)

        if documentos:
            col.insert_many(documentos)
            print(f"Sincronización exitosa: {len(documentos)} registros insertados en '{collection_name}'.")
            export_debug_txt(documentos)
        else:
            print(f"No se encontraron datos para la tarea {task_id} en este intervalo.")

        client.close()

    except Exception as e:
        print(f"ERROR EN TAREA '{task_id}': {e}")


def run_sync_cycle():
    """
    Coordina un ciclo completo de sincronización para todas las tareas
    contra todas las instancias QRadar configuradas.
    """
    validate_required_env()
    mongo_uri = get_mongo_uri()
    qradars = load_qradars()

    # Cargar catálogo de queries.
    config_path = os.path.join(os.path.dirname(__file__), "queries.json")
    if not os.path.exists(config_path):
        print(f"CRÍTICO: No se encontró el archivo {config_path}")
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
    except Exception as e:
        print(f"Error cargando queries.json: {e}")
        return

    print(f"Instancias QRadar detectadas: {len(qradars)}")

    # Iterar sobre cada instancia QRadar.
    for qr in qradars:
        print(f"\n{'='*60}")
        print(f"CONECTANDO A: {qr['name']} ({qr['ip']})")
        print(f"{'='*60}")

        headers = {"SEC": qr["token"], "Accept": "application/json"}
        base_url = f"https://{qr['ip']}/api/ariel/searches"

        # Ejecutar cada tarea secuencialmente contra esta instancia.
        for task in tasks:
            process_task(task, headers, base_url, mongo_uri, qr["name"])


def run_scheduler():
    """
    Gestiona el ciclo de vida del script: corre una vez o entra en bucle infinito.
    """
    if not RUN_CONTINUOUS:
        run_sync_cycle()
        return

    if RUN_INTERVAL_SECONDS <= 0:
        raise ValueError("RUN_INTERVAL_SECONDS debe ser mayor que 0 para ejecución continua.")

    print("=" * 60)
    print(f"MOTOR MULTI-TAREA ACTIVO - Intervalo: {RUN_INTERVAL_SECONDS} segundos")
    print("=" * 60)

    while True:
        try:
            run_sync_cycle()
        except KeyboardInterrupt:
            print("\nScript detenido por el usuario.")
            break
        except Exception as e:
            print(f"Falla crítica en el ciclo: {e}. Reintentando en el próximo ciclo...")
        
        print(f"\nSiguiente ciclo en {RUN_INTERVAL_SECONDS} segundos...")
        time.sleep(RUN_INTERVAL_SECONDS)


# --- PUNTO DE ENTRADA ---
if __name__ == "__main__":
    run_scheduler()