import os
from ast import literal_eval
import time
import xmlrpc.client
import json
import logging
from datetime import datetime
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from zeep import Client

# Configurar logging para Railway (envía todo a stdout)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Solo usar StreamHandler para enviar logs a stdout
    ]
)
logger = logging.getLogger(__name__)

# Datos de conexión a Odoo
ODOO_CONFIG = {
    'url': os.getenv('ODOO_URL'),
    'db': os.getenv('ODOO_DB'),
    'username': os.getenv('ODOO_USERNAME'),
    'password': os.getenv('ODOO_PASSWORD')
}

# Datos para el servicio SOAP
SOAP_CONFIG = {
    'wsdl_url': os.getenv('SOAP_WSDL_URL'),
    'numero_cliente': os.getenv('SOAP_NUMERO_CLIENTE'),
    'bytes_key': bytes(literal_eval(os.getenv('SOAP_BYTES_KEY'))),
    'bytes_iv': bytes(literal_eval(os.getenv('SOAP_BYTES_IV')))
}

# Lista de IDs de categorías
CATEGORIAS_IDS = [61, 58, 64, 59, 82, 77, 109, 73]


# Función para cifrar datos con AES
def cifrado_aes(datos, key, iv):
    try:
        obj_padder = padding.PKCS7(128).padder()
        padded_data = obj_padder.update(datos)
        padded_data += obj_padder.finalize()

        obj_cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        obj_encryptor = obj_cipher.encryptor()
        texto_cifrado = obj_encryptor.update(padded_data) + obj_encryptor.finalize()

        return texto_cifrado
    except Exception as e:
        logger.error(f"Error en cifrado AES: {str(e)}")
        raise


# Función para conectar a Odoo
def conectar_odoo():
    try:
        common = xmlrpc.client.ServerProxy(f"{ODOO_CONFIG['url']}/xmlrpc/2/common")
        uid = common.authenticate(
            ODOO_CONFIG['db'],
            ODOO_CONFIG['username'],
            ODOO_CONFIG['password'],
            {}
        )
        models = xmlrpc.client.ServerProxy(f"{ODOO_CONFIG['url']}/xmlrpc/2/object")

        return uid, models
    except Exception as e:
        logger.error(f"Error al conectar con Odoo: {str(e)}")
        raise


# Función para consultar productos de una categoría y enviar datos
def consultar_y_enviar(categoria_id):
    logger.info(f"Iniciando consulta para categoría ID: {categoria_id}")

    try:
        # Conectar a Odoo
        uid, models = conectar_odoo()

        # Definir el dominio para filtrar por categoría específica y productos con existencia
        domain = [('categ_id', '=', categoria_id), ('qty_available', '>', 0)]
        fields = ['name', 'default_code', 'qty_available']

        # Realizar la búsqueda en Odoo
        products = models.execute_kw(
            ODOO_CONFIG['db'],
            uid,
            ODOO_CONFIG['password'],
            'product.product',
            'search_read',
            [domain],
            {'fields': fields}
        )

        logger.info(f"Encontrados {len(products)} productos con existencia en categoría {categoria_id}")

        if not products:
            logger.info(f"No hay productos con existencia en la categoría {categoria_id}")
            return

        # Preparar los datos para enviar
        inventory = []
        for product in products:
            item = {
                "CustomerNumberSAP": SOAP_CONFIG['numero_cliente'],
                "ProductoId": product['default_code'],
                "PartNumber": product['default_code'],
                "NetExistence": product['qty_available'],
                "StoreLocation": "GUADALAJARA, JALISCO",
                "StoreName": "PRUEBA",
                "DateExtraction": datetime.now().isoformat()
            }
            inventory.append(item)

        # Convertir la lista de objetos a JSON string
        cadena_json = json.dumps(inventory)

        # Convertir a bytes y cifrar
        cadena_json_codificada = cadena_json.encode('utf-8')
        cadena_json_cifrada = cifrado_aes(
            cadena_json_codificada,
            SOAP_CONFIG['bytes_key'],
            SOAP_CONFIG['bytes_iv']
        )

        # Llamar al servicio SOAP
        cliente_servicio = Client(SOAP_CONFIG['wsdl_url'])
        resultado_servicio = cliente_servicio.service.RegisterPartnerInventoryT(
            SOAP_CONFIG['numero_cliente'],
            cadena_json_cifrada
        )

        log_event("SYNC_SUCCESS", f"Sincronización exitosa para categoría {categoria_id}",
                  {"category_id": categoria_id, "products_count": len(products)})

        logger.info(f"Datos enviados para la categoría {categoria_id}. Resultado: {resultado_servicio}")

    except Exception as e:
        log_event("SYNC_ERROR", f"Error al procesar la categoría {categoria_id}",
                  {"category_id": categoria_id, "error": str(e)})
        logger.error(f"Error al procesar la categoría {categoria_id}: {str(e)}")


def log_event(event_type, message, extra=None):
    """
    Función para registrar eventos en un formato que Railway pueda procesar fácilmente.
    """
    log_data = {
        "event": event_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }

    if extra:
        log_data.update(extra)

    # Imprimir como JSON para mejor procesamiento en Railway
    print(json.dumps(log_data))


# Función para programar las tareas con intervalos de 20 minutos
# def programar_tareas_diarias():
#     logger.info("Programando tareas diarias")
#
#     # Limpiar todas las tareas programadas anteriormente
#     schedule.clear()
#
#     # Programar cada categoría con un intervalo de 20 minutos
#     for i, categoria_id in enumerate(CATEGORIAS_IDS):
#         # Calcular el tiempo de ejecución (cada 20 minutos)
#         minutos = i * 20
#         hora = minutos // 60
#         minuto = minutos % 60
#
#         tiempo_ejecucion = f"{hora:02d}:{minuto:02d}"
#         logger.info(f"Programando categoría {categoria_id} para ejecutarse a las {tiempo_ejecucion}")
#
#         # Programar la tarea a una hora específica
#         schedule.every().day.at(tiempo_ejecucion).do(consultar_y_enviar, categoria_id=categoria_id)
#
#     # Programar la función para reprogramar las tareas al día siguiente
#     schedule.every().day.at("00:00").do(programar_tareas_diarias).tag('daily')


# Función principal
# def main():
#     try:
#         log_event("SERVICE_START", "Iniciando servicio de sincronización de inventario")
#         logger.info("Iniciando servicio de sincronización de inventario")
#
#         # Programar las tareas iniciales
#         programar_tareas_diarias()
#
#         # Bucle principal para ejecutar las tareas programadas
#         while True:
#             schedule.run_pending()
#             time.sleep(60)  # Verificar cada minuto en lugar de cada segundo para reducir carga
#
#     except KeyboardInterrupt:
#         logger.info("Servicio detenido por el usuario")
#     except Exception as e:
#         logger.error(f"Error en el servicio principal: {str(e)}")
#         raise

def main():
    try:
        while True:
            for categoria_id in CATEGORIAS_IDS:
                logger.info(f"Ejecutando categoría {categoria_id}")
                consultar_y_enviar(categoria_id)
                logger.info(f"Termino categoría {categoria_id}, esperando 20m")
                # Esperar 20 minutos (1200 segundos)
                time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Servicio detenido por el usuario")
    except Exception as e:
        logger.error(f"Error en el servicio principal: {str(e)}")
        raise


if __name__ == "__main__":
    logger.info("Iniciando main.py...")
    main()