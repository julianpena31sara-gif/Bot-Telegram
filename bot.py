import os
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, request, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from docxtpl import DocxTemplate
import templates_loader

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Credenciales de Twilio (variables de entorno)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM")  # Ej: whatsapp:+14155238886
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP")  # Número de la dueña (opcional)

# Carpeta de plantillas y archivos generados
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)

# URL pública de tu bot en Railway (sin / al final)
BASE_URL = "https://bot-telegram-production-3cc3.up.railway.app"

# Diccionario para manejar el estado de cada usuario
user_sessions = {}

# --- FUNCIONES AUXILIARES ---
def generar_word(answers, folder, config_data):
    """Genera el Word y devuelve la ruta del archivo"""
    template_path = os.path.join("templates", folder, config_data["template_file"])
    template_path_abs = os.path.abspath(template_path)
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Traspaso_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    doc = DocxTemplate(template_path_abs)
    doc.render(answers)
    doc.save(output_path)
    return output_path, output_filename

def enviar_mensaje_whatsapp(numero_destino, mensaje):
    """Envía un mensaje de texto por WhatsApp usando Twilio"""
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    message = client.messages.create(
        body=mensaje,
        from_=WHATSAPP_FROM,
        to=numero_destino
    )
    return message.sid

# --- ENDPOINT PARA DESCARGAR ARCHIVOS ---
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    """Sirve el archivo generado para su descarga"""
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

# --- ENDPOINT PRINCIPAL (WEBHOOK DE WHATSAPP) ---
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Recibe mensajes de WhatsApp y procesa el flujo del bot"""
    # Obtener datos del mensaje entrante
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")  # Número de WhatsApp del cliente
    
    # Inicializar sesión del usuario si no existe
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
    
    # --- FLUJO DE CONVERSACIÓN ---
    # Estado: START (menú principal)
    if session["estado"] == "START":
        templates = templates_loader.load_all_templates()
        if not templates:
            resp.message("⚠️ No hay plantillas disponibles. Contacta al administrador.")
        else:
            menu = "👋 Hola, soy el asistente de trámites.\n\nSelecciona una opción:\n"
            for i, t in enumerate(templates, 1):
                menu += f"{i}. {t['name']}\n"
            menu += "\nResponde con el número de la opción."
            resp.message(menu)
            session["estado"] = "SELECT_TEMPLATE"
        return str(resp)
    
    # Estado: SELECT_TEMPLATE (elige plantilla)
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
                
                # Hacer primera pregunta
                fields = template["fields"]
                first_question = fields[0]["question"]
                resp.message(f"{first_question}\n\n_(Escribe tu respuesta)_")
            else:
                resp.message("❌ Opción no válida. Elige un número del menú.")
        except ValueError:
            resp.message("❌ Por favor, responde con el número de la opción.")
        return str(resp)
    
    # Estado: ASKING_DATA (respondiendo preguntas)
    if session["estado"] == "ASKING_DATA":
        config_data = session["template_config"]
        fields = config_data["fields"]
        idx = session["current_field_index"]
        
        # Guardar respuesta
        if idx < len(fields):
            field_key = fields[idx]["key"]
            session["answers"][field_key] = incoming_msg
            session["current_field_index"] = idx + 1
            
            # Preguntar siguiente o mostrar resumen
            if session["current_field_index"] < len(fields):
                next_question = fields[session["current_field_index"]]["question"]
                resp.message(f"{next_question}\n\n_(Escribe tu respuesta)_")
                return str(resp)
            else:
                # Ya no hay más preguntas, mostrar resumen
                session["estado"] = "REVIEW_DATA"
                answers = session["answers"]
                summary = "✅ *REVISIÓN DE DATOS*\n\n"
                for key, value in answers.items():
                    clean_key = key.replace("_", " ").title()
                    summary += f"📌 *{clean_key}:* {value}\n"
                summary += "\n¿Están correctos? Responde SI o NO."
                resp.message(summary)
                return str(resp)
    
    # Estado: REVIEW_DATA (confirmar o cancelar)
    if session["estado"] == "REVIEW_DATA":
        if incoming_msg.lower() in ["si", "sí", "yes"]:
            # Generar documento
            try:
                config_data = session["template_config"]
                answers = session["answers"]
                folder = session["template_folder"]
                
                # Generar el Word
                output_path, output_filename = generar_word(answers, folder, config_data)
                
                # Construir enlace de descarga
                descarga_url = f"{BASE_URL}/descargar/{output_filename}"
                
                # Mensaje para el cliente con el enlace
                mensaje_cliente = (
                    f"✅ *¡Documento generado exitosamente!*\n\n"
                    f"Puedes descargarlo desde este enlace:\n"
                    f"{descarga_url}\n\n"
                    f"🔒 El enlace es válido por 24 horas.\n"
                    f"📌 *Placa:* {answers.get('placa', 'N/A')}"
                )
                resp.message(mensaje_cliente)
                
                # (Opcional) Enviar el enlace también a la dueña por WhatsApp
                if OWNER_WHATSAPP:
                    mensaje_duena = (
                        f"📄 *Nuevo documento generado*\n\n"
                        f"👤 Solicitado por: {sender}\n"
                        f"🏍️ Placa: {answers.get('placa', 'N/A')}\n"
                        f"📌 Comprador: {answers.get('nombre_comprador', 'N/A')}\n\n"
                        f"🔗 Descarga: {descarga_url}"
                    )
                    enviar_mensaje_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                
                # Limpiar sesión
                session.clear()
                session["estado"] = "START"
                
            except Exception as e:
                resp.message(f"❌ Error al generar el documento: {str(e)}")
                session["estado"] = "START"
        elif incoming_msg.lower() in ["no", "cancelar"]:
            resp.message("🔄 Operación cancelada. Escribe cualquier mensaje para comenzar de nuevo.")
            session.clear()
            session["estado"] = "START"
        else:
            resp.message("❌ Responde SI para generar el documento o NO para cancelar.")
        return str(resp)
    
    # Si llegamos aquí, reiniciamos la conversación
    resp.message("Escribe cualquier mensaje para comenzar.")
    session["estado"] = "START"
    return str(resp)

# --- INICIO DEL SERVIDOR ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
