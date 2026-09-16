from datetime import datetime
from collections import deque
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Monitor de pH - Servidor")

# Guarda as últimas N leituras em memória (não precisa de banco de dados para esse projeto)
HISTORICO_MAXIMO = 50
historico = deque(maxlen=HISTORICO_MAXIMO)


class LeituraPH(BaseModel):
    ph: float
    voltage: Optional[float] = None
    device: Optional[str] = "esp32"


@app.post("/api/ph")
def receber_leitura(leitura: LeituraPH):
    """Endpoint que o ESP32 chama periodicamente (HTTP POST)."""
    registro = {
        "ph": round(leitura.ph, 2),
        "voltage": leitura.voltage,
        "device": leitura.device,
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
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
            {"ph": None, "voltage": None, "timestamp": None, "device": None}
        )
    return historico[-1]


@app.get("/api/ph/historico")
def obter_historico():
    return list(historico)


# Serve arquivos estáticos (CSS/JS embutidos no index.html, então basta isso)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def pagina_inicial():
    return FileResponse("static/index.html")
