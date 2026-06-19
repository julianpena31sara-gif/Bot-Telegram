import os
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from docxtpl import DocxTemplate
import config
import templates_loader

# --- CONFIGURACIÓN INICIAL ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Carpeta donde se guardarán los archivos generados
OUTPUT_DIR = "generados"
Path(OUTPUT_DIR).mkdir(exist_ok=True)

# --- FUNCIÓN PRINCIPAL QUE MANEJA TODO ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja todos los mensajes y callbacks según el estado del usuario"""
    
    # Si es un callback (clic en botón)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        print(f"🔍 Callback recibido: {data}")
        
        # --- Menú principal: selección de plantilla ---
        if data.startswith("select_"):
            folder = data.replace("select_", "")
            context.user_data["template_folder"] = folder
            template_config = templates_loader.get_template_config(folder)
            context.user_data["template_config"] = template_config
            context.user_data["current_field_index"] = 0
            context.user_data["answers"] = {}
            context.user_data["estado"] = "ASKING_DATA"
            await ask_question(update, context)
            return
        
        # --- Botones del resumen ---
        if data == "confirm_generate":
            await generate_document(update, context)
            return
        if data == "cancel":
            await cancel(update, context)
            return
        
        # Si llega algo no reconocido
        await query.edit_message_text("❌ Opción no reconocida. Escribe /start para comenzar de nuevo.")
        return
    
    # --- Si es un mensaje de texto ---
    if update.message and update.message.text:
        text = update.message.text
        estado = context.user_data.get("estado")
        
        # Comando /start
        if text.startswith("/start"):
            await start(update, context)
            return
        
        # Si estamos en modo de preguntas
        if estado == "ASKING_DATA":
            await receive_answer(update, context)
            return
        
        # Si no está en un estado válido, mostrar el menú
        await start(update, context)

# --- FUNCIONES DEL FLUJO ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el menú de plantillas"""
    templates = templates_loader.load_all_templates()
    if not templates:
        await update.message.reply_text("⚠️ No hay plantillas configuradas.")
        return
    
    keyboard = []
    for t in templates:
        keyboard.append([InlineKeyboardButton(t["name"], callback_data=f"select_{t['folder']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 ¡Hola! Selecciona el tipo de documento que necesitas generar:",
        reply_markup=reply_markup
    )
    context.user_data["estado"] = "SELECT_TEMPLATE"

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía la pregunta actual al usuario"""
    config_data = context.user_data["template_config"]
    fields = config_data["fields"]
    idx = context.user_data.get("current_field_index", 0)
    
    if idx < len(fields):
        field = fields[idx]
        text = f"{field['question']}\n\n_(Escribe tu respuesta y envíala)_"
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
    else:
        # Ya no hay más preguntas, mostrar resumen
        await review_data(update, context)

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda la respuesta y pasa a la siguiente pregunta"""
    user_answer = update.message.text
    config_data = context.user_data["template_config"]
    fields = config_data["fields"]
    idx = context.user_data.get("current_field_index", 0)
    
    if idx < len(fields):
        field_key = fields[idx]["key"]
        context.user_data["answers"][field_key] = user_answer
        context.user_data["current_field_index"] = idx + 1
        await ask_question(update, context)

async def review_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el resumen y los botones de confirmación"""
    print("📋 review_data fue llamado")
    answers = context.user_data.get("answers", {})
    
    summary = "✅ *REVISIÓN DE DATOS*\n\n"
    for key, value in answers.items():
        clean_key = key.replace("_", " ").title()
        summary += f"📌 *{clean_key}:* {value}\n"
    summary += "\n¿Están correctos todos los datos?"
    
    keyboard = [
        [InlineKeyboardButton("✅ Sí, generar documento", callback_data="confirm_generate")],
        [InlineKeyboardButton("✏️ Cancelar y empezar de nuevo", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=reply_markup)
    
    context.user_data["estado"] = "REVIEW_DATA"

async def generate_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera el Word y lo envía a la dueña"""
    print("🚀 generate_document fue llamado")
    query = update.callback_query
    await query.edit_message_text("⏳ *Generando el documento... espera un momento*", parse_mode="Markdown")

    answers = context.user_data.get("answers", {})
    folder = context.user_data.get("template_folder")
    config_data = context.user_data.get("template_config")

    if not folder or not config_data:
        await query.edit_message_text("❌ Error: No se encontraron datos. Escribe /start para comenzar de nuevo.")
        return

    template_path = os.path.join("templates", folder, config_data["template_file"])
    template_path_abs = os.path.abspath(template_path)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"Traspaso_{answers.get('placa', 'sin_placa')}_{now}.docx"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    try:
        if not os.path.exists(template_path_abs):
            await query.edit_message_text(
                f"❌ *Error: No se encuentra la plantilla*\n\n"
                f"Ruta buscada:\n`{template_path_abs}`\n\n"
                f"Asegúrate de que el archivo `template.docx` esté en la carpeta `templates/traspaso_moto/`",
                parse_mode="Markdown"
            )
            return

        try:
            from docxtpl import DocxTemplate
        except ImportError:
            await query.edit_message_text(
                "❌ *Error: Falta la librería 'docxtpl'*\n\n"
                "Abre la terminal y ejecuta:\n"
                "`pip install docxtpl`\n\n"
                "Luego detén el bot (Ctrl+C) y vuelve a ejecutarlo.",
                parse_mode="Markdown"
            )
            return

        doc = DocxTemplate(template_path_abs)
        doc.render(answers)
        doc.save(output_path)

        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=config.OWNER_ID,
                document=f,
                filename=output_filename,
                caption=(
                    f"📄 *Nuevo documento generado*\n\n"
                    f"👤 Solicitado por: @{update.effective_user.username or 'cliente'}\n"
                    f"🏍️ Placa: {answers.get('placa', 'N/A')}\n"
                    f"📌 Comprador: {answers.get('nombre_comprador', 'N/A')}\n\n"
                    f"_Revisa y reenvía al cliente_"
                ),
                parse_mode="Markdown"
            )

        await query.edit_message_text(
            "✅ *¡Documento generado exitosamente!*\n\n"
            "La encargada del trámite lo ha recibido en su chat para su revisión. "
            "En breve se comunicará contigo para entregarte el documento final.\n\n"
            "📌 *Placa:* " + answers.get("placa", "N/A"),
            parse_mode="Markdown"
        )

        context.user_data.clear()
        return

    except KeyError as e:
        await query.edit_message_text(
            f"❌ *Error en la plantilla de Word*\n\n"
            f"La variable `{e.args[0]}` no existe en los datos ingresados.\n\n"
            f"Revisa que el `template.docx` tenga EXACTAMENTE las mismas llaves que el `config.json`.",
            parse_mode="Markdown"
        )
        return

    except Exception as e:
        await query.edit_message_text(
            f"❌ *Error inesperado*\n\n"
            f"```\n{str(e)}\n```\n\n"
            f"Por favor, reenvía este mensaje al administrador.",
            parse_mode="Markdown"
        )
        return

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la operación"""
    print("🚀 cancel fue llamado")
    query = update.callback_query
    context.user_data.clear()
    await query.edit_message_text("🔄 Operación cancelada. Escribe /start para comenzar de nuevo.")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /getid para obtener el chat_id"""
    await update.message.reply_text(f"🆔 Tu ID de Telegram es: `{update.effective_chat.id}`", parse_mode="Markdown")

# --- MAIN ---
def main():
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Handler principal: captura todos los mensajes y callbacks
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    application.add_handler(CallbackQueryHandler(handle_message))
    
    # Comando /start y /getid
    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(CommandHandler("getid", get_id))
    
    print("🤖 Bot iniciado. Presiona Ctrl+C para detener.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()