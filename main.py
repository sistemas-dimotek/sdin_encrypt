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


# Función para consultar productos de todas las categorías y enviar datos en un solo lote
def consultar_y_enviar_todas_categorias():
    logger.info(f"Iniciando consulta para todas las categorías: {CATEGORIAS_IDS}")

    try:
        # Conectar a Odoo
        uid, models = conectar_odoo()

        # Lista para almacenar todos los productos de todas las categorías
        all_inventory = []
        total_products = 0

        # Iterar sobre cada categoría para obtener sus productos
        for categoria_id in CATEGORIAS_IDS:
            logger.info(f"Consultando productos para categoría ID: {categoria_id}")

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

            # Preparar los datos para cada producto
            for product in products:
                item = {
                    "CustomerNumberSAP": SOAP_CONFIG['numero_cliente'],
                    "ProductoId": product['default_code'],
                    "PartNumber": product['default_code'],
                    "NetExistence": product['qty_available'],
                    "StoreLocation": "QUERETARO, QUERETARO",
                    "StoreName": "CEDIS QUERETARO",
                    "DateExtraction": datetime.now().isoformat()
                }
                all_inventory.append(item)

            total_products += len(products)

        # Verificar si hay productos para enviar
        if not all_inventory:
            logger.info("No hay productos con existencia en ninguna categoría")
            return

        logger.info(f"Total de productos recopilados de todas las categorías: {total_products}")

        # Convertir la lista completa de objetos a JSON string
        cadena_json = json.dumps(all_inventory)

        # Convertir a bytes y cifrar
        cadena_json_codificada = cadena_json.encode('utf-8')
        cadena_json_cifrada = cifrado_aes(
            cadena_json_codificada,
            SOAP_CONFIG['bytes_key'],
            SOAP_CONFIG['bytes_iv']
        )

        # Llamar al servicio SOAP una sola vez con todos los datos
        cliente_servicio = Client(SOAP_CONFIG['wsdl_url'])
        resultado_servicio = cliente_servicio.service.RegisterPartnerInventoryT(
            SOAP_CONFIG['numero_cliente'],
            cadena_json_cifrada
        )

        log_event("SYNC_SUCCESS", f"Sincronización exitosa para todas las categorías",
                  {"categories": CATEGORIAS_IDS, "products_count": total_products})

        logger.info(f"Datos enviados para todas las categorías. Resultado: {resultado_servicio}")

    except Exception as e:
        log_event("SYNC_ERROR", f"Error al procesar las categorías",
                  {"categories": CATEGORIAS_IDS, "error": str(e)})
        logger.error(f"Error al procesar las categorías: {str(e)}")


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


def main():
    try:
        logger.info("Iniciando servicio de sincronización de inventario")
        log_event("SERVICE_START", "Iniciando servicio de sincronización de inventario")

        # Ejecutar la consulta y envío de todas las categorías en un solo lote
        consultar_y_enviar_todas_categorias()

        logger.info("Proceso completado, deteniendo servicio")
        log_event("SERVICE_COMPLETE", "Proceso de sincronización completado")

    except KeyboardInterrupt:
        logger.info("Servicio detenido por el usuario")
    except Exception as e:
        logger.error(f"Error en el servicio principal: {str(e)}")
        raise


if __name__ == "__main__":
    logger.info("Iniciando main.py...")
    main()