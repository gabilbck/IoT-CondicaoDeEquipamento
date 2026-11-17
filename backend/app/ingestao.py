"""Processa cada mensagem recebida do broker: valida contra o contrato e grava no banco."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from . import comandos
from .contrato import Ack, ErroContrato, EstadoControlador, EstadoSonda, Status, Telemetria, validar_mensagem
from .models import Dispositivo, DispositivoStatus, MensagemInvalida, Medicao, agora

log = logging.getLogger("ingestao")


def _hora(ts: Optional[datetime], ts_sync: bool) -> datetime:
    """Hora da mensagem em UTC sem tz; usa a hora de chegada se o dispositivo não tem hora válida."""
    chegada = agora()
    if not ts or not ts_sync:
        return chegada
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    # relógio muito diferente do servidor: confia na chegada
    if abs((ts - chegada).total_seconds()) > 300:
        return chegada
    return ts


def _dispositivo(s: Session, device_id: str) -> Dispositivo:
    d = s.get(Dispositivo, device_id)
    if d is None:
        from .config import DISPOSITIVOS
        d = Dispositivo(device_id=device_id, tipo=DISPOSITIVOS.get(device_id, "?"), online=False)
        s.add(d)
        s.flush()
    return d


def _marcar_online(s: Session, d: Dispositivo, online: bool, quando: datetime) -> None:
    if d.online != online:
        s.add(DispositivoStatus(device_id=d.device_id, online=online, ts=quando))
    d.online = online


def processar(s: Session, topico: str, payload: bytes) -> bool:
    """Retorna True se a mensagem foi aceita; False se foi registrada como inválida."""
    try:
        device_id, tipo, msg = validar_mensagem(topico, payload)
    except ErroContrato as e:
        s.add(MensagemInvalida(topico=topico[:128], payload=payload.decode("utf-8", "replace")[:4000], erro=str(e)))
        log.warning("mensagem inválida em %s: %s", topico, e)
        return False

    quando = _hora(msg.ts, msg.ts_sync)
    d = _dispositivo(s, device_id)

    if isinstance(msg, Status):
        if msg.status == "online":
            d.ultimo_contato = agora()
            if msg.fw:
                d.fw = msg.fw
        _marcar_online(s, d, msg.status == "online", agora())
        return True

    # qualquer outra mensagem prova que o dispositivo está vivo
    d.ultimo_contato = agora()
    _marcar_online(s, d, True, agora())

    if isinstance(msg, Telemetria):
        for leitura in msg.leituras:
            s.add(Medicao(device_id=device_id, grandeza=leitura.grandeza, valor=leitura.valor,
                          unidade=leitura.unidade, valido=leitura.valido, ts=quando))
        estado = dict(d.ultimo_estado or {})
        estado["estado_local"] = msg.estado_local
        estado["ultima_telemetria"] = msg.model_dump(mode="json")
        d.ultimo_estado = estado
    elif isinstance(msg, (EstadoControlador, EstadoSonda)):
        novo = msg.model_dump(mode="json")
        if isinstance(msg, EstadoSonda) and d.ultimo_estado and "ultima_telemetria" in d.ultimo_estado:
            novo["ultima_telemetria"] = d.ultimo_estado["ultima_telemetria"]
        d.ultimo_estado = novo
        d.fw = msg.fw
        s.flush()
        comandos.aplicar_estado(s, device_id, novo)
    elif isinstance(msg, Ack):
        comandos.aplicar_ack(s, device_id, msg)
    return True


def dispositivo_online(d: Dispositivo, limite_s: int = 120) -> bool:
    return bool(d.online and d.ultimo_contato and agora() - d.ultimo_contato < timedelta(seconds=limite_s))
