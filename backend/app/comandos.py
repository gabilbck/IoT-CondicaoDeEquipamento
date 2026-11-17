"""Ciclo de vida do comando (R7): enviado → recebido → executado → confirmado | rejeitado | falhou | expirado."""
import json
import logging
import uuid
from datetime import timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .contrato import Ack, ErroContrato, validar_params
from .models import Comando, ComandoEvento, Configuracao, Dispositivo, agora

log = logging.getLogger("comandos")

FINAIS = ("confirmado", "rejeitado", "falhou", "expirado")
Publicar = Callable[[str, str], bool]


def config_backend(s: Session) -> dict:
    cfg = dict(config.CONFIG_PADRAO)
    for linha in s.scalars(select(Configuracao)):
        if linha.chave in cfg:
            cfg[linha.chave] = linha.valor
    return cfg


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def criar_comando(
    s: Session,
    publicar: Publicar,
    device_id: str,
    acao: str,
    params: Optional[dict],
    origem: str,
    usuario: Optional[str] = None,
    expira_em_s: Optional[int] = None,
) -> Comando:
    """Valida, grava como `enviado` e publica em aquario/v1/<deviceId>/cmd (QoS 1, sem retain).

    O backend é o ÚNICO componente que publica comandos (ACL no broker).
    """
    if device_id not in config.DISPOSITIVOS:
        raise ErroContrato(f"dispositivo desconhecido: {device_id}")
    if not (origem in ("usuario", "sistema") or origem.startswith("regra:")):
        raise ErroContrato(f"origem inválida: {origem}")
    params = validar_params(device_id, acao, params or {})
    if expira_em_s is None:
        expira_em_s = int(config_backend(s)["comando_expira_s"])

    cmd = Comando(
        command_id=str(uuid.uuid4()),
        device_id=device_id,
        origem=origem,
        usuario=usuario,
        acao=acao,
        params=params,
        status="enviado",
        expira_em_s=expira_em_s,
        enviado_em=agora(),
    )
    s.add(cmd)
    s.add(ComandoEvento(command_id=cmd.command_id, fase="enviado", ts=cmd.enviado_em))
    # grava ANTES de publicar: o ack pode chegar (em outra thread) antes deste método retornar
    s.commit()
    publicar_comando(publicar, cmd)
    log.info("comando %s %s %s %s (%s)", cmd.command_id, device_id, acao, params, origem)
    return cmd


def publicar_comando(publicar: Publicar, cmd: Comando) -> bool:
    payload = {
        "v": 1,
        "commandId": cmd.command_id,
        "ts": _iso(agora()),
        "origem": cmd.origem,
        "acao": cmd.acao,
        "params": cmd.params,
        "expira_em_s": cmd.expira_em_s,
    }
    return publicar(f"{config.PREFIXO}/{cmd.device_id}/cmd", json.dumps(payload, ensure_ascii=False))


def aplicar_ack(s: Session, device_id: str, ack: Ack) -> Optional[Comando]:
    quando = agora()
    if ack.commandId is None:
        log.warning("ack sem commandId de %s: %s", device_id, ack.codigo)
        return None
    cmd = s.get(Comando, ack.commandId)
    if cmd is None or cmd.device_id != device_id:
        log.warning("ack de comando desconhecido %s (%s)", ack.commandId, device_id)
        return None

    s.add(ComandoEvento(command_id=cmd.command_id, fase=f"ack_{ack.fase}", resultado=ack.resultado,
                        codigo=ack.codigo, detalhe=ack.detalhe, ts=quando))
    if cmd.status in FINAIS:
        # ex.: reenvio do mesmo commandId respondido com E_DUPLICADO — só registra
        return cmd

    if ack.fase == "recebido":
        if ack.resultado == "ok":
            if cmd.status == "enviado":
                cmd.status = "recebido"
            cmd.recebido_em = cmd.recebido_em or quando
        else:
            cmd.status = "rejeitado"
            cmd.codigo = ack.codigo
            cmd.recebido_em = quando
    else:  # executado
        cmd.recebido_em = cmd.recebido_em or quando
        if ack.resultado == "ok":
            cmd.status = "executado"
            cmd.executado_em = quando
            _confirmar_se_bate(s, cmd)
        else:
            cmd.status = "falhou"
            cmd.codigo = ack.codigo or "E_FALHA_EXECUCAO"
            cmd.executado_em = quando
    return cmd


def _bate(cmd: Comando, estado: dict) -> bool:
    """O estado publicado pelo dispositivo confirma o comando?"""
    if not estado or estado.get("ultimo_command_id") != cmd.command_id:
        return False
    atuadores = estado.get("atuadores") or {}
    p = cmd.params or {}
    if cmd.acao == "dosar":
        return atuadores.get(p.get("alvo")) == "OFF"  # dose concluída
    if cmd.acao in ("aquecedor", "cooler"):
        return atuadores.get(cmd.acao) == p.get("estado")
    if cmd.acao == "modo":
        return estado.get("modo") == p.get("modo")
    if cmd.acao == "ota":
        return estado.get("fw") == p.get("versao")
    if cmd.acao == "config":
        cfg = estado.get("config") or {}
        return all(abs(float(cfg.get(k, 1e9)) - float(v)) < 1e-3 for k, v in p.items())
    return True  # silenciar


def _confirmar_se_bate(s: Session, cmd: Comando) -> bool:
    disp = s.get(Dispositivo, cmd.device_id)
    if cmd.status == "executado" and disp and _bate(cmd, disp.ultimo_estado or {}):
        cmd.status = "confirmado"
        cmd.confirmado_em = agora()
        s.add(ComandoEvento(command_id=cmd.command_id, fase="confirmado", ts=cmd.confirmado_em))
        return True
    return False


def aplicar_estado(s: Session, device_id: str, estado: dict) -> Optional[Comando]:
    """Chamado depois de gravar o novo estado do dispositivo."""
    cid = estado.get("ultimo_command_id")
    if not cid:
        return None
    cmd = s.get(Comando, cid)
    if cmd and cmd.device_id == device_id:
        _confirmar_se_bate(s, cmd)
    return cmd


def expirar(s: Session) -> int:
    """Comandos sem conclusão dentro de expira_em_s viram `expirado`.

    Um `executado` ainda aguardando o estado tem uma folga extra (o estado chega logo após o ack).
    """
    n = 0
    t = agora()
    for cmd in s.scalars(select(Comando).where(Comando.status.in_(("enviado", "recebido", "executado")))):
        limite = cmd.enviado_em + timedelta(seconds=cmd.expira_em_s)
        if cmd.acao == "dosar":
            limite += timedelta(milliseconds=int((cmd.params or {}).get("duracao_ms", 0)))
        if cmd.acao == "ota":
            limite += timedelta(seconds=180)  # download + reinício
        if cmd.status == "executado":
            limite += timedelta(seconds=10)
        if t > limite:
            cmd.status = "expirado"
            cmd.codigo = cmd.codigo or "E_EXPIRADO"
            s.add(ComandoEvento(command_id=cmd.command_id, fase="expirado", ts=t))
            n += 1
    return n
