import os, json
BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
def load_all_templates():
    templates = []
    if not os.path.exists(TEMPLATES_DIR): return templates
    for folder in os.listdir(TEMPLATES_DIR):
        config_path = os.path.join(TEMPLATES_DIR, folder, "config.json")
        if os.path.isdir(os.path.join(TEMPLATES_DIR, folder)) and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                config["folder"] = folder
                templates.append(config)
    return templates
def get_template_config(folder_name):
    config_path = os.path.join(TEMPLATES_DIR, folder_name, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        config["folder"] = folder_name
        return config