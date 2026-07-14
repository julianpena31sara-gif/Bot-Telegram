import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

# --- ORDEN MANUAL DE LOS DOCUMENTOS ---
ORDEN_MENU = [
    "compraventa_vehiculo",
    "compraventa_inmueble",
    "arrendamiento_casa",
    "arrendamiento_local",
    "poder_amplio",
    "autorizacion",
    "cotizacion",
    "acuerdo_pago",
    "cuenta_cobro",
    "referencia_personal",
    "contrato_obra_civil",
    "declaracion_jurada",
    "permiso_menor",
    "acta_conciliacion",
    "constancia_cuidado",
    "contrato_laboral",
    "paz_salvo_impuesto"
]

def load_all_templates():
    """Carga todas las plantillas en el orden definido en ORDEN_MENU"""
    templates = []
    if not TEMPLATES_DIR.exists():
        return templates

    # Primero cargamos todas las plantillas en un diccionario
    templates_dict = {}
    for folder in TEMPLATES_DIR.iterdir():
        if folder.is_dir():
            config_path = folder / "config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        config["folder"] = folder.name
                        templates_dict[folder.name] = config
                        print(f"✅ Plantilla cargada: {config.get('name', folder.name)}")
                except Exception as e:
                    print(f"❌ Error al cargar {config_path}: {e}")
    
    # Luego las agregamos en el orden definido
    for folder_name in ORDEN_MENU:
        if folder_name in templates_dict:
            templates.append(templates_dict[folder_name])
    
    # Agregar las que no están en el orden (por si acaso)
    for folder_name, config in templates_dict.items():
        if folder_name not in ORDEN_MENU:
            templates.append(config)
    
    return templates

def get_template_config(folder_name):
    """Devuelve la configuración de una plantilla específica"""
    config_path = TEMPLATES_DIR / folder_name / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"No se encontró config.json en {folder_name}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        config["folder"] = folder_name
        return config