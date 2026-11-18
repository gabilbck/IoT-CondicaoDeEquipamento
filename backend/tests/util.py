import json
from datetime import timedelta

from app.models import agora


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def telemetria(ph=7.0, temp=25.0, ph_ok=True, temp_ok=True, seq=1, ts=None, estado="NORMAL"):
    return json.dumps({
        "v": 1, "deviceId": "sonda-01", "ts": iso(ts or agora()), "ts_sync": True, "seq": seq,
        "leituras": [
            {"grandeza": "ph", "valor": ph, "unidade": "pH", "valido": ph_ok},
            {"grandeza": "temperatura", "valor": temp, "unidade": "°C", "valido": temp_ok},
        ],
        "estado_local": estado,
    }).encode()


def estado_ctrl(modo="AUTO", ultimo=None, bomba_mais="OFF", bomba_menos="OFF", aquecedor="OFF", cooler="OFF",
                causa=None, config=None):
    return json.dumps({
        "v": 1, "deviceId": "ctrl-01", "ts": iso(agora()), "ts_sync": True, "modo": modo, "causa_seguro": causa,
        "atuadores": {"bomba_ph_mais": bomba_mais, "bomba_ph_menos": bomba_menos, "aquecedor": aquecedor,
                      "cooler": cooler},
        "nivel": "OK", "ultimo_command_id": ultimo, "fw": "1.0.0", "config_versao": 1, "rssi_dbm": -60,
        "uptime_s": 100, "config": config or {"dose_max_ms": 5000},
    }).encode()


def ack(command_id, fase="recebido", resultado="ok", codigo=None, device="ctrl-01"):
    return json.dumps({
        "v": 1, "deviceId": device, "ts": iso(agora()), "commandId": command_id,
        "fase": fase, "resultado": resultado, "codigo": codigo,
    }).encode()


def status(online=True, device="ctrl-01"):
    if online:
        return json.dumps({"v": 1, "deviceId": device, "status": "online", "ts": iso(agora()), "ts_sync": True}).encode()
    return json.dumps({"v": 1, "deviceId": device, "status": "offline", "ts": None, "ts_sync": False}).encode()


def atras(segundos):
    return agora() - timedelta(seconds=segundos)
