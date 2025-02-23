from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from zeep import Client
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
import uvicorn
import json
import os


# Instancia de FastAPI
app = FastAPI()

# Variables de configuración
ObjClienteServicio = Client('https://scmsdinwcf.mxappsqa.siemens.cloud/ServiceCDIN.svc?wsdl')
NumeroCliente = '0040011739'
ArrBytesKey = bytes(
    [234, 158, 85, 45, 177, 188, 141, 223, 139, 93, 161, 26, 190, 189, 165, 39, 87, 141, 83, 164, 172, 90, 146, 132, 7,
     25, 167, 70, 202, 184, 24, 89])
ArrBytesIv = bytes([130, 202, 183, 106, 180, 87, 144, 76, 119, 2, 80, 225, 171, 165, 208, 122])


# Modelo de entrada para el array de objetos
class InventoryItem(BaseModel):
    CustomerNumberSAP: str
    ProductoId: str
    PartNumber: str
    NetExistence: float
    StoreLocation: str
    StoreName: str
    DateExtraction: str  # Podríamos validarlo como datetime, pero lo dejaremos como string


# Función para cifrar datos con AES
def CifradoAES(ParamDatos, ParamKey, ParamIv):
    ObjPadder = padding.PKCS7(128).padder()
    Padded_data = ObjPadder.update(ParamDatos)
    Padded_data += ObjPadder.finalize()

    ObjCipher = Cipher(algorithms.AES(ParamKey), modes.CBC(ParamIv), backend=default_backend())
    ObjEncryptor = ObjCipher.encryptor()
    TextoCifrado = ObjEncryptor.update(Padded_data) + ObjEncryptor.finalize()
    return TextoCifrado


# Endpoint para recibir el array de inventarios
@app.post("/send-inventory/")
def send_inventory(inventory: List[InventoryItem]):
    try:
        # Convertir la lista de objetos a JSON string
        CadenaJSON = json.dumps([item.dict() for item in inventory])

        # Convertir a bytes y cifrar
        CadenaJSONCodificada = CadenaJSON.encode('utf-8')
        CadenaJSONCifrada = CifradoAES(CadenaJSONCodificada, ArrBytesKey, ArrBytesIv)

        # Llamar al servicio SOAP
        ResultadoServicio = ObjClienteServicio.service.RegisterPartnerInventoryT(NumeroCliente, CadenaJSONCifrada)

        return {"status": "success", "response": ResultadoServicio}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Ejecutar el servidor
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
