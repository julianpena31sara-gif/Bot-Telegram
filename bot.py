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
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP")  # Número de la dueña (sin +)

# --- FUNCIONES DE ULTRAMSG ---
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

# --- SESIONES EN MEMORIA (para mantener el estado de cada usuario) ---
user_sessions = {}

# --- ENDPOINT PRINCIPAL ---
@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de Ultramsg y responde rápidamente"""
    # Responder a Ultramsg INMEDIATAMENTE (antes de procesar)
    # Esto evita que Ultramsg muestre "I don't know this command"
    
    data = request.get_json()
    logger.info(f"Mensaje recibido: {data}")
    
    if data and "data" in data:
        # Extraer datos del mensaje
        message_data = data["data"]
        incoming_msg = message_data.get("body", "").strip()
        sender = message_data.get("from", "").replace("+", "")
        sender_name = message_data.get("name", sender)
        
        logger.info(f"Mensaje de {sender_name} ({sender}): {incoming_msg}")
        
        # ========== RESPUESTA RÁPIDA ==========
        # Si el mensaje es "hola", respondemos con el menú
        if incoming_msg.lower() == "hola":
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue tipo de documento necesitas?\n1. Poder para Tramite de Vehiculo\n\nResponde con el numero de la opcion."
            enviar_whatsapp(sender, menu)
            return "OK", 200
        
        # Si el mensaje es "1" (selecciona el documento)
        if incoming_msg == "1":
            enviar_whatsapp(sender, "Perfecto! Necesito algunos datos para generar el documento.\n\nEscribe el DIA de la fecha (ej: 10):")
            # Guardar estado del usuario (para futuros mensajes)
            if sender not in user_sessions:
                user_sessions[sender] = {"estado": "ASKING_DATA", "step": 0, "answers": {}}
            return "OK", 200
        
        # Si el mensaje es "cancelar", reiniciamos
        if incoming_msg.lower() in ["cancelar", "cancel"]:
            enviar_whatsapp(sender, "Operacion cancelada. Escribe 'hola' para comenzar de nuevo.")
            user_sessions.pop(sender, None)
            return "OK", 200
        
        # ========== PREGUNTAS DEL DOCUMENTO ==========
        if sender in user_sessions and user_sessions[sender]["estado"] == "ASKING_DATA":
            session = user_sessions[sender]
            step = session["step"]
            answers = session["answers"]
            
            # Campos del documento
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
            
            # Guardar respuesta
            if step < len(fields):
                field_key = fields[step]["key"]
                answers[field_key] = incoming_msg
                session["step"] = step + 1
                
                # Si hay más preguntas, preguntar la siguiente
                if session["step"] < len(fields):
                    next_question = fields[session["step"]]["question"]
                    enviar_whatsapp(sender, next_question)
                    return "OK", 200
                else:
                    # Ya no hay más preguntas
                    session["estado"] = "REVIEW_DATA"
                    summary = "REVISION DE DATOS\n\n"
                    for key, value in answers.items():
                        clean_key = key.replace("_", " ").title()
                        summary += f"{clean_key}: {value}\n"
                    summary += "\nEstan correctos? Responde SI o NO."
                    enviar_whatsapp(sender, summary)
                    return "OK", 200
        
        # ========== CONFIRMACION ==========
        if sender in user_sessions and user_sessions[sender]["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                answers = user_sessions[sender]["answers"]
                
                # Generar mensaje de confirmación (sin Word por ahora)
                mensaje_cliente = "✅ Solicitud enviada correctamente!\n\nLa encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\nGracias por usar nuestro servicio."
                enviar_whatsapp(sender, mensaje_cliente)
                
                # Notificar a la dueña
                if OWNER_WHATSAPP:
                    mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                
                user_sessions.pop(sender, None)
                return "OK", 200
            
            elif incoming_msg.lower() in ["no", "cancelar"]:
                enviar_whatsapp(sender, "Operacion cancelada. Escribe 'hola' para comenzar de nuevo.")
                user_sessions.pop(sender, None)
                return "OK", 200
            else:
                enviar_whatsapp(sender, "Responde SI para generar el documento o NO para cancelar.")
                return "OK", 200
        
        # ========== FALLBACK ==========
        enviar_whatsapp(sender, "No entendi tu mensaje. Escribe 'hola' para comenzar.")
        return "OK", 200
    
    # Si no hay datos, responder OK igualmente
    return "OK", 200

# --- INICIO ---
@app.route("/", methods=["GET"])
def home():
    return "Bot de WhatsApp funcionando con Ultramsg"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
