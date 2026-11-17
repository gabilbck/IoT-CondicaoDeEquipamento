"""Alertas e notificação externa (R15) por WhatsApp (CallMeBot).

Condições (cada uma abre no máximo um alerta ativo por tipo+dispositivo e se resolve sozinha):
- ph_fora_faixa / temp_fora_faixa: fora de [min, max] por mais de `alerta_fora_faixa_min` (10 min)
- dispositivo_offline: sem contato há mais de `offline_alerta_min` (2 min) ou Last Will recebido
- falha_sensor: última leitura com valido=false
- modo_seguro: controlador em SEGURO
- broker_indisponivel: backend sem conexão com o broker há mais de 30 s
O mesmo alerta só é notificado de novo depois de `alerta_intervalo_min`.
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .comandos import config_backend
from .models import Alerta, Dispositivo, Medicao, agora

log = logging.getLogger("alertas")


def enviar_whatsapp(texto: str) -> bool:
    if not (config.CALLMEBOT_PHONE and config.CALLMEBOT_APIKEY):
        log.info("[WhatsApp desativado] %s", texto)
        return False
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={quote(config.CALLMEBOT_PHONE)}&text={quote(texto)}&apikey={quote(config.CALLMEBOT_APIKEY)}"
    )
    try:
        r = httpx.get(url, timeout=15)
        ok = r.status_code == 200
        log.info("WhatsApp %s: %s", "enviado" if ok else f"falhou ({r.status_code})", texto)
        return ok
    except httpx.HTTPError as e:
        log.warning("WhatsApp falhou: %s", e)
        return False


# Trocável nos testes (e para trocar de provedor, ex.: Twilio)
notificador: Callable[[str], bool] = lambda texto: threading.Thread(
    target=enviar_whatsapp, args=(texto,), daemon=True
).start() or True


def abrir(s: Session, tipo: str, device_id: Optional[str], mensagem: str, severidade: str = "aviso") -> Alerta:
    ativo = s.scalars(
        select(Alerta).where(Alerta.tipo == tipo, Alerta.device_id == device_id, Alerta.resolvido_em.is_(None))
    ).first()
    if ativo:
        return ativo
    t = agora()
    cfg = config_backend(s)
    recente = s.scalars(
        select(Alerta).where(
            Alerta.tipo == tipo, Alerta.device_id == device_id, Alerta.notificado.is_(True),
            Alerta.criado_em >= t - timedelta(minutes=cfg["alerta_intervalo_min"]),
        )
    ).first()
    alerta = Alerta(tipo=tipo, device_id=device_id, mensagem=mensagem, severidade=severidade, criado_em=t)
    if not recente:
        alerta.notificado = bool(notificador(f"🐟 Aquário Inteligente — {mensagem}"))
    s.add(alerta)
    s.flush()
    log.warning("ALERTA %s %s: %s", tipo, device_id, mensagem)
    return alerta


def resolver(s: Session, tipo: str, device_id: Optional[str]) -> None:
    for a in s.scalars(
        select(Alerta).where(Alerta.tipo == tipo, Alerta.device_id == device_id, Alerta.resolvido_em.is_(None))
    ):
        a.resolvido_em = agora()


def _condicao(s: Session, tipo: str, device_id: Optional[str], ativo: bool, mensagem: str, sev="aviso"):
    if ativo:
        abrir(s, tipo, device_id, mensagem, sev)
    else:
        resolver(s, tipo, device_id)


def fora_da_faixa_desde(s: Session, grandeza: str, lo: float, hi: float, t: datetime) -> Optional[datetime]:
    """Desde quando a grandeza está continuamente fora de [lo, hi] (None se está dentro)."""
    base = select(Medicao).where(
        Medicao.device_id == "sonda-01", Medicao.grandeza == grandeza, Medicao.valido.is_(True),
        Medicao.ts >= t - timedelta(hours=24),
    )
    ultima = s.scalars(base.order_by(Medicao.ts.desc()).limit(1)).first()
    if not ultima or lo <= ultima.valor <= hi:
        return None
    ultima_ok = s.scalars(
        base.where(Medicao.valor >= lo, Medicao.valor <= hi).order_by(Medicao.ts.desc()).limit(1)
    ).first()
    q = base if not ultima_ok else base.where(Medicao.ts > ultima_ok.ts)
    primeira_fora = s.scalars(q.order_by(Medicao.ts.asc()).limit(1)).first()
    return primeira_fora.ts if primeira_fora else None


def avaliar(s: Session, broker_desconectado_desde: Optional[datetime] = None, t: Optional[datetime] = None):
    t = t or agora()
    cfg = config_backend(s)
    janela = timedelta(minutes=cfg["alerta_fora_faixa_min"])

    for grandeza, lo, hi, un in (("ph", cfg["ph_min"], cfg["ph_max"], "pH"),
                                  ("temperatura", cfg["temp_min"], cfg["temp_max"], "°C")):
        desde = fora_da_faixa_desde(s, grandeza, lo, hi, t)
        tipo = "ph_fora_faixa" if grandeza == "ph" else "temp_fora_faixa"
        nome = "pH" if grandeza == "ph" else "Temperatura"
        _condicao(s, tipo, "sonda-01", bool(desde and t - desde >= janela),
                  f"{nome} fora da faixa ({lo}–{hi} {un}) há mais de {cfg['alerta_fora_faixa_min']:.0f} min",
                  "critico")

        ultima = s.scalars(
            select(Medicao).where(Medicao.device_id == "sonda-01", Medicao.grandeza == grandeza,
                                  Medicao.ts >= t - timedelta(minutes=2))
            .order_by(Medicao.ts.desc()).limit(1)
        ).first()
        _condicao(s, f"falha_sensor_{grandeza}", "sonda-01", bool(ultima and not ultima.valido),
                  f"Falha no sensor de {nome.lower()} (leitura inválida)", "critico")

    limite = t - timedelta(minutes=cfg["offline_alerta_min"])
    for device_id in config.DISPOSITIVOS:
        d = s.get(Dispositivo, device_id)
        if d is None or d.ultimo_contato is None:
            continue  # nunca visto: não alerta
        offline = d.ultimo_contato < limite
        _condicao(s, "dispositivo_offline", device_id, offline,
                  f"{device_id} offline há mais de {cfg['offline_alerta_min']:.0f} min", "critico")
        if device_id == "ctrl-01":
            estado = d.ultimo_estado or {}
            seguro = estado.get("modo") == "SEGURO" and not offline
            _condicao(s, "modo_seguro", device_id, seguro,
                      f"Controlador em modo SEGURO (causa: {estado.get('causa_seguro') or '?'})", "critico")

    _condicao(s, "broker_indisponivel", None,
              bool(broker_desconectado_desde and t - broker_desconectado_desde > timedelta(seconds=30)),
              "Backend sem conexão com o broker MQTT", "critico")
