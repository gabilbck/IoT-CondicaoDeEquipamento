"""Regras de decisão remota (R8).

Regra 1 (pH): média móvel de 5 min abaixo de ph_min → dosar pH+; acima de ph_max → dosar pH−.
  Só dosa se não houve dose nos últimos `intervalo_min_doses_s` e se o total de doses na última hora
  está abaixo de `doses_max_hora`. Leituras dos 10 s seguintes a cada dose são descartadas (ruído da bomba).
Regra 2 (temperatura, com histerese):
  temp < temp_min → aquecedor ON; aquecedor ON e temp ≥ temp_min + h → aquecedor OFF
  temp > temp_max → cooler ON;    cooler ON e temp ≤ temp_max − h → cooler OFF

As regras só rodam com o controlador online e em modo AUTO. Os comandos passam pelo mesmo ciclo do R7,
com origem "regra:<nome>".
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .comandos import Publicar, config_backend, criar_comando
from .models import Comando, Dispositivo, Medicao, agora

log = logging.getLogger("regras")

PENDENTES_OU_FEITOS = ("enviado", "recebido", "executado", "confirmado")


@dataclass
class Decisao:
    regra: str
    acao: str
    params: dict


def _doses(s: Session, desde: datetime):
    return s.scalars(
        select(Comando).where(
            Comando.device_id == "ctrl-01",
            Comando.acao == "dosar",
            Comando.status.in_(PENDENTES_OU_FEITOS),
            Comando.enviado_em >= desde,
        )
    ).all()


def media_ph(s: Session, cfg: dict, t: datetime) -> tuple[Optional[float], int]:
    """Média móvel do pH na janela, sem as leituras logo após uma dose."""
    inicio = t - timedelta(seconds=cfg["janela_media_ph_s"])
    leituras = s.execute(
        select(Medicao.valor, Medicao.ts).where(
            Medicao.device_id == "sonda-01",
            Medicao.grandeza == "ph",
            Medicao.valido.is_(True),
            Medicao.ts >= inicio,
            Medicao.ts <= t,
        )
    ).all()
    descarte = timedelta(seconds=cfg["descartar_ph_apos_dose_s"])
    doses = [d.enviado_em for d in _doses(s, inicio - descarte)]
    valores = [v for v, ts in leituras if v is not None and not any(d <= ts <= d + descarte for d in doses)]
    if not valores:
        return None, 0
    return sum(valores) / len(valores), len(valores)


def decidir_ph(s: Session, cfg: dict, t: datetime) -> Optional[Decisao]:
    media, n = media_ph(s, cfg, t)
    if media is None or n < cfg["leituras_minimas_media"]:
        return None
    if media < cfg["ph_min"]:
        regra, alvo = "ph_baixo", "bomba_ph_mais"
    elif media > cfg["ph_max"]:
        regra, alvo = "ph_alto", "bomba_ph_menos"
    else:
        return None
    if _doses(s, t - timedelta(seconds=cfg["intervalo_min_doses_s"])):
        return None
    if len(_doses(s, t - timedelta(hours=1))) >= cfg["doses_max_hora"]:
        return None
    return Decisao(regra, "dosar", {"alvo": alvo, "duracao_ms": int(cfg["dose_ms"])})


def ultima_temperatura(s: Session, t: datetime, max_idade_s: int = 60) -> Optional[float]:
    m = s.scalars(
        select(Medicao)
        .where(Medicao.device_id == "sonda-01", Medicao.grandeza == "temperatura",
               Medicao.valido.is_(True), Medicao.ts >= t - timedelta(seconds=max_idade_s))
        .order_by(Medicao.ts.desc())
        .limit(1)
    ).first()
    return m.valor if m else None


def decidir_temperatura(cfg: dict, temp: Optional[float], atuadores: dict) -> list[Decisao]:
    if temp is None:
        return []
    h = cfg["histerese_temp"]
    aquecedor = atuadores.get("aquecedor") == "ON"
    cooler = atuadores.get("cooler") == "ON"
    out = []
    if temp < cfg["temp_min"]:
        if cooler:
            out.append(Decisao("temp_baixa", "cooler", {"estado": "OFF"}))
        if not aquecedor:
            out.append(Decisao("temp_baixa", "aquecedor", {"estado": "ON"}))
    elif temp > cfg["temp_max"]:
        if not cooler:
            out.append(Decisao("temp_alta", "cooler", {"estado": "ON"}))  # o firmware bloqueia o aquecedor antes
    else:
        if aquecedor and temp >= cfg["temp_min"] + h:
            out.append(Decisao("temp_ok", "aquecedor", {"estado": "OFF"}))
        if cooler and temp <= cfg["temp_max"] - h:
            out.append(Decisao("temp_ok", "cooler", {"estado": "OFF"}))
    return out


def _comando_pendente(s: Session, acao: str) -> bool:
    n = s.scalar(
        select(func.count()).select_from(Comando).where(
            Comando.device_id == "ctrl-01", Comando.acao == acao,
            Comando.status.in_(("enviado", "recebido", "executado")),
        )
    )
    return bool(n)


def executar_regras(s: Session, publicar: Publicar, t: Optional[datetime] = None) -> list[Comando]:
    t = t or agora()
    ctrl = s.get(Dispositivo, "ctrl-01")
    if not ctrl or not ctrl.online or not ctrl.ultimo_estado:
        return []
    estado = ctrl.ultimo_estado
    if estado.get("modo") != "AUTO":
        return []
    cfg = config_backend(s)
    decisoes: list[Decisao] = []
    d = decidir_ph(s, cfg, t)
    if d:
        decisoes.append(d)
    decisoes += decidir_temperatura(cfg, ultima_temperatura(s, t), estado.get("atuadores") or {})

    criados = []
    for d in decisoes:
        if _comando_pendente(s, d.acao):
            continue  # espera o ciclo anterior terminar
        cmd = criar_comando(s, publicar, "ctrl-01", d.acao, d.params, origem=f"regra:{d.regra}")
        criados.append(cmd)
    return criados
