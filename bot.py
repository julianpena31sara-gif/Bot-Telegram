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

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- VARIABLES DE ENTORNO ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM")          # Ej: whatsapp:+14155238886
OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP")        # Número de la dueña (OBLIGATORIO)
BASE_URL = os.getenv("BASE_URL", "https://bot-telegram-production-3cc3.up.railway.app")

# --- CARPETAS ---
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)
TEMPLATES_DIR = Path("templates")

# --- SESIONES EN MEMORIA ---
user_sessions = {}

# --- FUNCIÓN PARA OBTENER SALUDO SEGÚN LA HORA EN COLOMBIA ---
def obtener_saludo():
    colombia_tz = pytz.timezone('America/Bogota')
    now_colombia = datetime.now(colombia_tz)
    hour = now_colombia.hour
    if 6 <= hour < 12:
        return "Buenos días"
    elif 12 <= hour < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# --- FUNCIÓN PARA GENERAR WORD ---
def generar_word(answers, folder, config_data):
    try:
        template_file = config_data.get("template_file", "template.docx")
        template_path = TEMPLATES_DIR / folder / template_file
        template_path_abs = template_path.resolve()
        if not template_path_abs.exists():
            raise FileNotFoundError(f"Plantilla no encontrada: {template_path_abs}")
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"Traspaso_{answers.get('placa', 'sin_placa')}_{now}.docx"
        output_path = Path(OUTPUT_DIR) / output_filename
        doc = DocxTemplate(str(template_path_abs))
        doc.render(answers)
        doc.save(str(output_path))
        logger.info(f"✅ Documento generado: {output_filename}")
        return str(output_path), output_filename
    except Exception as e:
        logger.error(f"❌ Error en generar_word: {e}")
        raise

# --- FUNCIÓN PARA ENVIAR MENSAJE POR WHATSAPP ---
def enviar_mensaje_whatsapp(numero_destino, mensaje):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, WHATSAPP_FROM]):
        logger.warning("Faltan credenciales de Twilio, no se enviará mensaje.")
        return None
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=mensaje,
            from_=WHATSAPP_FROM,
            to=numero_destino
        )
        logger.info(f"📤 Mensaje enviado a {numero_destino}: {message.sid}")
        return message.sid
    except Exception as e:
        logger.error(f"❌ Error al enviar mensaje: {e}")
        return None

# --- ENDPOINT PARA DESCARGAR ---
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    try:
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"❌ Error al descargar {filename}: {e}")
        return "Archivo no encontrado", 404

# --- ENDPOINT PRINCIPAL (WEBHOOK) ---
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    logger.info("📨 Solicitud POST recibida en /whatsapp")
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")
    logger.info(f"👤 De: {sender} | Mensaje: {incoming_msg}")

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
        # --- MENÚ PRINCIPAL (START) ---
        if session["estado"] == "START":
            templates = templates_loader.load_all_templates()
            if not templates:
                logger.warning("No se cargaron plantillas")
                resp.message("⚠️ No hay plantillas disponibles. Contacta al administrador.")
                return str(resp)
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papelería Líder.\n\n¿Qué vas a hacer?\n"
            for i, t in enumerate(templates, 1):
                menu += f"{i}. {t['name']}\n"
            menu += "\nResponde con el número de la opción."
            resp.message(menu)
            session["estado"] = "SELECT_TEMPLATE"
            logger.info("📋 Menú con saludo enviado")
            return str(resp)

        # --- SELECCIÓN DE PLANTILLA ---
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
                    resp.message(f"{first_question}\n\n_(Escribe tu respuesta)_")
                    logger.info(f"📝 Primera pregunta: {first_question}")
                else:
                    resp.message("❌ Opción no válida. Elige un número del menú.")
            except ValueError:
                resp.message("❌ Responde con el número de la opción.")
            return str(resp)

        # --- RESPUESTA A PREGUNTAS ---
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
                    resp.message(f"{next_question}\n\n_(Escribe tu respuesta)_")
                    return str(resp)
                else:
                    session["estado"] = "REVIEW_DATA"
                    answers = session["answers"]
                    summary = "✅ *REVISIÓN DE DATOS*\n\n"
                    for key, value in answers.items():
                        clean_key = key.replace("_", " ").title()
                        summary += f"📌 *{clean_key}:* {value}\n"
                    summary += "\n¿Están correctos? Responde SI o NO."
                    resp.message(summary)
                    logger.info("📋 Resumen enviado")
                    return str(resp)

        # --- CONFIRMACIÓN (REVIEW_DATA) ---
        if session["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                try:
                    config_data = session["template_config"]
                    answers = session["answers"]
                    folder = session["template_folder"]

                    logger.info("📄 Generando documento...")
                    output_path, output_filename = generar_word(answers, folder, config_data)

                    # --- Generar enlace de descarga ---
                    descarga_url = f"{BASE_URL}/descargar/{output_filename}"
                    logger.info(f"🔗 Enlace de descarga generado: {descarga_url}")

                    # --- Mensaje para el CLIENTE (sin enlace) ---
                    mensaje_cliente = (
                        f"✅ *¡Documento generado exitosamente!*\n\n"
                        f"La encargada del trámite lo ha recibido para su revisión. "
                        f"En breve se comunicará contigo para entregarte el documento final.\n\n"
                        f"📌 *Placa:* {answers.get('placa', 'N/A')}"
                    )
                    resp.message(mensaje_cliente)

                    # --- Mensaje para la DUEÑA (con enlace) ---
                    if OWNER_WHATSAPP:
                        mensaje_duena = (
                            f"📄 *Nuevo documento generado*\n\n"
                            f"👤 Solicitado por: {sender}\n"
                            f"🏍️ Placa: {answers.get('placa', 'N/A')}\n"
                            f"📌 Comprador: {answers.get('nombre_comprador', 'N/A')}\n\n"
                            f"🔗 Descarga el documento aquí:\n{descarga_url}"
                        )
                        enviar_mensaje_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    else:
                        logger.warning("⚠️ OWNER_WHATSAPP no configurado. El enlace no se envió a nadie.")

                    session.clear()
                    session["estado"] = "START"

                except Exception as e:
                    logger.error(f"❌ Error en generación: {e}", exc_info=True)
                    resp.message(f"❌ Error al generar el documento: {str(e)}")
                    session.clear()
                    session["estado"] = "START"
                return str(resp)

            elif incoming_msg.lower() in ["no", "cancelar"]:
                saludo = obtener_saludo()
                resp.message(f"{saludo}. Operación cancelada. Escribe cualquier mensaje para comenzar de nuevo.")
                session.clear()
                session["estado"] = "START"
                return str(resp)
            else:
                resp.message("❌ Responde SI para generar el documento o NO para cancelar.")
                return str(resp)

        # --- ESTADO NO RECONOCIDO (FALLBACK) ---
        saludo = obtener_saludo()
        resp.message(f"{saludo}. Escribe cualquier mensaje para comenzar.")
        session["estado"] = "START"
        return str(resp)

    except Exception as e:
        logger.error(f"❌ Error inesperado en webhook: {e}", exc_info=True)
        resp.message("❌ Ocurrió un error inesperado. Intenta de nuevo.")
        session.clear()
        session["estado"] = "START"
        return str(resp)

# --- INICIO DEL SERVIDOR ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    app.run(host="0.0.0.0", port=port)
