"""Configuração do backend lida das variáveis de ambiente (arquivo .env no compose)."""
import os


def _bool(nome: str, padrao: str = "0") -> bool:
    return os.getenv(nome, padrao).strip().lower() in ("1", "true", "sim", "yes")


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./aquario.db")

# MQTT
MQTT_HABILITADO = _bool("MQTT_HABILITADO", "1")
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TLS = _bool("MQTT_TLS", "1")
MQTT_CA = os.getenv("MQTT_CA", "/certs/ca.crt")
MQTT_USUARIO = os.getenv("MQTT_BACKEND_USER", "backend")
MQTT_SENHA = os.getenv("MQTT_BACKEND_PASSWORD", "")
PREFIXO = "aquario/v1"

# Notificação externa (R15) — CallMeBot (WhatsApp)
CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE", "")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")

# OTA (R17): onde os .bin ficam e a URL pública que o ESP32 usa para baixar
FIRMWARE_DIR = os.getenv("FIRMWARE_DIR", "/data/firmware")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Laço de regras/expiração/alertas
INTERVALO_TAREFAS_S = float(os.getenv("INTERVALO_TAREFAS_S", "5"))

DISPOSITIVOS = {"sonda-01": "sonda", "ctrl-01": "controlador"}

# Configuração padrão das regras do backend (editável pela interface, tabela `configuracoes`)
CONFIG_PADRAO = {
    "ph_min": 6.5,
    "ph_max": 7.5,
    "temp_min": 24.0,
    "temp_max": 28.0,
    "histerese_temp": 0.5,
    "janela_media_ph_s": 300,       # média móvel de 5 min (R8)
    "leituras_minimas_media": 10,
    "dose_ms": 1000,
    "intervalo_min_doses_s": 900,   # 15 min
    "doses_max_hora": 3,
    "descartar_ph_apos_dose_s": 10,
    "alerta_fora_faixa_min": 10,    # R15
    "offline_alerta_min": 2,
    "alerta_intervalo_min": 30,     # intervalo mínimo entre alertas iguais
    "comando_expira_s": 10,
}

# Faixas válidas de cada chave (validação do PUT /api/config)
CONFIG_FAIXAS = {
    "ph_min": (0, 14), "ph_max": (0, 14),
    "temp_min": (0, 45), "temp_max": (0, 45),
    "histerese_temp": (0.1, 5),
    "janela_media_ph_s": (60, 3600),
    "leituras_minimas_media": (1, 1000),
    "dose_ms": (100, 5000),
    "intervalo_min_doses_s": (60, 86400),
    "doses_max_hora": (1, 20),
    "descartar_ph_apos_dose_s": (0, 600),
    "alerta_fora_faixa_min": (1, 1440),
    "offline_alerta_min": (1, 1440),
    "alerta_intervalo_min": (1, 1440),
    "comando_expira_s": (1, 600),
}
