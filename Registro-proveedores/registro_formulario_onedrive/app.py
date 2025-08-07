
import os
import msal
import requests
from flask import Flask, request, render_template, redirect

app = Flask(__name__)

# Configuración MSAL
CLIENT_ID = os.getenv("CLIENT_ID", "TU_CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "TU_CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID", "TU_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]

app_msal = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=AUTHORITY
)

def obtener_token_acceso():
    result = app_msal.acquire_token_silent(SCOPE, account=None)
    if not result:
        result = app_msal.acquire_token_for_client(scopes=SCOPE)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Error al obtener token: {result.get('error_description')}")

def subir_archivo_a_onedrive(nombre_archivo, contenido):
    token = obtener_token_acceso()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/octet-stream'
    }
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/Registro/{nombre_archivo}:/content"
    response = requests.put(url, headers=headers, data=contenido)
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Error al subir archivo: {response.status_code} - {response.text}")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if archivo:
            contenido = archivo.read()
            nombre = archivo.filename
            subir_archivo_a_onedrive(nombre, contenido)
            return "Archivo subido correctamente"
    return '''
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="archivo">
            <input type="submit" value="Subir a OneDrive">
        </form>
    '''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
