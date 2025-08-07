
import os
import msal
import requests
from flask import Flask, request, render_template, jsonify

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")  # Carga el archivo HTML desde /templates

# === Configuración MSAL / Graph ===
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
TENANT_ID = os.getenv("TENANT_ID", "")
TARGET_USER_UPN = os.getenv("TARGET_USER_UPN", "")  # ej: "tuusuario@tu-dominio.com"

if not all([CLIENT_ID, CLIENT_SECRET, TENANT_ID, TARGET_USER_UPN]):
    raise RuntimeError("Faltan variables de entorno: CLIENT_ID, CLIENT_SECRET, TENANT_ID, TARGET_USER_UPN")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]  # para client credentials
GRAPH_BASE = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_UPN}/drive"

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
    raise Exception(f"Error al obtener token: {result.get('error')} - {result.get('error_description')}")

def asegurar_carpeta_registro(token):
    """Crea la carpeta 'Registro' si no existe."""
    headers_json = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # ¿Existe?
    resp = requests.get(f"{GRAPH_BASE}/root/children?$filter=name eq 'Registro'", headers=headers_json)
    if resp.status_code == 200:
        items = resp.json().get("value", [])
        if any(i.get("name") == "Registro" and "folder" in i for i in items):
            return  # ya está
    # Crear
    payload = {"name": "Registro", "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
    create = requests.post(f"{GRAPH_BASE}/root/children", headers=headers_json, json=payload)
    if create.status_code not in (200, 201):
        raise Exception(f"No se pudo crear carpeta Registro: {create.status_code} - {create.text}")

def subir_archivo_a_onedrive(nombre_archivo, contenido):
    token = obtener_token_acceso()
    asegurar_carpeta_registro(token)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
    url = f"{GRAPH_BASE}/root:/Registro/{nombre_archivo}:/content"
    resp = requests.put(url, headers=headers, data=contenido)
    if resp.status_code in (200, 201):
        return resp.json()
    raise Exception(f"Error al subir archivo: {resp.status_code} - {resp.text}")

# === RUTA ÚNICA ===
@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "GET":
        # Usa templates/index.html (asegúrate de tener carpeta 'templates' y el archivo dentro)
        return render_template("index.html")

    # POST (sube el archivo)
    archivo = request.files.get("archivo")
    if not archivo or archivo.filename.strip() == "":
        return jsonify({"ok": False, "message": "Debe seleccionar un archivo"}), 400

    try:
        subir_archivo_a_onedrive(archivo.filename, archivo.read())
        return jsonify({"ok": True, "message": "Archivo subido correctamente"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

