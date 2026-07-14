import os
import logging
import requests
import json
from flask import Flask, request, send_from_directory
import pytz
from datetime import datetime
from pathlib import Path
from docxtpl import DocxTemplate
import templates_loader
import contadores

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

# --- PARA EVITAR DUPLICADOS ---
mensajes_procesados = set()

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
        "caption": "📄 Documento generado automáticamente"
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
        return "Buenos días"
    elif 12 <= hour < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# ========== FUNCIÓN PARA GENERAR WORD ==========
def generar_word(answers, folder, config_data):
    template_path = TEMPLATES_DIR / folder / config_data["template_file"]
    if not template_path.exists():
        raise FileNotFoundError(f"Plantilla no encontrada: {template_path}")
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{folder}_{now}.docx"
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
    global mensajes_procesados
    
    data = request.get_json()
    
    # Extraer información clave
    event_type = data.get("event_type", "")
    message_data = data.get("data", {})
    
    # =========================================================
    # 🔇 FILTRO 1: SOLO PROCESAR EVENTOS DE MENSAJES RECIBIDOS
    # =========================================================
    if event_type != "message_received":
        logger.info(f"🔇 IGNORANDO evento: {event_type} (no es message_received)")
        return "OK", 200
    
    # Extraer ID del mensaje (para evitar duplicados)
    message_id = message_data.get("id", "")
    
    # =========================================================
    # 🔇 FILTRO 2: EVITAR DUPLICADOS POR ID
    # =========================================================
    if message_id in mensajes_procesados:
        logger.info(f"🔇 IGNORANDO mensaje duplicado (ID ya procesado): {message_id}")
        return "OK", 200
    
    # Guardar el ID como procesado
    if message_id:
        mensajes_procesados.add(message_id)
        # Limitar el set para evitar memory leak
        if len(mensajes_procesados) > 500:
            mensajes_procesados = set(list(mensajes_procesados)[-200:])
    
    # =========================================================
    # 🔇 FILTRO 3: ANTI-BUCLE
    # =========================================================
    incoming_msg = message_data.get("body", "").strip()
    sender = message_data.get("from", "").replace("@c.us", "").replace("+", "")
    sender_name = message_data.get("pushname", sender)
    sender_clean = sender.replace("+", "").replace(" ", "")
    connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
    
    # Ignorar mensajes enviados por el propio bot
    if message_data.get("fromMe") == True or message_data.get("self") == True:
        logger.info(f"🔇 IGNORANDO mensaje del propio bot: {incoming_msg}")
        return "OK", 200
    
    # Ignorar mensajes del número conectado
    if sender_clean == connected_clean:
        logger.info(f"🔇 IGNORANDO mensaje del número conectado: {incoming_msg}")
        return "OK", 200
    
    # Ignorar mensajes de la dueña
    if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
        logger.info(f"🔇 IGNORANDO mensaje de la dueña: {incoming_msg}")
        return "OK", 200
    
    # Ignorar mensajes vacíos
    if not incoming_msg:
        logger.info(f"🔇 IGNORANDO mensaje vacío")
        return "OK", 200
    
    # =========================================================
    # FIN DEL FILTRO
    # =========================================================
    
    logger.info(f"✅ PROCESANDO: {sender_name} ({sender_clean}): {incoming_msg}")
    
    # --- MENÚ PRINCIPAL ---
    if incoming_msg.lower() == "hola":
        saludo = obtener_saludo()
        templates = templates_loader.load_all_templates()
        
        menu = f"Hola, {saludo}. Soy el asistente de la Papelería Líder.\n\n¿Qué documento necesitas?\n"
        for i, t in enumerate(templates, 1):
            menu += f"{i}. {t['name']}\n"
        menu += "\nResponde con el número de la opción."
        
        enviar_whatsapp(sender_clean, menu)
        
        if sender_clean not in user_sessions:
            user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
        else:
            user_sessions[sender_clean]["estado"] = "SELECT_TEMPLATE"
            user_sessions[sender_clean]["step"] = 0
            user_sessions[sender_clean]["answers"] = {}
        
        logger.info(f"📋 Menú enviado a {sender_clean}")
        return "OK", 200
    
    # --- SELECCIONAR PLANTILLA ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "SELECT_TEMPLATE":
        templates = templates_loader.load_all_templates()
        try:
            option = int(incoming_msg) - 1
            if 0 <= option < len(templates):
                template = templates[option]
                user_sessions[sender_clean]["template_folder"] = template["folder"]
                user_sessions[sender_clean]["template_config"] = template
                user_sessions[sender_clean]["current_field_index"] = 0
                user_sessions[sender_clean]["answers"] = {}
                user_sessions[sender_clean]["estado"] = "ASKING_DATA"
                
                fields = template["fields"]
                
                # Generar números consecutivos automáticos
                folder_name = template["folder"]
                answers = user_sessions[sender_clean]["answers"]
                
                if folder_name == "cotizacion":
                    answers["numero_cotizacion"] = contadores.obtener_siguiente_numero("cotizacion", "COT")
                elif folder_name == "cuenta_cobro":
                    answers["numero_cuenta"] = contadores.obtener_siguiente_numero("cuenta_cobro", "CC")
                
                first_question = fields[0]["question"]
                enviar_whatsapp(sender_clean, first_question)
            else:
                enviar_whatsapp(sender_clean, "❌ Opción no válida. Elige un número del menú.")
        except ValueError:
            enviar_whatsapp(sender_clean, "❌ Responde con el número de la opción.")
        return "OK", 200
    
    # --- PREGUNTAS ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_DATA":
        session = user_sessions[sender_clean]
        config_data = session["template_config"]
        fields = config_data["fields"]
        idx = session["current_field_index"]
        answers = session["answers"]
        
        if idx < len(fields):
            field_key = fields[idx]["key"]
            answers[field_key] = incoming_msg
            session["current_field_index"] = idx + 1
            
            if session["current_field_index"] < len(fields):
                next_question = fields[session["current_field_index"]]["question"]
                enviar_whatsapp(sender_clean, next_question)
                return "OK", 200
            else:
                session["estado"] = "REVIEW_DATA"
                summary = "📋 REVISIÓN DE DATOS\n\n"
                for key, value in answers.items():
                    clean_key = key.replace("_", " ").title()
                    summary += f"📌 {clean_key}: {value}\n"
                summary += "\n¿Están correctos? Responde SI o NO."
                enviar_whatsapp(sender_clean, summary)
                return "OK", 200
        else:
            session["estado"] = "REVIEW_DATA"
            summary = "📋 REVISIÓN DE DATOS\n\n"
            for key, value in answers.items():
                clean_key = key.replace("_", " ").title()
                summary += f"📌 {clean_key}: {value}\n"
            summary += "\n¿Están correctos? Responde SI o NO."
            enviar_whatsapp(sender_clean, summary)
            return "OK", 200
    
    # --- CONFIRMACIÓN ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "REVIEW_DATA":
        if incoming_msg.lower() in ["si", "sí", "yes"]:
            try:
                session = user_sessions[sender_clean]
                answers = session["answers"]
                folder = session["template_folder"]
                config_data = session["template_config"]
                
                output_path, output_filename = generar_word(answers, folder, config_data)
                
                enviar_whatsapp(sender_clean, "✅ Solicitud enviada correctamente.\n\nLa encargada revisará tu documento y te contactará en breve.")
                
                enviar_documento_ultramsg(OWNER_WHATSAPP, output_path, output_filename)
                mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nDocumento: {config_data.get('name', 'Documento')}"
                enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                
                user_sessions.pop(sender_clean, None)
                
            except Exception as e:
                logger.error(f"Error al generar documento: {e}")
                enviar_whatsapp(sender_clean, f"❌ Error al generar el documento: {str(e)}")
                user_sessions.pop(sender_clean, None)
            return "OK", 200
        
        elif incoming_msg.lower() in ["no", "cancelar"]:
            enviar_whatsapp(sender_clean, "🔄 Operación cancelada. Escribe 'hola' para comenzar de nuevo.")
            user_sessions.pop(sender_clean, None)
            return "OK", 200
        else:
            enviar_whatsapp(sender_clean, "❌ Responde SI o NO.")
            return "OK", 200
    
    # --- FALLBACK ---
    enviar_whatsapp(sender_clean, "No entendí tu mensaje. Escribe 'hola' para comenzar.")
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot de WhatsApp funcionando"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)