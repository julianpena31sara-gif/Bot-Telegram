import os
import logging
import requests
import json
from flask import Flask, request
import pytz
from datetime import datetime
from pathlib import Path
from docxtpl import DocxTemplate

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")
OWNER_WHATSAPP = "573247247478"  # Número de la dueña
CONNECTED_NUMBER = "573167913339"  # Número conectado a Ultramsg

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES ---
user_sessions = {}

# --- FUNCIONES ---
def enviar_whatsapp(numero, mensaje):
    """Envía un mensaje de texto usando Ultramsg"""
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"
    payload = {"token": ULTRA_TOKEN, "to": numero, "body": mensaje}
    try:
        response = requests.post(url, json=payload, timeout=3)
        if response.status_code == 200:
            logger.info(f"Mensaje enviado a {numero}")
        else:
            logger.error(f"Error al enviar: {response.text}")
        return response
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

def enviar_documento(numero, archivo_path, nombre_archivo):
    """Envía un documento (Word/PDF) usando Ultramsg"""
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/document"
    
    # Ultramsg espera el archivo en base64 o URL
    # Primero, leemos el archivo y lo codificamos en base64
    import base64
    with open(archivo_path, "rb") as f:
        file_data = base64.b64encode(f.read()).decode("utf-8")
    
    payload = {
        "token": ULTRA_TOKEN,
        "to": numero,
        "filename": nombre_archivo,
        "document": file_data,
        "caption": "📄 Documento generado automáticamente por Papeleria Lider"
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

def generar_word(answers, folder="poder_vehiculo"):
    """Genera el Word con los datos y devuelve la ruta y nombre del archivo"""
    template_path = TEMPLATES_DIR / folder / "template.docx"
    if not template_path.exists():
        raise FileNotFoundError(f"Plantilla no encontrada: {template_path}")
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Poder_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = Path(OUTPUT_DIR) / output_filename
    
    doc = DocxTemplate(str(template_path))
    doc.render(answers)
    doc.save(str(output_path))
    
    logger.info(f"Documento generado: {output_filename}")
    return str(output_path), output_filename

# --- ENDPOINT PRINCIPAL ---
@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de Ultramsg y responde rápidamente"""
    data = request.get_json()
    logger.info(f"Mensaje recibido: {data}")
    
    if data and "data" in data:
        message_data = data["data"]
        incoming_msg = message_data.get("body", "").strip()
        sender = message_data.get("from", "").replace("@c.us", "").replace("+", "")
        sender_name = message_data.get("pushname", sender)
        
        # --- FILTRO: Ignorar mensajes del número conectado y de la dueña ---
        connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
        sender_clean = sender.replace("+", "").replace(" ", "")
        
        if sender_clean == connected_clean:
            logger.info(f"🔇 Ignorando mensaje del número conectado: {incoming_msg}")
            return "OK", 200
        
        if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
            logger.info(f"🔇 Ignorando mensaje de la dueña: {incoming_msg}")
            return "OK", 200
        
        logger.info(f"Mensaje de {sender_name} ({sender_clean}): {incoming_msg}")
        
        # --- MENÚ PRINCIPAL ---
        if incoming_msg.lower() == "hola":
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue tipo de documento necesitas?\n1. Poder para Tramite de Vehiculo\n\nResponde con el numero de la opcion."
            enviar_whatsapp(sender_clean, menu)
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
            return "OK", 200
        
        # --- SELECCIONAR PLANTILLA ---
        if incoming_msg == "1":
            enviar_whatsapp(sender_clean, "Perfecto! Necesito algunos datos para generar el documento.\n\nEscribe el DIA de la fecha (ej: 10):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_DATA", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_DATA"
                user_sessions[sender_clean]["step"] = 0
            return "OK", 200
        
        # --- PREGUNTAS ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_DATA":
            session = user_sessions[sender_clean]
            step = session["step"]
            answers = session["answers"]
            
            fields = [
                {"key": "dia", "question": "Escribe el DIA de la fecha (ej: 10):"},
                {"key": "mes", "question": "Escribe el MES en letras (ej: octubre):"},
                {"key": "año", "question": "Escribe el ANIO (ej: 2024):"},
                {"key": "entidad_destino", "question": "Escribe la ENTIDAD a la que va dirigido:"},
                {"key": "nombre_vendedor", "question": "Escribe el NOMBRE COMPLETO del propietario actual:"},
                {"key": "cedula_vendedor", "question": "Escribe la CEDULA del propietario:"},
                {"key": "ciudad_expedicion", "question": "Escribe la CIUDAD de expedicion de la cedula:"},
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
        
        # --- CONFIRMACION ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                try:
                    answers = user_sessions[sender_clean]["answers"]
                    
                    # Generar el Word
                    output_path, output_filename = generar_word(answers)
                    
                    # Enviar confirmación al cliente
                    enviar_whatsapp(sender_clean, "✅ Solicitud enviada correctamente!\n\nLa encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\nGracias por usar nuestro servicio.")
                    
                    # Enviar el DOCUMENTO a la dueña
                    enviar_documento(OWNER_WHATSAPP, output_path, output_filename)
                    
                    # También enviar notificación de texto a la dueña
                    mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    
                    user_sessions.pop(sender_clean, None)
                    
                except Exception as e:
                    logger.error(f"Error al generar documento: {e}")
                    enviar_whatsapp(sender_clean, f"❌ Error al generar el documento: {str(e)}")
                    user_sessions.pop(sender_clean, None)
                return "OK", 200
            
            elif incoming_msg.lower() in ["no", "cancelar"]:
                enviar_whatsapp(sender_clean, "Operacion cancelada. Escribe 'hola' para comenzar de nuevo.")
                user_sessions.pop(sender_clean, None)
                return "OK", 200
            else:
                enviar_whatsapp(sender_clean, "Responde SI para generar el documento o NO para cancelar.")
                return "OK", 200
        
        # --- FALLBACK ---
        enviar_whatsapp(sender_clean, "No entendi tu mensaje. Escribe 'hola' para comenzar.")
        return "OK", 200
    
    return "OK", 200

# --- INICIO ---
@app.route("/", methods=["GET"])
def home():
    return "Bot de WhatsApp funcionando con Ultramsg"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
