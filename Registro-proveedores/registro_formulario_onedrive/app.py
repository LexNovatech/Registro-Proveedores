from flask import Flask, request, render_template, redirect
import os
import pandas as pd
from werkzeug.utils import secure_filename
from onedrivesdk import GraphClient, AuthProvider  # placeholder imports

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/registrado", methods=["POST"])
def registrado():
    razon_social = request.form.get("razon_social")
    tipo_documento = request.form.get("tipo_documento")
    numero_documento = request.form.get("numero_documento")
    departamento = request.form.get("departamento")
    ciudad = request.form.get("ciudad")
    archivos = request.files.getlist("archivos")

    folder_name = f"{numero_documento}_{razon_social}".replace(" ", "_")
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Guardar en Excel
    df = pd.DataFrame([{
        "Razón Social": razon_social,
        "Tipo Documento": tipo_documento,
        "Número Documento": numero_documento,
        "Departamento": departamento,
        "Ciudad": ciudad
    }])
    df.to_excel(os.path.join(folder_path, f"{numero_documento}.xlsx"), index=False)

    # Guardar archivos
    for file in archivos:
        filename = secure_filename(file.filename)
        file.save(os.path.join(folder_path, filename))

    # Aquí se debe subir a OneDrive (requiere integración con API)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
