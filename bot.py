import os
import logging
import requests
import json
from flask import Flask, request, send_from_directory
import pytz
from datetime import datetime
from pathlib import Path
from docxtpl import DocxTemplate
from bs4 import BeautifulSoup
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
import re

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "573247247478")
CONNECTED_NUMBER = os.getenv("CONNECTED_NUMBER", "573167913339")
BASE_URL = os.getenv("BASE_URL", "https://bot-telegram-production-f78f.up.railway.app")

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES ---
user_sessions = {}

# ========== FUNCIONES DE ULTRAMSG ==========
def enviar_whatsapp(numero, mensaje):
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"
    payload = {"token": ULTRA_TOKEN, "to": numero, "body": mensaje}
    try:
        response = requests.post(url, json=payload, timeout=3)
        if response.status_code == 200:
            logger.info(f"Mensaje enviado a {numero}")
        else:
            logger.error(f"Error al enviar texto: {response.text}")
        return response
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

def enviar_documento_ultramsg(numero, archivo_path, nombre_archivo):
    descarga_url = f"{BASE_URL}/descargar/{nombre_archivo}"
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/document"
    payload = {
        "token": ULTRA_TOKEN,
        "to": numero,
        "filename": nombre_archivo,
        "document": descarga_url,
        "caption": "📄 Documento generado automaticamente por Papeleria Lider"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Documento enviado a {numero}: {nombre_archivo}")
        else:
            logger.error(f"Error al enviar documento: {response.text}")
        return response
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

def obtener_saludo():
    colombia_tz = pytz.timezone('America/Bogota')
    hour = datetime.now(colombia_tz).hour
    if 6 <= hour < 12:
        return "Buenos dias"
    elif 12 <= hour < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# ========== FUNCIONES DE SISBÉN (CON reportes.sisben.gov.co) ==========
def mapear_tipo_documento(tipo_input):
    tipo_input = tipo_input.upper().strip()
    mapeo = {
        "RC": "1", "REGISTRO CIVIL": "1",
        "TI": "2", "TARJETA DE IDENTIDAD": "2",
        "CC": "3", "CEDULA DE CIUDADANIA": "3",
        "CE": "4", "CEDULA DE EXTRANJERIA": "4",
        "DNI": "5", "PASAPORTE": "6",
        "PEP": "8", "PPT": "9"
    }
    for key, value in mapeo.items():
        if tipo_input == key or tipo_input in key or key in tipo_input:
            return value
    return "3"

def consultar_sisben_post(tipo_documento, numero_documento):
    """Consulta el Sisbén usando reportes.sisben.gov.co"""
    logger.info(f"🔍 Consultando Sisbén para {tipo_documento}: {numero_documento}")
    
    tipo_id = mapear_tipo_documento(tipo_documento)
    logger.info(f"📝 Tipo ID: {tipo_id}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://www.sisben.gov.co",
        "Referer": "https://www.sisben.gov.co/Paginas/consulta-tu-grupo.html"
    }
    
    # Intentar diferentes URLs
    urls = [
        ("https://reportes.sisben.gov.co/api/consulta", "json"),
        ("https://reportes.sisben.gov.co/consulta/ciudadano", "form"),
        ("https://reportes.sisben.gov.co/api/ciudadano", "json")
    ]
    
    for url, tipo in urls:
        try:
            logger.info(f"📡 Intentando: {url}")
            
            if tipo == "json":
                payload = {"tipoDocumento": tipo_id, "numeroDocumento": numero_documento}
                response = requests.post(url, json=payload, headers=headers, timeout=15)
            else:
                payload = {"tipoDocumento": tipo_id, "documento": numero_documento}
                response = requests.post(url, data=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                if tipo == "json":
                    try:
                        data = response.json()
                        logger.info(f"✅ Datos JSON: {data}")
                        if data and "error" not in str(data).lower():
                            datos = extraer_datos_api(data, tipo_documento, numero_documento)
                            if datos:
                                return datos
                    except:
                        pass
                
                # Si no es JSON, parsear HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                texto = soup.get_text()
                if "registro válido" in texto.lower() or "datos personales" in texto.lower():
                    return extraer_datos_html(texto, tipo_documento, numero_documento)
                    
        except Exception as e:
            logger.warning(f"⚠️ Error en {url}: {e}")
    
    logger.error("❌ No se pudo obtener información")
    return None

def extraer_datos_api(data, tipo_documento, numero_documento):
    """Extrae datos del JSON de la API"""
    try:
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        if "data" in data:
            data = data["data"]
        if "resultado" in data:
            data = data["resultado"]
        
        datos = {
            "nombres": data.get("nombres", data.get("Nombres", data.get("Nombre", "No disponible"))),
            "apellidos": data.get("apellidos", data.get("Apellidos", data.get("Apellido", "No disponible"))),
            "tipo_documento": tipo_documento,
            "numero_documento": numero_documento,
            "municipio": data.get("municipio", data.get("Municipio", "No disponible")),
            "departamento": data.get("departamento", data.get("Departamento", "No disponible")),
            "grupo": data.get("grupo", data.get("Grupo", "No disponible")),
            "categoria": data.get("categoria", data.get("Categoria", "No disponible")),
            "fecha_encuesta": data.get("fechaEncuesta", data.get("FechaEncuesta", "No disponible")),
            "fecha_actualizacion": data.get("fechaActualizacion", data.get("FechaActualizacion", "No disponible")),
            "nombre_administrador": data.get("nombreAdministrador", data.get("NombreAdministrador", "No disponible")),
            "direccion_oficina": data.get("direccionOficina", data.get("DireccionOficina", "No disponible")),
            "telefono_oficina": data.get("telefonoOficina", data.get("TelefonoOficina", "No disponible")),
            "email_oficina": data.get("emailOficina", data.get("EmailOficina", "No disponible")),
            "fecha_consulta": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        
        if datos["nombres"] != "No disponible" or datos["apellidos"] != "No disponible":
            return datos
        return None
    except Exception as e:
        logger.error(f"Error parseando API: {e}")
        return None

def extraer_datos_html(texto, tipo_documento, numero_documento):
    """Extrae datos del HTML"""
    datos = {
        "nombres": "No disponible",
        "apellidos": "No disponible",
        "tipo_documento": tipo_documento,
        "numero_documento": numero_documento,
        "municipio": "No disponible",
        "departamento": "No disponible",
        "grupo": "No disponible",
        "categoria": "No disponible",
        "fecha_encuesta": "No disponible",
        "fecha_actualizacion": "No disponible",
        "nombre_administrador": "No disponible",
        "direccion_oficina": "No disponible",
        "telefono_oficina": "No disponible",
        "email_oficina": "No disponible",
        "fecha_consulta": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    
    patrones = {
        "nombres": r'Nombres?[:\s]+([A-ZÁÉÍÓÚÑ\s.]+)',
        "apellidos": r'Apellidos?[:\s]+([A-ZÁÉÍÓÚÑ\s.]+)',
        "municipio": r'Municipio[:\s]+([A-Za-zÁÉÍÓÚÑ\s.]+)',
        "departamento": r'Departamento[:\s]+([A-Za-zÁÉÍÓÚÑ\s.]+)',
        "grupo": r'[Gg]rupo[:\s]+([A-Z0-9]+)',
        "categoria": r'[Cc]ategor[ií]a[:\s]+([A-Za-zÁÉÍÓÚÑ\s.]+)',
        "fecha_encuesta": r'Encuesta vigente[:\s]+([0-9/]+)',
        "fecha_actualizacion": r'[Úú]ltima actualizaci[óo]n[:\s]+([0-9/]+)',
    }
    
    for key, pattern in patrones.items():
        match = re.search(pattern, texto, re.IGNORECASE)
        if match:
            datos[key] = match.group(1).strip()
            logger.info(f"✅ {key}: {datos[key]}")
    
    match = re.search(r'Nombre administrador[:\s]+([A-Za-zÁÉÍÓÚÑ\s.]+)', texto, re.IGNORECASE)
    if match:
        datos["nombre_administrador"] = match.group(1).strip()
    
    match = re.search(r'Direcci[oó]n[:\s]+([A-Za-zÁÉÍÓÚÑ\s0-9#-.]+)', texto, re.IGNORECASE)
    if match:
        datos["direccion_oficina"] = match.group(1).strip()
    
    match = re.search(r'Tel[eé]fono[:\s]+([0-9\s]+)', texto, re.IGNORECASE)
    if match:
        datos["telefono_oficina"] = match.group(1).strip()
    
    match = re.search(r'Correo Electr[oó]nico[:\s]+([A-Za-z0-9@._-]+)', texto, re.IGNORECASE)
    if match:
        datos["email_oficina"] = match.group(1).strip()
    
    if datos["nombres"] != "No disponible" or datos["apellidos"] != "No disponible":
        return datos
    return None

# ========== GENERAR PDF ==========
def generar_pdf_sisben(datos, output_path):
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    
    y = height - 40
    c.setFont("Helvetica", 8)
    fecha_consulta = datos.get("fecha_consulta", datetime.now().strftime("%d/%m/%Y %H:%M"))
    c.drawRightString(width - 50, y, f"Fecha de consulta: {fecha_consulta}")
    
    c.setFont("Helvetica-Bold", 8)
    c.drawString(50, y, "Ficha:")
    c.setFont("Helvetica", 8)
    c.drawString(100, y, "41132004748100000116")
    y -= 30
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.0, 0.5, 0.0))
    c.drawString(50, y, "Registro válido")
    y -= 20
    
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(colors.Color(0.2, 0.4, 0.6))
    c.drawString(50, y, datos.get("grupo", "N/A"))
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.black)
    c.drawString(150, y + 10, datos.get("categoria", "N/A"))
    y -= 40
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "DATOS PERSONALES")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Nombres: {datos.get('nombres', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Apellidos: {datos.get('apellidos', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Tipo de documento: {datos.get('tipo_documento', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Número de documento: {datos.get('numero_documento', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Municipio: {datos.get('municipio', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Departamento: {datos.get('departamento', 'No disponible')}")
    y -= 25
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "INFORMACIÓN ADMINISTRATIVA")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Encuesta vigente: {datos.get('fecha_encuesta', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Última actualización: {datos.get('fecha_actualizacion', 'No disponible')}")
    y -= 30
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "Contacto Oficina SISBEN")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Nombre: {datos.get('nombre_administrador', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Dirección: {datos.get('direccion_oficina', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Teléfono: {datos.get('telefono_oficina', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Email: {datos.get('email_oficina', 'No disponible')}")
    y -= 30
    
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.gray)
    c.drawString(50, 50, "*Si encuentra alguna inconsistencia, acérquese a la oficina del Sisbén de su municipio")
    c.line(50, 70, width - 50, 70)
    c.save()
    logger.info(f"PDF generado: {output_path}")

# ========== FUNCIÓN PARA GENERAR WORD ==========
def generar_word(answers, folder="poder_vehiculo"):
    template_path = TEMPLATES_DIR / folder / "template.docx"
    if not template_path.exists():
        template_path = Path("template.docx")
        if not template_path.exists():
            raise FileNotFoundError(f"Plantilla no encontrada")
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Poder_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = Path(OUTPUT_DIR) / output_filename
    
    doc = DocxTemplate(str(template_path))
    doc.render(answers)
    doc.save(str(output_path))
    logger.info(f"Documento generado: {output_filename}")
    return str(output_path), output_filename

# ========== ENDPOINTS ==========
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    try:
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error al descargar {filename}: {e}")
        return "Archivo no encontrado", 404

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logger.info(f"Mensaje recibido: {data}")
    
    if data and "data" in data:
        message_data = data["data"]
        incoming_msg = message_data.get("body", "").strip()
        sender = message_data.get("from", "").replace("@c.us", "").replace("+", "")
        sender_name = message_data.get("pushname", sender)
        
        connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
        sender_clean = sender.replace("+", "").replace(" ", "")
        
        if sender_clean == connected_clean:
            logger.info(f"🔇 Ignorando mensaje del número conectado: {incoming_msg}")
            return "OK", 200
        
        if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
            logger.info(f"🔇 Ignorando mensaje de la dueña: {incoming_msg}")
            return "OK", 200
        
        logger.info(f"Mensaje de {sender_name} ({sender_clean}): {incoming_msg}")
        
        if incoming_msg.lower() == "hola":
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue tipo de documento necesitas?\n1. Poder para Tramite de Vehiculo\n2. Certificado de Sisbén\n3. Certificado de ADRES\n\nResponde con el numero de la opcion."
            enviar_whatsapp(sender_clean, menu)
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
            return "OK", 200
        
        if incoming_msg == "1":
            enviar_whatsapp(sender_clean, "Perfecto! Necesito algunos datos.\n\nEscribe el DIA de la fecha (ej: 10):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_DATA", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_DATA"
                user_sessions[sender_clean]["step"] = 0
            return "OK", 200
        
        if incoming_msg == "2":
            enviar_whatsapp(sender_clean, "Escribe el TIPO de documento (CC, CE, TI, DNI, Pasaporte, PEP, PPT):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_SISBEN_TIPO", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_SISBEN_TIPO"
            return "OK", 200
        
        # --- PREGUNTAS DEL DOCUMENTO (PODER) ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_DATA":
            session = user_sessions[sender_clean]
            step = session["step"]
            answers = session["answers"]
            
            fields = [
                {"key": "dia", "question": "Escribe el DIA de la fecha (ej: 10):"},
                {"key": "mes", "question": "Escribe el MES en letras (ej: octubre):"},
                {"key": "año", "question": "Escribe el ANIO (ej: 2024):"},
                {"key": "entidad_destino", "question": "Escribe la ENTIDAD a la que va dirigido:"},
                {"key": "nombre_vendedor", "question": "Escribe el NOMBRE COMPLETO del propietario:"},
                {"key": "cedula_vendedor", "question": "Escribe la CEDULA del propietario:"},
                {"key": "ciudad_expedicion", "question": "Escribe la CIUDAD de expedicion:"},
                {"key": "nombre_apoderado", "question": "Escribe el NOMBRE COMPLETO del apoderado:"},
                {"key": "cedula_apoderado", "question": "Escribe la CEDULA del apoderado:"},
                {"key": "placa", "question": "Escribe la PLACA del vehiculo:"}
            ]
            
            if step < len(fields):
                field_key = fields[step]["key"]
                answers[field_key] = incoming_msg
                session["step"] = step + 1
                
                if session["step"] < len(fields):
                    next_question = fields[session["step"]]["question"]
                    enviar_whatsapp(sender_clean, next_question)
                    return "OK", 200
                else:
                    session["estado"] = "REVIEW_DATA"
                    summary = "REVISION DE DATOS\n\n"
                    for key, value in answers.items():
                        clean_key = key.replace("_", " ").title()
                        summary += f"{clean_key}: {value}\n"
                    summary += "\nEstan correctos? Responde SI o NO."
                    enviar_whatsapp(sender_clean, summary)
                    return "OK", 200
            else:
                session["estado"] = "REVIEW_DATA"
                summary = "REVISION DE DATOS\n\n"
                for key, value in answers.items():
                    clean_key = key.replace("_", " ").title()
                    summary += f"{clean_key}: {value}\n"
                summary += "\nEstan correctos? Responde SI o NO."
                enviar_whatsapp(sender_clean, summary)
                return "OK", 200
        
        # --- PREGUNTAS DE SISBÉN ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_TIPO":
            session = user_sessions[sender_clean]
            session["answers"]["tipo_documento"] = incoming_msg
            session["estado"] = "ASKING_SISBEN_NUMERO"
            enviar_whatsapp(sender_clean, "Escribe el NUMERO de documento:")
            return "OK", 200
        
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_NUMERO":
            session = user_sessions[sender_clean]
            tipo_doc = session["answers"]["tipo_documento"]
            num_doc = incoming_msg
            
            enviar_whatsapp(sender_clean, "⏳ Consultando información en el Sisbén...")
            
            try:
                datos = consultar_sisben_post(tipo_doc, num_doc)
                
                if datos:
                    output_filename = f"Sisben_{num_doc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    output_path = Path(OUTPUT_DIR) / output_filename
                    generar_pdf_sisben(datos, str(output_path))
                    
                    enviar_documento_ultramsg(OWNER_WHATSAPP, str(output_path), output_filename)
                    
                    mensaje_duena = f"📄 Certificado de Sisbén generado\n\nSolicitado por: {sender_clean}\nTipo: {tipo_doc}\nNúmero: {num_doc}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    
                    enviar_whatsapp(sender_clean, f"✅ Certificado generado correctamente.\n\nDatos encontrados:\nNombres: {datos.get('nombres', 'N/A')}\nApellidos: {datos.get('apellidos', 'N/A')}\nGrupo: {datos.get('grupo', 'N/A')}")
                else:
                    enviar_whatsapp(sender_clean, "❌ No se encontró información para esos datos. Verifica tipo y número.")
            except Exception as e:
                logger.error(f"Error: {e}")
                enviar_whatsapp(sender_clean, "❌ Ocurrió un error al consultar el Sisbén. Intenta de nuevo.")
            
            user_sessions.pop(sender_clean, None)
            return "OK", 200
        
        # --- CONFIRMACIÓN (PODER) ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                try:
                    answers = user_sessions[sender_clean]["answers"]
                    output_path, output_filename = generar_word(answers)
                    
                    enviar_whatsapp(sender_clean, "✅ Solicitud enviada correctamente!\n\nLa encargada revisará tu documento y te contactará.")
                    
                    enviar_documento_ultramsg(OWNER_WHATSAPP, output_path, output_filename)
                    mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    
                    user_sessions.pop(sender_clean, None)
                    
                except Exception as e:
                    logger.error(f"Error: {e}")
                    enviar_whatsapp(sender_clean, f"❌ Error: {str(e)}")
                    user_sessions.pop(sender_clean, None)
                return "OK", 200
            
            elif incoming_msg.lower() in ["no", "cancelar"]:
                enviar_whatsapp(sender_clean, "Operación cancelada. Escribe 'hola' para comenzar.")
                user_sessions.pop(sender_clean, None)
                return "OK", 200
            else:
                enviar_whatsapp(sender_clean, "Responde SI o NO.")
                return "OK", 200
        
        enviar_whatsapp(sender_clean, "No entendí tu mensaje. Escribe 'hola' para comenzar.")
        return "OK", 200
    
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot de WhatsApp funcionando con Ultramsg"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)