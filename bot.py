import os
import logging
import requests
import json
from flask import Flask, request
import pytz
from datetime import datetime

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")
OWNER_WHATSAPP = "573247247478"  # Número de la dueña

# --- EL NÚMERO CONECTADO A ULTRAMSG (el que está en los logs con @c.us) ---
CONNECTED_NUMBER = "573167913339"

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

def obtener_saludo():
    colombia_tz = pytz.timezone('America/Bogota')
    hour = datetime.now(colombia_tz).hour
    if 6 <= hour < 12:
        return "Buenos dias"
    elif 12 <= hour < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# --- SESIONES EN MEMORIA ---
user_sessions = {}

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
        
        # ========== FILTRO CRÍTICO: IGNORAR MENSAJES DEL NÚMERO CONECTADO ==========
        # ELIMINAMOS @c.us y el + para comparar correctamente
        connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
        sender_clean = sender.replace("+", "").replace(" ", "")
        
        # Si el mensaje viene del número conectado a Ultramsg, lo ignoramos COMPLETAMENTE
        if sender_clean == connected_clean:
            logger.info(f"🔇 IGNORANDO mensaje del número conectado ({sender_clean}): {incoming_msg}")
            return "OK", 200
        
        # Si el mensaje viene de la dueña, lo ignoramos
        if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
            logger.info(f"🔇 IGNORANDO mensaje de la dueña ({sender_clean}): {incoming_msg}")
            return "OK", 200
        
        logger.info(f"Mensaje de {sender_name} ({sender_clean}): {incoming_msg}")
        
        # ========== MENÚ PRINCIPAL ==========
        if incoming_msg.lower() == "hola":
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue tipo de documento necesitas?\n1. Poder para Tramite de Vehiculo\n\nResponde con el numero de la opcion."
            enviar_whatsapp(sender_clean, menu)
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
            return "OK", 200
        
        # ========== SELECCIONAR PLANTILLA ==========
        if incoming_msg == "1":
            enviar_whatsapp(sender_clean, "Perfecto! Necesito algunos datos para generar el documento.\n\nEscribe el DIA de la fecha (ej: 10):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_DATA", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_DATA"
                user_sessions[sender_clean]["step"] = 0
            return "OK", 200
        
        # ========== PREGUNTAS ==========
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
        
        # ========== CONFIRMACION ==========
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                answers = user_sessions[sender_clean]["answers"]
                mensaje_cliente = "✅ Solicitud enviada correctamente!\n\nLa encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\nGracias por usar nuestro servicio."
                enviar_whatsapp(sender_clean, mensaje_cliente)
                mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}"
                enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                user_sessions.pop(sender_clean, None)
                return "OK", 200
            elif incoming_msg.lower() in ["no", "cancelar"]:
                enviar_whatsapp(sender_clean, "Operacion cancelada. Escribe 'hola' para comenzar de nuevo.")
                user_sessions.pop(sender_clean, None)
                return "OK", 200
            else:
                enviar_whatsapp(sender_clean, "Responde SI para generar el documento o NO para cancelar.")
                return "OK", 200
        
        # ========== FALLBACK (SOLO PARA CLIENTES) ==========
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
