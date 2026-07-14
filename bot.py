import os
import logging
import requests
import json
from flask import Flask, request

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")
CONNECTED_NUMBER = os.getenv("CONNECTED_NUMBER", "573167913339")

# ========== FUNCIONES DE ULTRAMSG ==========
def enviar_whatsapp(numero, mensaje):
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"
    payload = {"token": ULTRA_TOKEN, "to": numero, "body": mensaje}
    try:
        response = requests.post(url, json=payload, timeout=3)
        if response.status_code == 200:
            logger.info(f"Mensaje enviado a {numero}")
        else:
            logger.error(f"Error: {response.text}")
        return response
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

# ========== ENDPOINT PRINCIPAL ==========
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    
    # Solo procesar mensajes recibidos
    event_type = data.get("event_type", "")
    if event_type != "message_received":
        return "OK", 200
    
    message_data = data.get("data", {})
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
    
    # Ignorar mensajes vacíos
    if not incoming_msg:
        return "OK", 200
    
    logger.info(f"✅ PROCESANDO: {sender_clean}: {incoming_msg}")
    
    # --- RESPUESTA DE PRUEBA ---
    if incoming_msg.lower() == "hola":
        enviar_whatsapp(sender_clean, "✅ Mensaje de prueba - El bot está funcionando correctamente.")
        return "OK", 200
    
    # --- FALLBACK ---
    enviar_whatsapp(sender_clean, "Escribe 'hola' para probar el bot.")
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot de prueba funcionando"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)