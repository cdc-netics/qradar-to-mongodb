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

# Parámetros críticos para conectar con la consola de QRadar.
QRADAR_IP = os.getenv("QRADAR_IP")
SEC_TOKEN = os.getenv("QRADAR_TOKEN")  # Security Token (SEC) generado en QRadar.

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


def validate_required_env():
    """
    Verifica que las variables de entorno esenciales estén presentes.
    Lanza ValueError si falta información crítica antes de iniciar el proceso.
    """
    required = {
        "QRADAR_IP": QRADAR_IP,
        "QRADAR_TOKEN": SEC_TOKEN,
        "MONGO_DB": DB_NAME,
        "MONGO_COLLECTION": COLLECTION_NAME,
    }

    # Identificar claves nulas o vacías.
    missing = [key for key, value in required.items() if not value]

    if missing:
        raise ValueError(f"Faltan variables de entorno requeridas: {', '.join(missing)}")

    # Validar también que la configuración de MongoDB sea coherente.
    get_mongo_uri()


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


def sync_qradar_to_mongo():
    """
    FLUJO PRINCIPAL:
    1. Ejecuta consulta AQL en QRadar Ariel API.
    2. Monitorea el estado de la búsqueda hasta que finalice.
    3. Obtiene los resultados de eventos por dominio.
    4. Procesa y transforma los datos al esquema de MongoDB.
    5. Inserta en lote (batch) los documentos en la base de datos.
    """
    validate_required_env()
    mongo_uri = get_mongo_uri()

    # QUERY AQL: Agrupa eventos por domainid y cuenta cuántos hubo en los últimos N minutos.
    aql_query = (
        f"SELECT DOMAINNAME(domainid) AS metric, LONG(COUNT(*)) AS value "
        f"FROM events GROUP BY domainid LAST {SYNC_INTERVAL_MINUTES} MINUTES"
    )
    
    # Autenticación mediante Header SEC (Security Token).
    headers = {"SEC": SEC_TOKEN, "Accept": "application/json"}
    base_url = f"https://{QRADAR_IP}/api/ariel/searches"

    try:
        # --- PASO 1: Iniciar la búsqueda en QRadar ---
        print(f"[{datetime.now().isoformat()}] Iniciando búsqueda Ariel en QRadar...")
        res = requests.post(
            base_url,
            headers=headers,
            params={"query_expression": aql_query},
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )
        search_id = request_json(res).get("search_id")

        if not search_id:
            raise RuntimeError("QRadar no devolvió search_id para la consulta AQL")

        # --- PASO 2: Polling (Esperar a que termine) ---
        print(f"Búsqueda ID {search_id} en curso. Esperando finalización...")
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
                raise RuntimeError(f"QRadar devolvió estado ERROR para la búsqueda {search_id}")

            # Esperar antes del siguiente intento para no saturar la API de la consola.
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            raise TimeoutError(f"La búsqueda {search_id} excedió {MAX_POLL_ATTEMPTS} intentos de polling.")

        # --- PASO 3: Descargar resultados ---
        print("Búsqueda completada. Descargando resultados...")
        results = request_json(
            requests.get(
                f"{base_url}/{search_id}/results",
                headers=headers,
                verify=False,
                timeout=REQUEST_TIMEOUT,
            )
        )
        
        # --- PASO 4: Procesamiento e inserción en MongoDB ---
        # Conexión persistente para el lote de documentos.
        client = MongoClient(mongo_uri)
        col = client[DB_NAME][COLLECTION_NAME]
        
        # Obtener contexto temporal único para evitar discrepancias de milisegundos entre docs.
        ahora_utc, ahora_local = get_time_context()
        documentos = []

        # results['events'] contiene el array de filas devueltas por la consulta SELECT AQL.
        for row in results.get('events', []):
            total_eventos = int(row['value'])
            eps_calculado = calculate_eps(total_eventos, SYNC_INTERVAL_MINUTES)
            
            # Esquema de documento optimizado para consultas temporales y reportes.
            documentos.append({
                # metric contiene el DOMAINNAME(domainid) calculado en AQL.
                "cliente": row['metric'] if row['metric'] else "Default Domain",
                "eventos_totales": total_eventos,
                "eps": eps_calculado,
                "fecha": ahora_utc,                         # Timestamp ISO UTC (técnico).
                "dia": ahora_local.strftime("%Y-%m-%d"),    # Para filtros por jornada.
                "hora": ahora_local.strftime("%H:00"),      # Para agrupaciones por bloque horario.
                "hora_minuto": ahora_local.strftime("%H:%M"),# Hora exacta de captura.
                "timezone": APP_TIMEZONE,                    # Contexto geográfico.
            })

        # Almacenar copia local si el modo debug está activo.
        export_debug_txt(documentos)

        # Inserción masiva para minimizar el número de operaciones de red hacia MongoDB.
        if documentos:
            col.insert_many(documentos)
            print(f"Sincronización exitosa: {len(documentos)} dominios/clientes procesados.")
        else:
            print("No se encontraron eventos en este intervalo.")

        # Liberación de recursos.
        client.close()

    except Exception as e:
        print(f"ERROR DURANTE EL PROCESO: {e}")


def run_scheduler():
    """
    Gestiona el ciclo de vida del script: corre una vez o entra en bucle infinito
    según la configuración de RUN_CONTINUOUS.
    """
    if not RUN_CONTINUOUS:
        sync_qradar_to_mongo()
        return

    if RUN_INTERVAL_SECONDS <= 0:
        raise ValueError("RUN_INTERVAL_SECONDS debe ser mayor que 0 para ejecución continua.")

    print("=" * 60)
    print(f"MODO CONTINUO ACTIVADO - Intervalo: {RUN_INTERVAL_SECONDS} segundos")
    print("=" * 60)

    while True:
        try:
            sync_qradar_to_mongo()
        except KeyboardInterrupt:
            print("\nScript detenido por el usuario.")
            break
        except Exception as e:
            print(f"Falla crítica en el bucle: {e}. Reintentando en el próximo ciclo...")
        
        print(f"Siguiente ejecución en {RUN_INTERVAL_SECONDS} segundos...")
        time.sleep(RUN_INTERVAL_SECONDS)


# --- PUNTO DE ENTRADA ---
if __name__ == "__main__":
    run_scheduler()