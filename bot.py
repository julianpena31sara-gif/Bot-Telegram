import os
import logging
import requests
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, request, send_from_directory
from docxtpl import DocxTemplate
import pytz
import templates_loader

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO (ULTRAMSG) ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")  # Ej: instance123456
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")              # Ej: abcdef123456
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP")        # Número de la dueña (sin +, ej: 573167913339)
BASE_URL = os.getenv("BASE_URL", "https://bot-telegram-production-3cc3.up.railway.app")

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES ---
user_sessions = {}

# --- FUNCIONES DE ULTRAMSG ---
def enviar_whatsapp(numero, mensaje):
    """Envía un mensaje de texto usando Ultramsg API"""
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"
    payload = {
        "token": ULTRA_TOKEN,
        "to": numero,
        "body": mensaje
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        if response.status_code == 200:
            logger.info(f"Mensaje enviado a {numero}")
            return response.json()
        else:
            logger.error(f"Error al enviar: {response.text}")
            return None
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

def generar_word(answers, folder, config_data):
    template_path = TEMPLATES_DIR / folder / config_data["template_file"]
    if not template_path.exists():
        raise FileNotFoundError(f"Plantilla no encontrada: {template_path}")
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Poder_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = Path(OUTPUT_DIR) / output_filename
    
    doc = DocxTemplate(str(template_path))
    doc.render(answers)
    doc.save(str(output_path))
    return str(output_path), output_filename

# --- ENDPOINT PARA DESCARGAR ---
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

# --- ENDPOINT PARA RECIBIR MENSAJES (WEBHOOK) ---
@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de Ultramsg"""
    data = request.get_json()
    logger.info(f"Mensaje recibido: {data}")
    
    # Extraer datos del mensaje
    if "data" in data:
        message_data = data["data"]
        incoming_msg = message_data.get("body", "").strip()
        sender = message_data.get("from", "").replace("+", "")
        sender_name = message_data.get("name", sender)
        
        logger.info(f"Mensaje de {sender_name} ({sender}): {incoming_msg}")
        
        # Inicializar sesión
        if sender not in user_sessions:
            user_sessions[sender] = {
                "estado": "START",
                "template_folder": None,
                "template_config": None,
                "current_field_index": 0,
                "answers": {}
            }
        session = user_sessions[sender]
        
        try:
            # ========== MENU PRINCIPAL ==========
            if session["estado"] == "START":
                templates = templates_loader.load_all_templates()
                if not templates:
                    enviar_whatsapp(sender, "No hay plantillas disponibles.")
                    return "OK", 200
                
                saludo = obtener_saludo()
                menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue vas a hacer?\n"
                for i, t in enumerate(templates, 1):
                    menu += f"{i}. {t['name']}\n"
                menu += "\nResponde con el numero de la opcion."
                
                enviar_whatsapp(sender, menu)
                session["estado"] = "SELECT_TEMPLATE"
                logger.info("Menu enviado")
                return "OK", 200
            
            # ========== SELECCIONAR PLANTILLA ==========
            if session["estado"] == "SELECT_TEMPLATE":
                templates = templates_loader.load_all_templates()
                try:
                    option = int(incoming_msg) - 1
                    if 0 <= option < len(templates):
                        template = templates[option]
                        session["template_folder"] = template["folder"]
                        session["template_config"] = template
                        session["current_field_index"] = 0
                        session["answers"] = {}
                        session["estado"] = "ASKING_DATA"
                        
                        fields = template["fields"]
                        first_question = fields[0]["question"]
                        enviar_whatsapp(sender, f"{first_question}\n\n(Escribe tu respuesta)")
                    else:
                        enviar_whatsapp(sender, "Opcion no valida. Elige un numero del menu.")
                except ValueError:
                    enviar_whatsapp(sender, "Responde con el numero de la opcion.")
                return "OK", 200
            
            # ========== RESPONDER PREGUNTAS ==========
            if session["estado"] == "ASKING_DATA":
                config_data = session["template_config"]
                fields = config_data["fields"]
                idx = session["current_field_index"]
                
                if idx < len(fields):
                    field_key = fields[idx]["key"]
                    session["answers"][field_key] = incoming_msg
                    session["current_field_index"] = idx + 1
                    
                    if session["current_field_index"] < len(fields):
                        next_question = fields[session["current_field_index"]]["question"]
                        enviar_whatsapp(sender, f"{next_question}\n\n(Escribe tu respuesta)")
                        return "OK", 200
                    else:
                        session["estado"] = "REVIEW_DATA"
                        answers = session["answers"]
                        summary = "REVISION DE DATOS\n\n"
                        for key, value in answers.items():
                            clean_key = key.replace("_", " ").title()
                            summary += f"{clean_key}: {value}\n"
                        summary += "\nEstan correctos? Responde SI o NO."
                        enviar_whatsapp(sender, summary)
                        return "OK", 200
            
            # ========== CONFIRMACION ==========
            if session["estado"] == "REVIEW_DATA":
                if incoming_msg.lower() in ["si", "sí", "yes"]:
                    try:
                        config_data = session["template_config"]
                        answers = session["answers"]
                        folder = session["template_folder"]
                        
                        output_path, output_filename = generar_word(answers, folder, config_data)
                        descarga_url = f"{BASE_URL}/descargar/{output_filename}"
                        
                        # Mensaje para el cliente
                        enviar_whatsapp(sender, "Solicitud enviada correctamente!\n\nLa encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\nGracias por usar nuestro servicio.")
                        
                        # Enviar a la duena
                        if OWNER_WHATSAPP:
                            mensaje_duena = f"Nuevo documento generado\n\nSolicitado por: {sender}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}\n\nDescarga: {descarga_url}"
                            enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                            logger.info(f"Mensaje enviado a duena: {OWNER_WHATSAPP}")
                        
                        session.clear()
                        session["estado"] = "START"
                        
                    except Exception as e:
                        logger.error(f"Error al generar: {e}")
                        enviar_whatsapp(sender, f"Error al generar el documento: {str(e)}")
                        session.clear()
                        session["estado"] = "START"
                    return "OK", 200
                
                elif incoming_msg.lower() in ["no", "cancelar"]:
                    saludo = obtener_saludo()
                    enviar_whatsapp(sender, f"{saludo}. Operacion cancelada. Escribe cualquier mensaje para comenzar de nuevo.")
                    session.clear()
                    session["estado"] = "START"
                    return "OK", 200
                else:
                    enviar_whatsapp(sender, "Responde SI para generar el documento o NO para cancelar.")
                    return "OK", 200
            
            # ========== FALLBACK ==========
            saludo = obtener_saludo()
            enviar_whatsapp(sender, f"{saludo}. Escribe cualquier mensaje para comenzar.")
            session["estado"] = "START"
            return "OK", 200
            
        except Exception as e:
            logger.error(f"Error: {e}")
            enviar_whatsapp(sender, "Ocurrio un error. Intenta de nuevo.")
            session.clear()
            session["estado"] = "START"
            return "OK", 200
    
    return "OK", 200

# --- INICIO ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
