import os
from pathlib import Path

CONTADORES_FILE = Path("contadores.txt")

def inicializar_contadores():
    """Crea el archivo de contadores si no existe"""
    if not CONTADORES_FILE.exists():
        with open(CONTADORES_FILE, "w", encoding="utf-8") as f:
            f.write("cotizacion=0\n")
            f.write("cuenta_cobro=0\n")

def leer_contador(tipo):
    """Lee el último número usado para un tipo de documento"""
    inicializar_contadores()
    with open(CONTADORES_FILE, "r", encoding="utf-8") as f:
        lineas = f.readlines()
        for linea in lineas:
            if linea.startswith(f"{tipo}="):
                return int(linea.split("=")[1].strip())
    return 0

def escribir_contador(tipo, numero):
    """Actualiza el número de un tipo de documento"""
    inicializar_contadores()
    lineas = []
    with open(CONTADORES_FILE, "r", encoding="utf-8") as f:
        lineas = f.readlines()
    
    encontrado = False
    for i, linea in enumerate(lineas):
        if linea.startswith(f"{tipo}="):
            lineas[i] = f"{tipo}={numero}\n"
            encontrado = True
            break
    
    if not encontrado:
        lineas.append(f"{tipo}={numero}\n")
    
    with open(CONTADORES_FILE, "w", encoding="utf-8") as f:
        f.writelines(lineas)

def obtener_siguiente_numero(tipo, prefijo, digitos=3):
    """Obtiene el siguiente número para un tipo de documento"""
    actual = leer_contador(tipo)
    siguiente = actual + 1
    escribir_contador(tipo, siguiente)
    numero_formateado = str(siguiente).zfill(digitos)
    return f"{prefijo}-{numero_formateado}"