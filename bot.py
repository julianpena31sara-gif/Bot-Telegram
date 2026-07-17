import os
import logging
import requests
import json
from flask import Flask, request, send_from_directory
import pytz
from datetime import datetime, timedelta
from pathlib import Path
from docxtpl import DocxTemplate
import templates_loader
import contadores
from collections import deque

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "573247247478")
CONNECTED_NUMBER = os.getenv("CONNECTED_NUMBER", "573167913339")
BASE_URL = os.getenv("BASE_URL", "https://bot-telegram-production-4164.up.railway.app")

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES ---
user_sessions = {}
historial_mensajes = {}

# ========== FUNCIONES DE ULTRAMSG ==========
def enviar_whatsapp(numero, mensaje):
    """Envía un mensaje de texto usando Ultramsg"""
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
    """Genera el Word y devuelve la ruta y nombre del archivo"""
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

# ========== FUNCIÓN PARA ENVIAR MENÚ ==========
def enviar_menu(sender, templates):
    """Envía el menú en un solo mensaje de WhatsApp"""
    saludo = obtener_saludo()
    menu = f"Hola, {saludo}. Soy el asistente de la Papelería Líder.\n\n¿Qué documento necesitas?\n"
    for i, t in enumerate(templates, 1):
        menu += f"{i}. {t['name']}\n"
    menu += "\n18. Otros (Sisbén / Adres)\n"
    menu += "\nResponde con el número de la opción."
    
    enviar_whatsapp(sender, menu)
    logger.info(f"📋 Menú enviado a {sender}")

# ========== FUNCIÓN PARA OBTENER PRECIO ==========
def obtener_precio(nombre_documento):
    """Devuelve el precio según el documento"""
    precios = {
        "Compraventa de Vehículo": "$25.000",
        "Compraventa de Inmueble (Casa/Lote)": "$40.000",
        "Contrato de Arrendamiento (Casa/Apartamento)": "$35.000",
        "Contrato de Arrendamiento (Local Comercial)": "$35.000",
        "Poder Amplio y Suficiente": "$15.000",
        "Autorización": "$6.000",
        "Cotización": "Consultar con la encargada (se comunicará en breve)",
        "Acuerdo de Pago": "$6.000",
        "Cuenta de Cobro": "$7.000",
        "Referencia Personal - Familiar": "$4.000"
    }
    
    if nombre_documento in precios:
        return precios[nombre_documento]
    
    return "Consultar con la encargada (se comunicará en breve)"

# ========== ENDPOINTS ==========
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    """Sirve el archivo generado para su descarga"""
    try:
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error al descargar {filename}: {e}")
        return "Archivo no encontrado", 404

@app.route("/webhook", methods=["POST"])
def webhook():
    global historial_mensajes
    
    data = request.get_json()
    
    # =========================================================
    # 🔇 FILTRO 1: SOLO PROCESAR MENSAJES RECIBIDOS
    # =========================================================
    event_type = data.get("event_type", "")
    
    if event_type != "message_received":
        return "OK", 200
    
    message_data = data.get("data", {})
    
    # =========================================================
    # 🔇 FILTRO 2: ANTI-BUCLE
    # =========================================================
    incoming_msg = message_data.get("body", "").strip()
    sender = message_data.get("from", "").replace("@c.us", "").replace("+", "")
    sender_clean = sender.replace("+", "").replace(" ", "")
    connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
    
    # Ignorar mensajes del propio bot
    if message_data.get("fromMe") == True or message_data.get("self") == True:
        return "OK", 200
    
    # Ignorar mensajes del número conectado
    if sender_clean == connected_clean:
        return "OK", 200
    
    # Ignorar mensajes de la dueña
    if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
        return "OK", 200
    
    # Ignorar mensajes vacíos
    if not incoming_msg:
        return "OK", 200
    
    # =========================================================
    # 🔇 FILTRO 3: EVITAR DUPLICADOS POR CONTENIDO
    # =========================================================
    mensaje_normalizado = incoming_msg.lower().strip()
    
    if sender_clean not in historial_mensajes:
        historial_mensajes[sender_clean] = deque(maxlen=20)
    
    historial = historial_mensajes[sender_clean]
    
    if mensaje_normalizado in historial:
        logger.info(f"🔇 DUPLICADO POR CONTENIDO ignorado de {sender_clean}: {incoming_msg[:20]}")
        return "OK", 200
    
    historial.append(mensaje_normalizado)
    
    # =========================================================
    # FIN DEL FILTRO
    # =========================================================
    
    logger.info(f"✅ PROCESANDO: {sender_clean}: {incoming_msg[:30]}")
    
    # --- MENÚ PRINCIPAL ---
    if incoming_msg.lower() == "hola":
        templates = templates_loader.load_all_templates()
        enviar_menu(sender_clean, templates)
        
        if sender_clean not in user_sessions:
            user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
        else:
            user_sessions[sender_clean]["estado"] = "SELECT_TEMPLATE"
            user_sessions[sender_clean]["step"] = 0
            user_sessions[sender_clean]["answers"] = {}
        
        return "OK", 200
    
    # --- SELECCIONAR PLANTILLA (DOCUMENTOS 1-17) ---
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
    
    # =========================================================
    # 🆕 OPCIÓN 18: OTROS (SISBÉN / ADRES)
    # =========================================================
    
    # --- SUBMENÚ DE OTROS ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "SELECT_TEMPLATE":
        if incoming_msg == "18":
            user_sessions[sender_clean]["estado"] = "SELECCIONAR_OTROS"
            enviar_whatsapp(sender_clean, "📋 Opciones de Otros:\n\n1. Certificado de Sisbén\n2. Certificado de Adres\n\nResponde con el número de la opción.")
            return "OK", 200
    
    # --- SELECCIONAR SISBÉN O ADRES ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "SELECCIONAR_OTROS":
        if incoming_msg == "1":
            user_sessions[sender_clean]["estado"] = "ASKING_SISBEN_TIPO"
            user_sessions[sender_clean]["answers"] = {}
            user_sessions[sender_clean]["answers"]["tipo"] = "Sisbén"
            enviar_whatsapp(sender_clean, "📄 Escribe el TIPO de documento (CC, CE, TI, etc.):")
            return "OK", 200
        
        elif incoming_msg == "2":
            user_sessions[sender_clean]["estado"] = "ASKING_ADRES_TIPO"
            user_sessions[sender_clean]["answers"] = {}
            user_sessions[sender_clean]["answers"]["tipo"] = "Adres"
            enviar_whatsapp(sender_clean, "📄 Escribe el TIPO de documento (CC, CE, TI, etc.):")
            return "OK", 200
        
        else:
            enviar_whatsapp(sender_clean, "❌ Opción no válida. Elige 1 para Sisbén o 2 para Adres.")
            return "OK", 200
    
    # --- PREGUNTAS SISBÉN ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_TIPO":
        user_sessions[sender_clean]["answers"]["tipo_documento"] = incoming_msg
        user_sessions[sender_clean]["estado"] = "ASKING_SISBEN_NUMERO"
        enviar_whatsapp(sender_clean, "🔢 Escribe el NÚMERO de documento:")
        return "OK", 200
    
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_NUMERO":
        user_sessions[sender_clean]["answers"]["numero_documento"] = incoming_msg
        answers = user_sessions[sender_clean]["answers"]
        
        # Enviar a la dueña
        mensaje_duena = f"📄 *Solicitud de {answers['tipo']}*\n\nTipo de documento: {answers['tipo_documento']}\nNúmero de documento: {answers['numero_documento']}\n\n📌 La encargada debe realizar la consulta manualmente."
        enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
        
        # Mensaje al cliente
        enviar_whatsapp(sender_clean, f"✅ Solicitud de {answers['tipo']} enviada correctamente.\n\nLa encargada revisará tu solicitud y te contactará en breve.")
        
        user_sessions.pop(sender_clean, None)
        return "OK", 200
    
    # --- PREGUNTAS ADRES ---
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_ADRES_TIPO":
        user_sessions[sender_clean]["answers"]["tipo_documento"] = incoming_msg
        user_sessions[sender_clean]["estado"] = "ASKING_ADRES_NUMERO"
        enviar_whatsapp(sender_clean, "🔢 Escribe el NÚMERO de documento:")
        return "OK", 200
    
    if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_ADRES_NUMERO":
        user_sessions[sender_clean]["answers"]["numero_documento"] = incoming_msg
        answers = user_sessions[sender_clean]["answers"]
        
        # Enviar a la dueña
        mensaje_duena = f"📄 *Solicitud de {answers['tipo']}*\n\nTipo de documento: {answers['tipo_documento']}\nNúmero de documento: {answers['numero_documento']}\n\n📌 La encargada debe realizar la consulta manualmente."
        enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
        
        # Mensaje al cliente
        enviar_whatsapp(sender_clean, f"✅ Solicitud de {answers['tipo']} enviada correctamente.\n\nLa encargada revisará tu solicitud y te contactará en breve.")
        
        user_sessions.pop(sender_clean, None)
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
                
                # Generar el Word
                output_path, output_filename = generar_word(answers, folder, config_data)
                
                # Construir el enlace de descarga
                descarga_url = f"{BASE_URL}/descargar/{output_filename}"
                
                # Obtener el nombre y precio del documento
                nombre_documento = config_data.get('name', 'Documento')
                precio = obtener_precio(nombre_documento)
                
                # --- MENSAJE PARA EL CLIENTE ---
                mensaje_cliente = f"✅ Solicitud enviada correctamente.\n\n📄 Documento: {nombre_documento}\n💰 Valor: {precio}\n\nLa encargada revisará tu documento y te contactará en breve."
                enviar_whatsapp(sender_clean, mensaje_cliente)
                
                # --- MENSAJE PARA LA DUEÑA ---
                mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nDocumento: {nombre_documento}\n💰 Valor: {precio}\n\n🔗 Descarga: {descarga_url}"
                enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                
                logger.info(f"📄 Documento generado y enlace enviado a la dueña: {descarga_url}")
                
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