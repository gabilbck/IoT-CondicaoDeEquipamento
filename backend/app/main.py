"""Backend do Aquário Inteligente (R4): API REST + interface + ponte MQTT + laço de regras/alertas."""
import asyncio
import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import alertas, analitico, comandos, config, db, regras
from .contrato import ErroContrato
from .ingestao import dispositivo_online
from .models import (Alerta, Comando, ComandoEvento, Configuracao, Dispositivo, Medicao, MensagemInvalida, agora)
from .mqtt_bridge import Ponte, PonteDesligada

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("backend")

ESTATICO = Path(__file__).parent / "static"
ponte = Ponte() if config.MQTT_HABILITADO else PonteDesligada()


def tarefas_periodicas() -> None:
    """Uma rodada: expira comandos, roda as regras R8 e avalia os alertas R15."""
    with db.sessao() as s:
        comandos.expirar(s)
    with db.sessao() as s:
        if ponte.conectado:
            regras.executar_regras(s, ponte.publicar)
    with db.sessao() as s:
        alertas.avaliar(s, ponte.desconectado_desde)


async def _laco():
    while True:
        try:
            await asyncio.to_thread(tarefas_periodicas)
        except Exception:
            log.exception("erro no laço de tarefas")
        await asyncio.sleep(config.INTERVALO_TAREFAS_S)


def preparar_banco() -> None:
    if db.engine.dialect.name == "sqlite":
        # desenvolvimento/testes; no Postgres o esquema vem das migrações (alembic upgrade head)
        db.Base.metadata.create_all(db.engine)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    preparar_banco()
    Path(config.FIRMWARE_DIR).mkdir(parents=True, exist_ok=True)
    ponte.iniciar()
    tarefa = asyncio.create_task(_laco()) if os.getenv("LACO_TAREFAS", "1") == "1" else None
    yield
    if tarefa:
        tarefa.cancel()
    ponte.parar()


app = FastAPI(title="Aquário Inteligente — backend", version="1.0.0", lifespan=ciclo_de_vida)


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _cmd(c: Comando, eventos: Optional[list] = None) -> dict:
    d = {
        "command_id": c.command_id, "device_id": c.device_id, "origem": c.origem, "usuario": c.usuario,
        "acao": c.acao, "params": c.params, "status": c.status, "codigo": c.codigo,
        "expira_em_s": c.expira_em_s, "enviado_em": _iso(c.enviado_em), "recebido_em": _iso(c.recebido_em),
        "executado_em": _iso(c.executado_em), "confirmado_em": _iso(c.confirmado_em),
    }
    if eventos is not None:
        d["eventos"] = [{"fase": e.fase, "resultado": e.resultado, "codigo": e.codigo, "detalhe": e.detalhe,
                         "ts": _iso(e.ts)} for e in eventos]
    return d


def _alerta(a: Alerta) -> dict:
    return {"id": a.id, "tipo": a.tipo, "device_id": a.device_id, "severidade": a.severidade,
            "mensagem": a.mensagem, "criado_em": _iso(a.criado_em), "resolvido_em": _iso(a.resolvido_em),
            "notificado": a.notificado}


# ---------------------------------------------------------------------------
# Estado atual e histórico
# ---------------------------------------------------------------------------
@app.get("/api/saude")
def saude():
    return {"ok": True, "broker_conectado": ponte.conectado}


@app.get("/api/estado")
def estado_atual(s: Session = Depends(db.get_db)):
    """Cards da interface: valor atual com unidade, último contato e online/offline de cada dispositivo."""
    out = {"broker_conectado": ponte.conectado, "agora": _iso(agora()), "dispositivos": {}}
    for device_id, tipo in config.DISPOSITIVOS.items():
        d = s.get(Dispositivo, device_id)
        info: dict[str, Any] = {"device_id": device_id, "tipo": tipo, "online": False, "ultimo_contato": None,
                                "fw": None, "estado": None}
        if d:
            info.update(online=dispositivo_online(d), ultimo_contato=_iso(d.ultimo_contato), fw=d.fw,
                        estado=d.ultimo_estado)
        out["dispositivos"][device_id] = info
    leituras = {}
    for grandeza in ("ph", "temperatura"):
        m = s.scalars(select(Medicao).where(Medicao.device_id == "sonda-01", Medicao.grandeza == grandeza)
                      .order_by(Medicao.ts.desc()).limit(1)).first()
        leituras[grandeza] = ({"valor": m.valor, "unidade": m.unidade, "valido": m.valido, "ts": _iso(m.ts)}
                              if m else None)
    out["leituras"] = leituras
    out["config"] = comandos.config_backend(s)
    return out


@app.get("/api/historico")
def historico(grandeza: str = Query("ph", pattern="^(ph|temperatura)$"), horas: int = Query(1, ge=1, le=168),
              s: Session = Depends(db.get_db)):
    rows = s.scalars(select(Medicao).where(Medicao.device_id == "sonda-01", Medicao.grandeza == grandeza,
                                           Medicao.ts >= agora() - timedelta(hours=horas))
                     .order_by(Medicao.ts.desc()).limit(5000)).all()
    return [{"ts": _iso(m.ts), "valor": m.valor, "valido": m.valido} for m in reversed(rows)]


@app.get("/api/analitico")
def painel_analitico(periodo: str = Query("24h", pattern="^(24h|7d)$"), s: Session = Depends(db.get_db)):
    return analitico.painel(s, periodo)


@app.get("/api/alertas")
def listar_alertas(ativos: bool = False, limite: int = Query(50, ge=1, le=500), s: Session = Depends(db.get_db)):
    q = select(Alerta).order_by(Alerta.criado_em.desc()).limit(limite)
    if ativos:
        q = q.where(Alerta.resolvido_em.is_(None))
    return [_alerta(a) for a in s.scalars(q)]


@app.get("/api/mensagens-invalidas")
def mensagens_invalidas(limite: int = Query(50, ge=1, le=500), s: Session = Depends(db.get_db)):
    q = select(MensagemInvalida).order_by(MensagemInvalida.recebido_em.desc()).limit(limite)
    return [{"id": m.id, "topico": m.topico, "payload": m.payload, "erro": m.erro, "recebido_em": _iso(m.recebido_em)}
            for m in s.scalars(q)]


# ---------------------------------------------------------------------------
# Comandos (R7)
# ---------------------------------------------------------------------------
class NovoComando(BaseModel):
    device_id: str
    acao: str
    params: dict = Field(default_factory=dict)


@app.get("/api/comandos")
def listar_comandos(limite: int = Query(30, ge=1, le=500), s: Session = Depends(db.get_db)):
    return [_cmd(c) for c in s.scalars(select(Comando).order_by(Comando.enviado_em.desc()).limit(limite))]


@app.get("/api/comandos/{command_id}")
def obter_comando(command_id: str, s: Session = Depends(db.get_db)):
    c = s.get(Comando, command_id)
    if not c:
        raise HTTPException(404, "comando não encontrado")
    ev = s.scalars(select(ComandoEvento).where(ComandoEvento.command_id == command_id).order_by(ComandoEvento.id)).all()
    return _cmd(c, ev)


@app.post("/api/comandos", status_code=201)
def enviar_comando(dados: NovoComando, s: Session = Depends(db.get_db)):
    try:
        c = comandos.criar_comando(s, ponte.publicar, dados.device_id, dados.acao, dados.params,
                                   origem="usuario", usuario=None)
    except ErroContrato as e:
        raise HTTPException(422, str(e))
    s.commit()
    return _cmd(c)


@app.post("/api/comandos/{command_id}/reenviar")
def reenviar(command_id: str, s: Session = Depends(db.get_db)):
    """Republica o MESMO commandId (teste de falha R10-4: o dispositivo deve responder E_DUPLICADO)."""
    c = s.get(Comando, command_id)
    if not c:
        raise HTTPException(404, "comando não encontrado")
    comandos.publicar_comando(ponte.publicar, c)
    s.add(ComandoEvento(command_id=c.command_id, fase="reenviado", ts=agora()))
    s.commit()
    return _cmd(c)


# ---------------------------------------------------------------------------
# Configuração das regras (faixas)
# ---------------------------------------------------------------------------
@app.get("/api/config")
def obter_config(s: Session = Depends(db.get_db)):
    return {"valores": comandos.config_backend(s), "faixas": config.CONFIG_FAIXAS}


@app.put("/api/config")
def alterar_config(valores: dict[str, float], s: Session = Depends(db.get_db)):
    atual = comandos.config_backend(s)
    for chave, valor in valores.items():
        if chave not in config.CONFIG_FAIXAS:
            raise HTTPException(422, f"chave desconhecida: {chave}")
        lo, hi = config.CONFIG_FAIXAS[chave]
        if not lo <= valor <= hi:
            raise HTTPException(422, f"{chave} fora da faixa {lo}–{hi}")
        atual[chave] = valor
    if atual["ph_min"] >= atual["ph_max"] or atual["temp_min"] >= atual["temp_max"]:
        raise HTTPException(422, "o mínimo deve ser menor que o máximo")
    for chave, valor in valores.items():
        linha = s.get(Configuracao, chave) or Configuracao(chave=chave)
        linha.valor, linha.atualizado_em, linha.atualizado_por = valor, agora(), "interface"
        s.add(linha)
    s.commit()
    return {"valores": comandos.config_backend(s)}


# ---------------------------------------------------------------------------
# OTA (R17)
# ---------------------------------------------------------------------------
@app.post("/api/firmware", status_code=201)
async def enviar_firmware(arquivo: UploadFile = File(...)):
    nome = re.sub(r"[^A-Za-z0-9._-]", "_", arquivo.filename or "firmware.bin")
    if not nome.endswith(".bin"):
        raise HTTPException(422, "envie o .bin gerado pela Arduino IDE (Sketch → Exportar binário)")
    conteudo = await arquivo.read()
    sha = hashlib.sha256(conteudo).hexdigest()
    nome = f"{sha[:12]}-{nome}"
    (Path(config.FIRMWARE_DIR) / nome).write_bytes(conteudo)
    return {"arquivo": nome, "sha256": sha, "tamanho": len(conteudo), "url": f"{config.PUBLIC_BASE_URL}/firmware/{nome}"}


class PedidoOta(BaseModel):
    device_id: str
    arquivo: str
    versao: str


@app.post("/api/ota", status_code=201)
def disparar_ota(dados: PedidoOta, s: Session = Depends(db.get_db)):
    caminho = Path(config.FIRMWARE_DIR) / Path(dados.arquivo).name
    if not caminho.is_file():
        raise HTTPException(404, "arquivo de firmware não encontrado")
    sha = hashlib.sha256(caminho.read_bytes()).hexdigest()
    params = {"url": f"{config.PUBLIC_BASE_URL}/firmware/{caminho.name}", "versao": dados.versao, "sha256": sha}
    try:
        c = comandos.criar_comando(s, ponte.publicar, dados.device_id, "ota", params, origem="usuario",
                                   usuario=None, expira_em_s=30)
    except ErroContrato as e:
        raise HTTPException(422, str(e))
    s.commit()
    return _cmd(c)


@app.get("/firmware/{nome}")
def baixar_firmware(nome: str):
    caminho = Path(config.FIRMWARE_DIR) / Path(nome).name
    if not caminho.is_file():
        raise HTTPException(404, "não encontrado")
    return FileResponse(caminho, media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Interface web (R6)
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=ESTATICO), name="static")


@app.get("/")
def pagina():
    return FileResponse(ESTATICO / "index.html")
