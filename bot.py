import os
import requests
from flask import Flask, request

app = Flask(__name__)

ULTRA_INSTANCE_ID = os.getenv("ULTRA_INSTANCE_ID")
ULTRA_TOKEN = os.getenv("ULTRA_TOKEN")

def enviar_whatsapp(numero, mensaje):
    url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"
    payload = {"token": ULTRA_TOKEN, "to": numero, "body": mensaje}
    try:
        response = requests.post(url, json=payload)
        print(f"Enviado a {numero}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None

@app.route("/webhook", methods=["POST"])
def webhook():
    print("📨 Webhook recibido")  # Log para Railway
    data = request.get_json()
    print(f"Datos: {data}")
    
    if data and "data" in data:
        sender = data["data"].get("from", "").replace("+", "")
        mensaje = data["data"].get("body", "")
        print(f"Mensaje de {sender}: {mensaje}")
        
        # Responder al cliente
        enviar_whatsapp(sender, "Hola, esto es una prueba desde Railway")
        
        return "OK", 200  # Respuesta rápida para Ultramsg
    
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Bot funcionando"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
