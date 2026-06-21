import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

def load_all_templates():
    templates = []
    if not TEMPLATES_DIR.exists():
        return templates
    
    for folder in TEMPLATES_DIR.iterdir():
        if folder.is_dir():
            config_path = folder / "config.json"
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        config["folder"] = folder.name
                        templates.append(config)
                        print(f"✅ Plantilla cargada: {config.get('name', folder.name)}")
                except Exception as e:
                    print(f"❌ Error cargando {config_path}: {e}")
    return templates

def get_template_config(folder_name):
    config_path = TEMPLATES_DIR / folder_name / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        config["folder"] = folder_name
        return config
