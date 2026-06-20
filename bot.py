import os
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from docxtpl import DocxTemplate
import pytz
import templates_loader

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM")  # whatsapp:+14155238886
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP")  # Numero de la duena sin whatsapp:
BASE_URL = os.getenv("BASE_URL", "https://bot-telegram-production-3cc3.up.railway.app")

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES ---
user_sessions = {}

# --- FUNCIONES ---
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

# --- ENDPOINT PRINCIPAL ---
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").replace("whatsapp:", "")
    
    logger.info(f"Mensaje de {sender}: {incoming_msg}")
    
    # Inicializar sesion
    if sender not in user_sessions:
        user_sessions[sender] = {
            "estado": "START",
            "template_folder": None,
            "template_config": None,
            "current_field_index": 0,
            "answers": {}
        }
    session = user_sessions[sender]
    resp = MessagingResponse()
    
    try:
        # ========== MENU PRINCIPAL ==========
        if session["estado"] == "START":
            templates = templates_loader.load_all_templates()
            if not templates:
                resp.message("No hay plantillas disponibles.")
                logger.warning("No hay plantillas")
                return str(resp)
            
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue vas a hacer?\n"
            for i, t in enumerate(templates, 1):
                menu += f"{i}. {t['name']}\n"
            menu += "\nResponde con el numero de la opcion."
            
            resp.message(menu)
            session["estado"] = "SELECT_TEMPLATE"
            logger.info("Menu enviado")
            return str(resp)  # <--- ¡AQUÍ ESTABA EL ERROR! Tenía una línea que no ejecutaba esto
        
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
                    resp.message(f"{first_question}\n\n(Escribe tu respuesta)")
                else:
                    resp.message("Opcion no valida. Elige un numero del menu.")
            except ValueError:
                resp.message("Responde con el numero de la opcion.")
            return str(resp)
        
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
                    resp.message(f"{next_question}\n\n(Escribe tu respuesta)")
                    return str(resp)
                else:
                    session["estado"] = "REVIEW_DATA"
                    answers = session["answers"]
                    summary = "REVISION DE DATOS\n\n"
                    for key, value in answers.items():
                        clean_key = key.replace("_", " ").title()
                        summary += f"{clean_key}: {value}\n"
                    summary += "\nEstan correctos? Responde SI o NO."
                    resp.message(summary)
                    return str(resp)
        
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
                    resp.message(
                        "Solicitud enviada correctamente!\n\n"
                        "La encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\n"
                        "Gracias por usar nuestro servicio."
                    )
                    
                    # Enviar a la duena
                    if OWNER_WHATSAPP:
                        try:
                            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                            mensaje_duena = (
                                f"Nuevo documento generado\n\n"
                                f"Solicitado por: {sender}\n"
                                f"Placa: {answers.get('placa', 'N/A')}\n"
                                f"Propietario: {answers.get('nombre_vendedor', 'N/A')}\n\n"
                                f"Descarga: {descarga_url}"
                            )
                            client.messages.create(
                                body=mensaje_duena,
                                from_=WHATSAPP_FROM,
                                to=f"whatsapp:{OWNER_WHATSAPP}"
                            )
                            logger.info(f"Mensaje enviado a duena: {OWNER_WHATSAPP}")
                        except Exception as e:
                            logger.error(f"Error al enviar a duena: {e}")
                    
                    session.clear()
                    session["estado"] = "START"
                    return str(resp)
                    
                except Exception as e:
                    logger.error(f"Error al generar: {e}")
                    resp.message(f"Error al generar el documento: {str(e)}")
                    session.clear()
                    session["estado"] = "START"
                    return str(resp)
            
            elif incoming_msg.lower() in ["no", "cancelar"]:
                saludo = obtener_saludo()
                resp.message(f"{saludo}. Operacion cancelada. Escribe cualquier mensaje para comenzar de nuevo.")
                session.clear()
                session["estado"] = "START"
                return str(resp)
            else:
                resp.message("Responde SI para generar el documento o NO para cancelar.")
                return str(resp)
        
        # ========== FALLBACK ==========
        saludo = obtener_saludo()
        resp.message(f"{saludo}. Escribe cualquier mensaje para comenzar.")
        session["estado"] = "START"
        return str(resp)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        resp.message("Ocurrio un error. Intenta de nuevo.")
        session.clear()
        session["estado"] = "START"
        return str(resp)

# --- INICIO ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
