
# app.py
import os
import json
import math
import time
from datetime import datetime
from flask import Flask, request, send_from_directory, jsonify

import msal
import requests

# =========================
# Config Flask
# =========================
# Sirve index.html desde la raíz del proyecto y el logo desde /templates/ (tal como tienes el HTML)
app = Flask(__name__, static_folder=None)

# =========================
# Credenciales Graph por entorno
# =========================
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")

if not all([CLIENT_ID, CLIENT_SECRET, TENANT_ID]):
    print("[AVISO] Faltan variables de entorno: CLIENT_ID / CLIENT_SECRET / TENANT_ID")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/.default"]

# Carpeta base en OneDrive donde se guardará todo
BASE_FOLDER = "Registro"

# =========================
# MSAL App
# =========================
msal_app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=AUTHORITY
)

def get_access_token():
    """Obtiene un access token para Graph (app perms)."""
    result = msal_app.acquire_token_silent(SCOPES, account=None)
    if not result:
        result = msal_app.acquire_token_for_client(scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"Error autenticando con Graph: {result}")
    return result["access_token"]

# =========================
# Utilidades OneDrive / Graph
# =========================
def ensure_folder(path, token):
    """
    Asegura que exista la carpeta root:/path: en OneDrive.
    Si no existe la crea. Devuelve el driveItem.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Intentar obtener
    get_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}"
    r = requests.get(get_url, headers=headers)
    if r.status_code == 200:
        return r.json()
    if r.status_code not in (200, 404):
        r.raise_for_status()

    # Crear (en el padre)
    parent = "/".join(path.split("/")[:-1])
    name = path.split("/")[-1]
    if parent:
        children_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{parent}:/children"
    else:
        children_url = "https://graph.microsoft.com/v1.0/me/drive/root/children"

    payload = {
        "name": name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "rename"
    }
    r = requests.post(children_url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()

def upload_small_file(path_in_drive, content_bytes, token):
    """
    Sube archivo pequeño (<=4MB aprox) a root:/path_in_drive:
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path_in_drive}:/content"
    r = requests.put(url, headers=headers, data=content_bytes)
    r.raise_for_status()
    return r.json()

def upload_large_file(path_in_drive, file_stream, token, chunk_size=5*1024*1024):
    """
    Sube archivos grandes usando Upload Session.
    - path_in_drive: 'Carpeta/Subcarpeta/archivo.ext'
    - file_stream: objeto tipo file (ya posicionado al inicio)
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    session_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path_in_drive}:/createUploadSession"
    session_res = requests.post(session_url, headers=headers, json={
        "@microsoft.graph.conflictBehavior": "replace"
    })
    session_res.raise_for_status()
    upload_url = session_res.json()["uploadUrl"]

    file_stream.seek(0, os.SEEK_END)
    file_size = file_stream.tell()
    file_stream.seek(0)

    start = 0
    while start < file_size:
        end = min(start + chunk_size - 1, file_size - 1)
        length = end - start + 1
        chunk = file_stream.read(length)
        headers = {
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{file_size}"
        }
        put = requests.put(upload_url, headers=headers, data=chunk)
        # 202 = parcial; 201/200 = completado
        if put.status_code not in (200, 201, 202):
            # reintento simple
            time.sleep(1.0)
            put = requests.put(upload_url, headers=headers, data=chunk)
            if put.status_code not in (200, 201, 202):
                put.raise_for_status()
        start = end + 1

    # Cuando termina, Graph responde con el driveItem del archivo
    return put.json()

def upload_any_size(path_in_drive, werkzeug_file, token):
    """
    Sube archivo, detectando si es pequeño o grande.
    werkzeug_file: objeto de request.files[...] (FileStorage)
    """
    if not werkzeug_file or not werkzeug_file.filename:
        return None

    # Leemos el stream una vez para determinar tamaño
    stream = werkzeug_file.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)

    # Nombres seguros
    safe_name = werkzeug_file.filename.replace("/", "-")
    path_in_drive = path_in_drive.rsplit("/", 1)[0] + "/" + safe_name if "/" in path_in_drive else safe_name

    if size <= 4 * 1024 * 1024:
        # pequeño
        content = stream.read()
        return upload_small_file(path_in_drive, content, token)
    else:
        # grande (upload session)
        return upload_large_file(path_in_drive, stream, token)

# =========================
# Rutas Front
# =========================
@app.route("/")
def index():
    # Sirve tu index.html de la raíz (como lo has manejado)
    return send_from_directory(".", "index.html")

@app.route("/templates/<path:filename>")
def serve_templates(filename):
    # Sirve el logo desde /templates
    return send_from_directory("templates", filename)

# =========================
# Ruta que procesa el formulario
# =========================
@app.route("/registrado", methods=["POST"])
def registrado():
    """
    Recibe el POST del formulario (action="/registrado"), crea carpeta en OneDrive,
    sube adjuntos y guarda metadata.json con todos los campos.
    """
    try:
        # 1) Recoger datos del formulario (coinciden con tu HTML por pasos)
        data = {
            "razon_social": request.form.get("razon_social", "").strip(),
            "tipo_documento": request.form.get("tipo_documento", "").strip(),
            "numero_documento": request.form.get("numero_documento", "").strip(),
            "departamento": request.form.get("departamento", "").strip(),
            "ciudad": request.form.get("ciudad", "").strip(),
            "telefonos": request.form.get("telefonos", "").strip(),
            "correo": request.form.get("correo", "").strip(),
            "tipo_empresa": request.form.get("tipo_empresa", "").strip(),
            "fecha_constitucion": request.form.get("fecha_constitucion", "").strip(),
            "codigo_ciiu": request.form.get("codigo_ciiu", "").strip(),
            "primer_apellido": request.form.get("primer_apellido", "").strip(),
            "segundo_apellido": request.form.get("segundo_apellido", "").strip(),
            "nombres_rl": request.form.get("nombres_rl", "").strip(),
            "tipo_documento_rl": request.form.get("tipo_documento_rl", "").strip(),
            "numero_documento_rl": request.form.get("numero_documento_rl", "").strip(),
            "timestamp_utc": datetime.utcnow().isoformat() + "Z"
        }

        files = {
            "camara_comercio": request.files.get("camara_comercio"),
            "doc_identidad": request.files.get("doc_identidad"),
            "composicion_accionaria": request.files.get("composicion_accionaria"),
            "rut": request.files.get("rut"),
            "autorizacion_datos": request.files.get("autorizacion_datos"),
        }

        # 2) Token Graph
        token = get_access_token()

        # 3) Asegurar carpeta base y subcarpeta por proveedor
        ensure_folder(BASE_FOLDER, token)
        safe_doc = data["numero_documento"] or f"sin_doc_{int(time.time())}"
        safe_rs = (data["razon_social"] or "sin_razon").replace("/", "-").strip()
        subfolder_name = f"{safe_doc} - {safe_rs}"
        ensure_folder(f"{BASE_FOLDER}/{subfolder_name}", token)

        # 4) Subir adjuntos (maneja pequeños y grandes)
        for key, f in files.items():
            if f and f.filename:
                drive_path = f"{BASE_FOLDER}/{subfolder_name}/{f.filename}"
                upload_any_size(drive_path, f, token)

        # 5) Subir metadata.json con todos los campos
        metadata_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        upload_small_file(f"{BASE_FOLDER}/{subfolder_name}/metadata.json", metadata_bytes, token)

        # Respuesta simple (puedes redirigir a una página de éxito si prefieres)
        return """
        <!doctype html>
        <html lang="es">
        <meta charset="utf-8">
        <title>Registro completado</title>
        <body style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;">
          <div style="max-width:680px;margin:40px auto;padding:24px;border:1px solid #e1e7ef;border-radius:12px;background:#fff;">
            <h2 style="margin-top:0;color:#0d47a1">¡Registro completado!</h2>
            <p>Se creó la carpeta en OneDrive y se subieron los archivos y metadatos.</p>
            <a href="/" style="display:inline-block;margin-top:12px;padding:10px 14px;border-radius:10px;background:#0d47a1;color:#fff;text-decoration:none">Volver al formulario</a>
          </div>
        </body>
        </html>
        """

    except Exception as e:
        # Para depurar si algo falla
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
