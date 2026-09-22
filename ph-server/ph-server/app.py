import json
import os
import ssl
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import paho.mqtt.client as mqtt
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ===== Configuração MQTT (pode ser alterada no docker-compose.yml) =====
MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# Muitas redes (faculdade, empresa) bloqueiam a porta 1883. A 8883 (MQTT com TLS) costuma passar.
MQTT_TLS = os.getenv("MQTT_TLS", "1") == "1"
TOPICO_PH = os.getenv("TOPICO_PH", "sistema/aquario/ph")              # servidor ASSINA
TOPICO_ATUADOR = os.getenv("TOPICO_ATUADOR", "sistema/aquario/atuador")  # servidor PUBLICA

# Faixa considerada normal (mesma usada no dashboard)
PH_MIN = float(os.getenv("PH_MIN", "6.5"))
PH_MAX = float(os.getenv("PH_MAX", "7.5"))

# Guarda as últimas N leituras em memória (não precisa de banco de dados para esse projeto)
HISTORICO_MAXIMO = 50
historico = deque(maxlen=HISTORICO_MAXIMO)

# Estado da automação decidida pelo servidor a partir das mensagens MQTT
estado = {
    "mqtt_conectado": False,
    "ultimo_ph_mqtt": None,
    "atuador": None,          # "ON" / "OFF" / None (nenhum comando enviado ainda)
    "atualizado_em": None,
}


def agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# ---------------------------------------------------------
# MQTT: assina a leitura do ESP32, decide e publica o comando
# ---------------------------------------------------------
def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[MQTT] Falha ao conectar: {reason_code}")
        return
    estado["mqtt_conectado"] = True
    client.subscribe(TOPICO_PH)
    print(f"[MQTT] Conectado a {MQTT_BROKER}. Assinado: {TOPICO_PH}")


def ao_desconectar(client, userdata, flags, reason_code, properties):
    estado["mqtt_conectado"] = False
    print(f"[MQTT] Desconectado ({reason_code}). Reconectando automaticamente...")


def ao_receber(client, userdata, msg):
    try:
        dados = json.loads(msg.payload.decode("utf-8"))
        ph = float(dados["ph"])
    except (ValueError, KeyError, TypeError) as erro:
        print(f"[MQTT] Mensagem inválida em {msg.topic}: {msg.payload!r} ({erro})")
        return

    estado["ultimo_ph_mqtt"] = round(ph, 2)
    comando = "ON" if (ph < PH_MIN or ph > PH_MAX) else "OFF"

    # Publica só quando o estado muda; retain=True faz o ESP32 receber
    # o último comando assim que (re)conectar ao broker.
    if comando != estado["atuador"]:
        client.publish(TOPICO_ATUADOR, comando, qos=1, retain=True)
        estado["atuador"] = comando
        estado["atualizado_em"] = agora()
        print(f"[{estado['atualizado_em']}] pH={ph:.2f} -> comando {comando} em {TOPICO_ATUADOR}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ph-server-{os.getpid()}")
mqtt_client.on_connect = ao_conectar
mqtt_client.on_disconnect = ao_desconectar
mqtt_client.on_message = ao_receber
if MQTT_TLS:
    # Broker público de teste: criptografa, mas não valida o certificado
    mqtt_client.tls_set(cert_reqs=ssl.CERT_NONE)
    mqtt_client.tls_insecure_set(True)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()  # roda em thread separada, junto com a API
    yield
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(title="Monitor de pH - Servidor", lifespan=ciclo_de_vida)


class LeituraPH(BaseModel):
    ph: float
    voltage: Optional[float] = None
    device: Optional[str] = "esp32"


@app.post("/api/ph")
def receber_leitura(leitura: LeituraPH):
    """Endpoint que o ESP32 chama periodicamente (HTTP POST) - usado só para o dashboard."""
    registro = {
        "ph": round(leitura.ph, 2),
        "voltage": leitura.voltage,
        "device": leitura.device,
        "timestamp": agora(),
    }
    historico.append(registro)

    # Aparece no terminal do container (docker logs)
    print(
        f"[{registro['timestamp']}] dispositivo={registro['device']} "
        f"| pH={registro['ph']} | tensao={registro['voltage']}"
    )

    return {"status": "ok", "recebido": registro}


@app.get("/api/ph/latest")
def leitura_mais_recente():
    """A página web consulta esse endpoint para se atualizar sozinha."""
    if not historico:
        return JSONResponse(
            {"ph": None, "voltage": None, "timestamp": None, "device": None, "atuador": estado["atuador"]}
        )
    return {**historico[-1], "atuador": estado["atuador"]}


@app.get("/api/ph/historico")
def obter_historico():
    return list(historico)


@app.get("/api/status")
def status_mqtt():
    """Estado da parte MQTT: conexão, último pH recebido e último comando enviado."""
    return {
        **estado,
        "broker": MQTT_BROKER,
        "topico_ph": TOPICO_PH,
        "topico_atuador": TOPICO_ATUADOR,
        "faixa_normal": [PH_MIN, PH_MAX],
    }


# Serve arquivos estáticos (CSS/JS embutidos no index.html, então basta isso)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def pagina_inicial():
    return FileResponse("static/index.html")
