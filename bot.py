import os
import logging
import requests
import json
from flask import Flask, request, send_from_directory
import pytz
from datetime import datetime
from pathlib import Path
from docxtpl import DocxTemplate
from bs4 import BeautifulSoup
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

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

# --- FUNCIONES DE ULTRAMSG ---
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
        "caption": "📄 Documento generado automáticamente por Papeleria Lider"
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
        return "Buenos dias"
    elif 12 <= hour < 18:
        return "Buenas tardes"
    else:
        return "Buenas noches"

# --- FUNCIÓN DE SCRAPING REAL CON SELENIUM ---
def consultar_sisben_real(tipo_documento, numero_documento):
    """
    Consulta la página del Sisbén usando Selenium y devuelve los datos reales
    """
    logger.info(f"Consultando Sisbén para {tipo_documento}: {numero_documento}")
    
    # Configurar Chrome en modo headless (sin interfaz gráfica)
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Ejecutar sin ventana
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    try:
        # Inicializar driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)
        
        # 1. Ir a la página de consulta
        url = "https://www.sisben.gov.co/Paginas/consulta-tu-grupo.html"
        logger.info(f"Cargando página: {url}")
        driver.get(url)
        time.sleep(2)  # Esperar carga inicial
        
        # 2. Llenar el formulario
        # Buscar el campo de tipo de documento (puede ser un select o input)
        try:
            # Intentar con el ID real del campo (debes inspeccionar la página)
            tipo_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "tipoDocumento"))
            )
            tipo_input.send_keys(tipo_documento)
            logger.info(f"Tipo de documento ingresado: {tipo_documento}")
        except:
            # Si no encuentra por ID, intentar por nombre
            tipo_input = driver.find_element(By.NAME, "tipoDocumento")
            tipo_input.send_keys(tipo_documento)
        
        # Buscar el campo de número de documento
        try:
            num_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "numeroDocumento"))
            )
            num_input.send_keys(numero_documento)
            logger.info(f"Número de documento ingresado: {numero_documento}")
        except:
            num_input = driver.find_element(By.NAME, "numeroDocumento")
            num_input.send_keys(numero_documento)
        
        # 3. Hacer clic en el botón de consulta
        try:
            boton = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "btnConsultar"))
            )
            boton.click()
            logger.info("Botón de consulta presionado")
        except:
            # Intentar otros selectores comunes
            boton = driver.find_element(By.CLASS_NAME, "btn-consultar")
            boton.click()
        
        # 4. Esperar que carguen los resultados
        time.sleep(3)  # Esperar a que la página procese la consulta
        
        # 5. Extraer los datos de la página de resultados
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # --- EXTRAER DATOS (AJUSTA LAS CLASES SEGÚN EL HTML REAL) ---
        # Función auxiliar para extraer texto
        def extraer_texto(elemento, selector, atributo="class"):
            try:
                if atributo == "class":
                    elem = elemento.find(class_=selector)
                elif atributo == "id":
                    elem = elemento.find(id=selector)
                else:
                    elem = elemento.find(selector)
                if elem:
                    return elem.text.strip()
                return "No disponible"
            except:
                return "No disponible"
        
        datos = {
            "nombres": extraer_texto(soup, "nombres"),
            "apellidos": extraer_texto(soup, "apellidos"),
            "tipo_documento": tipo_documento,
            "numero_documento": numero_documento,
            "municipio": extraer_texto(soup, "municipio"),
            "departamento": extraer_texto(soup, "departamento"),
            "grupo": extraer_texto(soup, "grupo"),
            "categoria": extraer_texto(soup, "categoria"),
            "fecha_encuesta": extraer_texto(soup, "fecha_encuesta"),
            "fecha_actualizacion": extraer_texto(soup, "fecha_actualizacion"),
            "nombre_administrador": extraer_texto(soup, "nombre_administrador"),
            "direccion_oficina": extraer_texto(soup, "direccion_oficina"),
            "telefono_oficina": extraer_texto(soup, "telefono_oficina"),
            "email_oficina": extraer_texto(soup, "email_oficina"),
            "fecha_consulta": datetime.now().strftime("%d/%m/%Y %H:%M")
        }
        
        logger.info(f"Datos extraídos: {datos}")
        
        # Verificar si se encontraron datos
        if datos["nombres"] == "No disponible" and datos["apellidos"] == "No disponible":
            logger.warning("No se encontraron datos para el documento ingresado")
            return None
        
        return datos
        
    except Exception as e:
        logger.error(f"Error en consulta Sisbén: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            logger.info("Driver cerrado")

# --- FUNCIÓN PARA GENERAR PDF DE SISBÉN ---
def generar_pdf_sisben(datos, output_path):
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    
    # --- ENCABEZADO ---
    y = height - 40
    
    # Fecha de consulta
    c.setFont("Helvetica", 8)
    fecha_consulta = datos.get("fecha_consulta", datetime.now().strftime("%d/%m/%Y %H:%M"))
    c.drawRightString(width - 50, y, f"Fecha de consulta: {fecha_consulta}")
    
    # Ficha
    c.setFont("Helvetica-Bold", 8)
    c.drawString(50, y, "Ficha:")
    c.setFont("Helvetica", 8)
    c.drawString(100, y, "41132004748100000116")
    
    y -= 30
    
    # --- LÍNEA DE ESTADO ---
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Registro válido")
    y -= 20
    
    # --- GRUPO Y CATEGORÍA ---
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(colors.Color(0.2, 0.4, 0.6))
    c.drawString(50, y, datos.get("grupo", "N/A"))
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(colors.black)
    c.drawString(150, y + 10, datos.get("categoria", "N/A"))
    y -= 40
    
    # --- DATOS PERSONALES ---
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "DATOS PERSONALES")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Nombres: {datos.get('nombres', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Apellidos: {datos.get('apellidos', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Tipo de documento: {datos.get('tipo_documento', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Número de documento: {datos.get('numero_documento', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Municipio: {datos.get('municipio', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Departamento: {datos.get('departamento', 'No disponible')}")
    y -= 25
    
    # --- INFORMACIÓN ADMINISTRATIVA ---
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "INFORMACIÓN ADMINISTRATIVA")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Encuesta vigente: {datos.get('fecha_encuesta', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Última actualización ciudadano: {datos.get('fecha_actualizacion', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Última actualización via registros administrativos: {datos.get('fecha_actualizacion', 'No disponible')}")
    y -= 30
    
    # --- CONTACTO OFICINA ---
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.Color(0.1, 0.3, 0.5))
    c.drawString(50, y, "Contacto Oficina SISBEN")
    y -= 20
    
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(50, y, f"Nombre administrador: {datos.get('nombre_administrador', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Dirección: {datos.get('direccion_oficina', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Teléfono: {datos.get('telefono_oficina', 'No disponible')}")
    y -= 15
    c.drawString(50, y, f"Correo Electrónico: {datos.get('email_oficina', 'No disponible')}")
    y -= 30
    
    # --- PIE DE PÁGINA ---
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.gray)
    c.drawString(50, 50, "*Si encuentra alguna inconsistencia o desea actualizar su información por favor acérquese a la oficina del Sisbén del municipio donde reside actualmente")
    
    c.save()
    logger.info(f"PDF de Sisbén generado: {output_path}")

# --- FUNCIONES DE PLANTILLAS ---
def generar_word(answers, folder="poder_vehiculo"):
    template_path = TEMPLATES_DIR / folder / "template.docx"
    if not template_path.exists():
        template_path = Path("template.docx")
        if not template_path.exists():
            raise FileNotFoundError(f"Plantilla no encontrada en templates/{folder}/template.docx")
    
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Poder_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = Path(OUTPUT_DIR) / output_filename
    
    doc = DocxTemplate(str(template_path))
    doc.render(answers)
    doc.save(str(output_path))
    
    logger.info(f"Documento generado: {output_filename}")
    return str(output_path), output_filename

# --- ENDPOINT PARA DESCARGAR ---
@app.route("/descargar/<filename>", methods=["GET"])
def descargar_archivo(filename):
    try:
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error al descargar {filename}: {e}")
        return "Archivo no encontrado", 404

# --- ENDPOINT PRINCIPAL ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logger.info(f"Mensaje recibido: {data}")
    
    if data and "data" in data:
        message_data = data["data"]
        incoming_msg = message_data.get("body", "").strip()
        sender = message_data.get("from", "").replace("@c.us", "").replace("+", "")
        sender_name = message_data.get("pushname", sender)
        
        connected_clean = CONNECTED_NUMBER.replace("+", "").replace(" ", "")
        sender_clean = sender.replace("+", "").replace(" ", "")
        
        if sender_clean == connected_clean:
            logger.info(f"🔇 Ignorando mensaje del número conectado: {incoming_msg}")
            return "OK", 200
        
        if OWNER_WHATSAPP and sender_clean == OWNER_WHATSAPP.replace("+", "").replace(" ", ""):
            logger.info(f"🔇 Ignorando mensaje de la dueña: {incoming_msg}")
            return "OK", 200
        
        logger.info(f"Mensaje de {sender_name} ({sender_clean}): {incoming_msg}")
        
        # --- MENÚ PRINCIPAL ---
        if incoming_msg.lower() == "hola":
            saludo = obtener_saludo()
            menu = f"Hola, {saludo}. Soy el asistente de la Papeleria Lider.\n\nQue tipo de documento necesitas?\n1. Poder para Tramite de Vehiculo\n2. Certificado de Sisbén\n3. Certificado de ADRES\n\nResponde con el numero de la opcion."
            enviar_whatsapp(sender_clean, menu)
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "SELECT_TEMPLATE", "step": 0, "answers": {}}
            return "OK", 200
        
        # --- SELECCIONAR PLANTILLA ---
        if incoming_msg == "1":
            enviar_whatsapp(sender_clean, "Perfecto! Necesito algunos datos para generar el documento.\n\nEscribe el DIA de la fecha (ej: 10):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_DATA", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_DATA"
                user_sessions[sender_clean]["step"] = 0
            return "OK", 200
        
        # --- SISBÉN ---
        if incoming_msg == "2":
            enviar_whatsapp(sender_clean, "Escribe el TIPO de documento (CC, CE, etc.):")
            if sender_clean not in user_sessions:
                user_sessions[sender_clean] = {"estado": "ASKING_SISBEN_TIPO", "step": 0, "answers": {}}
            else:
                user_sessions[sender_clean]["estado"] = "ASKING_SISBEN_TIPO"
            return "OK", 200
        
        # --- PREGUNTAS DEL DOCUMENTO (PODER) ---
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
        
        # --- PREGUNTAS DE SISBÉN ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_TIPO":
            session = user_sessions[sender_clean]
            session["answers"]["tipo_documento"] = incoming_msg
            session["estado"] = "ASKING_SISBEN_NUMERO"
            enviar_whatsapp(sender_clean, "Escribe el NUMERO de documento:")
            return "OK", 200
        
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "ASKING_SISBEN_NUMERO":
            session = user_sessions[sender_clean]
            tipo_doc = session["answers"]["tipo_documento"]
            num_doc = incoming_msg
            
            enviar_whatsapp(sender_clean, "⏳ Consultando información en el Sisbén...")
            
            try:
                # Consulta real con Selenium
                datos = consultar_sisben_real(tipo_doc, num_doc)
                
                if datos:
                    output_filename = f"Sisben_{num_doc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    output_path = Path(OUTPUT_DIR) / output_filename
                    generar_pdf_sisben(datos, str(output_path))
                    
                    enviar_documento_ultramsg(OWNER_WHATSAPP, str(output_path), output_filename)
                    
                    mensaje_duena = f"📄 Certificado de Sisbén generado\n\nSolicitado por: {sender_clean}\nTipo: {tipo_doc}\nNúmero: {num_doc}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    
                    enviar_whatsapp(sender_clean, "✅ Certificado de Sisbén generado correctamente y enviado a la encargada.")
                else:
                    enviar_whatsapp(sender_clean, "❌ No se encontró información para esos datos. Verifica el tipo y número de documento.")
            except Exception as e:
                logger.error(f"Error al procesar Sisbén: {e}")
                enviar_whatsapp(sender_clean, f"❌ Ocurrió un error al consultar el Sisbén: {str(e)}")
            
            user_sessions.pop(sender_clean, None)
            return "OK", 200
        
        # --- CONFIRMACIÓN (PODER) ---
        if sender_clean in user_sessions and user_sessions[sender_clean]["estado"] == "REVIEW_DATA":
            if incoming_msg.lower() in ["si", "sí", "yes"]:
                try:
                    answers = user_sessions[sender_clean]["answers"]
                    output_path, output_filename = generar_word(answers)
                    
                    enviar_whatsapp(sender_clean, "✅ Solicitud enviada correctamente!\n\nLa encargada de la Papeleria Lider revisara tu documento y te contactara en breve.\nGracias por usar nuestro servicio.")
                    
                    enviar_documento_ultramsg(OWNER_WHATSAPP, output_path, output_filename)
                    mensaje_duena = f"📄 Nuevo documento generado\n\nSolicitado por: {sender_clean}\nPlaca: {answers.get('placa', 'N/A')}\nPropietario: {answers.get('nombre_vendedor', 'N/A')}"
                    enviar_whatsapp(OWNER_WHATSAPP, mensaje_duena)
                    
                    user_sessions.pop(sender_clean, None)
                    
                except Exception as e:
                    logger.error(f"Error al generar documento: {e}")
                    enviar_whatsapp(sender_clean, f"❌ Error al generar el documento: {str(e)}")
                    user_sessions.pop(sender_clean, None)
                return "OK", 200
            
            elif incoming_msg.lower() in ["no", "cancelar"]:
                enviar_whatsapp(sender_clean, "Operacion cancelada. Escribe 'hola' para comenzar de nuevo.")
                user_sessions.pop(sender_clean, None)
                return "OK", 200
            else:
                enviar_whatsapp(sender_clean, "Responde SI para generar el documento o NO para cancelar.")
                return "OK", 200
        
        # --- FALLBACK ---
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