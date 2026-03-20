import os
import requests
import time
import urllib3
import json
from urllib.parse import quote_plus
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

# Carga variables definidas en .env al entorno del proceso.
# Si una variable ya existe en el entorno del sistema, se respeta ese valor.
load_dotenv()

# Tiempo maximo (segundos) para cada request HTTP hacia QRadar.
# Evita que el proceso quede bloqueado indefinidamente por problemas de red.
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))

# Espera (segundos) entre cada consulta de estado del search en QRadar.
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 2))

# Limite de intentos de polling para cortar busquedas que nunca terminan.
MAX_POLL_ATTEMPTS = int(os.getenv("MAX_POLL_ATTEMPTS", 120))

# Parametros de conexion a QRadar.
QRADAR_IP = os.getenv("QRADAR_IP")
SEC_TOKEN = os.getenv("QRADAR_TOKEN")

# Parametros de conexion y destino en MongoDB.
MONGO_URI = os.getenv("MONGO_URI")
MONGO_HOST = os.getenv("MONGO_HOST")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")
MONGO_PARAMS = os.getenv("MONGO_PARAMS")
DB_NAME = os.getenv("MONGO_DB")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION")

# Ventana de tiempo (en minutos) usada por la consulta AQL.
MINUTOS_INTERVALO = int(os.getenv("MINUTOS_INTERVALO", 60))

# Controla si se genera un TXT de prueba por cada corrida.
# En productivo dejar en false para deshabilitarlo facilmente.
DEBUG_EXPORT_TXT = os.getenv("DEBUG_EXPORT_TXT", "false").strip().lower() == "true"
DEBUG_TXT_FILE = os.getenv("DEBUG_TXT_FILE", "debug_qradar_output.txt")

# El script hoy consulta con verify=False, por eso se silencian warnings TLS.
# Nota: en produccion es mejor usar certificados validos y verify=True.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def validate_required_env():
    # Diccionario de variables obligatorias para que el script funcione.
    required = {
        "QRADAR_IP": QRADAR_IP,
        "QRADAR_TOKEN": SEC_TOKEN,
        "MONGO_DB": DB_NAME,
        "MONGO_COLLECTION": COLLECTION_NAME,
    }

    # Se identifica cuales vienen vacias o no definidas.
    missing = [key for key, value in required.items() if not value]

    # Si falta alguna, se aborta antes de hacer llamadas remotas.
    if missing:
        raise ValueError(f"Faltan variables de entorno requeridas: {', '.join(missing)}")

    # Valida credenciales de Mongo por cualquiera de los dos modos soportados.
    get_mongo_uri()


def get_mongo_uri():
    # Si hay usuario/password definidos, se prioriza modo por variables separadas.
    # Esto evita errores cuando MONGO_URI apunta a localhost sin auth.
    use_separate_credentials = bool(MONGO_USER or MONGO_PASSWORD)

    # Modo 1 (preferido): URI completa provista por entorno.
    if MONGO_URI and not use_separate_credentials:
        return MONGO_URI

    # Modo 2: construccion desde variables separadas.
    if not MONGO_HOST:
        raise ValueError("Debe definir MONGO_URI o MONGO_HOST para conectar a MongoDB")

    if (MONGO_USER and not MONGO_PASSWORD) or (MONGO_PASSWORD and not MONGO_USER):
        raise ValueError("Debe definir ambos MONGO_USER y MONGO_PASSWORD, o ninguno")

    auth_part = ""
    if MONGO_USER and MONGO_PASSWORD:
        auth_part = f"{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}@"

    query_parts = []
    if MONGO_AUTH_SOURCE:
        query_parts.append(f"authSource={quote_plus(MONGO_AUTH_SOURCE)}")
    if MONGO_PARAMS:
        query_parts.append(MONGO_PARAMS.lstrip("?"))
    query_string = f"?{'&'.join(query_parts)}" if query_parts else ""

    return f"mongodb://{auth_part}{MONGO_HOST}:{MONGO_PORT}/{query_string}"


def request_json(response):
    # Si QRadar responde 4xx/5xx, se lanza excepcion inmediatamente.
    response.raise_for_status()

    # Devuelve el body parseado como JSON para consumo del flujo principal.
    return response.json()


def calculate_eps(total_eventos, minutos_intervalo):
    # Convierte la ventana de minutos a segundos para obtener EPS real.
    segundos_ventana = minutos_intervalo * 60
    if segundos_ventana <= 0:
        raise ValueError("MINUTOS_INTERVALO debe ser mayor que 0")

    # EPS entero: se redondea al entero mas cercano.
    # Si el resultado es 0, se fuerza a 1 por requisito operativo.
    eps_entero = int(round(total_eventos / segundos_ventana))
    return max(1, eps_entero)


def export_debug_txt(documentos):
    # Export opcional de los documentos para validar rapidamente salida.
    # Cada linea se escribe en JSON para facilitar lectura y diff.
    if not DEBUG_EXPORT_TXT:
        return

    with open(DEBUG_TXT_FILE, "w", encoding="utf-8") as f:
        for doc in documentos:
            doc_copy = doc.copy()
            if isinstance(doc_copy.get("fecha"), datetime):
                doc_copy["fecha"] = doc_copy["fecha"].isoformat()
            f.write(json.dumps(doc_copy, ensure_ascii=True) + "\n")


def sync_qradar_to_mongo():
    # Validacion temprana para evitar errores ambiguos mas adelante.
    validate_required_env()

    mongo_uri = get_mongo_uri()

    # 1) Consulta AQL: cuenta eventos por dominio en una ventana de tiempo.
    #    metric  -> nombre del dominio
    #    value   -> total de eventos para ese dominio
    aql_query = f"SELECT DOMAINNAME(domainid) AS metric, LONG(COUNT(*)) AS value FROM events GROUP BY domainid LAST {MINUTOS_INTERVALO} MINUTES"
    
    # Header SEC requerido por API Ariel y formato de respuesta JSON.
    headers = {"SEC": SEC_TOKEN, "Accept": "application/json"}

    # Endpoint base para crear y consultar busquedas Ariel.
    base_url = f"https://{QRADAR_IP}/api/ariel/searches"

    try:
        # 2) Envia la consulta AQL y obtiene search_id.
        #    search_id es el identificador que QRadar entrega para consultar estado/resultados.
        res = requests.post(
            base_url,
            headers=headers,
            params={"query_expression": aql_query},
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )
        search_id = request_json(res).get("search_id")

        # Sin search_id no se puede continuar con polling ni resultados.
        if not search_id:
            raise RuntimeError("QRadar no devolvio search_id para la consulta AQL")

        # 3) Polling de estado hasta COMPLETED, ERROR o timeout logico.
        #    Se limita con MAX_POLL_ATTEMPTS para evitar ciclos infinitos.
        for _ in range(MAX_POLL_ATTEMPTS):
            status_res = request_json(
                requests.get(
                    f"{base_url}/{search_id}",
                    headers=headers,
                    verify=False,
                    timeout=REQUEST_TIMEOUT,
                )
            )

            # Valores comunes esperados: WAIT, EXECUTE, SORTING, COMPLETED, ERROR.
            status = status_res.get("status")
            if status == "COMPLETED":
                break
            if status == "ERROR":
                raise RuntimeError("QRadar devolvio estado ERROR en la busqueda")

            # Espera entre consultas para no sobrecargar el endpoint.
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            # Este else del for se ejecuta solo si no hubo break.
            raise TimeoutError("No se completo la busqueda de QRadar dentro del tiempo esperado")

        # 4) Descarga resultados finales de la busqueda completada.
        results = request_json(
            requests.get(
                f"{base_url}/{search_id}/results",
                headers=headers,
                verify=False,
                timeout=REQUEST_TIMEOUT,
            )
        )
        
        # 5) Conexion a Mongo y preparacion de documentos de salida.
        client = MongoClient(mongo_uri)
        col = client[DB_NAME][COLLECTION_NAME]
        
        # Marca temporal compartida por todos los documentos de esta corrida.
        ahora = datetime.now()

        # Lista batch para insertar en una sola operacion (insert_many).
        documentos = []

        # Recorre cada fila devuelta por QRadar.
        for row in results.get('events', []):
            # Total de eventos del dominio en la ventana consultada.
            total_eventos = int(row['value'])

            # EPS entero por ventana real; minimo permitido = 1.
            eps_calculado = calculate_eps(total_eventos, MINUTOS_INTERVALO)
            
            # Documento final que se persiste en MongoDB.
            documentos.append({
                # Si QRadar no trae dominio, se etiqueta como Default Domain.
                "cliente": row['metric'] if row['metric'] else "Default Domain",
                "eventos_totales": total_eventos,
                "eps": eps_calculado,
                "fecha": ahora,
                "dia": ahora.strftime("%Y-%m-%d"),
                "hora": ahora.strftime("%H:00")
            })

        # Export de prueba opcional a TXT; util para validar conversion antes de productivo.
        export_debug_txt(documentos)

        # Inserta lote solo si hubo resultados.
        if documentos:
            col.insert_many(documentos)
            print(f"Sincronizacion exitosa: {len(documentos)} clientes actualizados.")
        else:
            print("Sin datos para insertar en MongoDB.")

        # Cierre explicito del cliente para liberar recursos.
        client.close()

    except Exception as e:
        # Cualquier error del flujo se reporta de forma controlada.
        print(f"Error: {e}")


# Punto de entrada cuando el archivo se ejecuta como script directo.
if __name__ == "__main__":
    sync_qradar_to_mongo()