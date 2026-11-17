"""Painel analítico (R14), calculado do histórico real no banco.

- série de pH e temperatura (24 h em baldes de 5 min, 7 dias em baldes de 1 h)
- média móvel de 30 min
- % do tempo fora da faixa
- nº de doses por dia
- uptime de cada dispositivo
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, case, cast, func, select
from sqlalchemy.orm import Session

from . import config
from .comandos import config_backend
from .models import Comando, Dispositivo, DispositivoStatus, Medicao, agora

PERIODOS = {"24h": (timedelta(hours=24), 300), "7d": (timedelta(days=7), 3600)}


def _balde(s: Session, segundos: int):
    if s.get_bind().dialect.name == "postgresql":
        return cast(func.floor(func.extract("epoch", Medicao.ts) / segundos), Integer)
    return cast(func.strftime("%s", Medicao.ts), Integer) / segundos


def serie(s: Session, grandeza: str, periodo: str, t: datetime | None = None) -> dict:
    t = t or agora()
    duracao, seg = PERIODOS[periodo]
    cfg = config_backend(s)
    lo, hi = (cfg["ph_min"], cfg["ph_max"]) if grandeza == "ph" else (cfg["temp_min"], cfg["temp_max"])
    b = _balde(s, seg).label("b")
    fora = func.sum(case((and_(Medicao.valor >= lo, Medicao.valor <= hi), 0), else_=1))
    linhas = s.execute(
        select(b, func.avg(Medicao.valor), func.count(), fora)
        .where(Medicao.device_id == "sonda-01", Medicao.grandeza == grandeza, Medicao.valido.is_(True),
               Medicao.ts >= t - duracao, Medicao.ts <= t)
        .group_by(b).order_by(b)
    ).all()

    pontos, total, total_fora = [], 0, 0
    janela = max(1, 1800 // seg)  # baldes que cabem em 30 min
    hist: list[tuple[float, int]] = []
    for balde, media, n, nf in linhas:
        total += n
        total_fora += nf or 0
        hist.append((float(media), n))
        ult = hist[-janela:]
        mm = sum(m * c for m, c in ult) / sum(c for _, c in ult)
        pontos.append({
            "ts": datetime.fromtimestamp(int(balde) * seg, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "media": round(float(media), 3),
            "media_movel_30min": round(mm, 3),
        })
    return {
        "grandeza": grandeza,
        "unidade": "pH" if grandeza == "ph" else "°C",
        "faixa": [lo, hi],
        "pontos": pontos,
        "pct_fora_faixa": round(100 * total_fora / total, 1) if total else None,
        "leituras": total,
    }


def doses_por_dia(s: Session, dias: int = 7, t: datetime | None = None) -> list[dict]:
    t = t or agora()
    inicio = (t - timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cmds = s.scalars(
        select(Comando).where(Comando.device_id == "ctrl-01", Comando.acao == "dosar",
                              Comando.status.in_(("executado", "confirmado")), Comando.enviado_em >= inicio)
    ).all()
    out = []
    for i in range(dias):
        dia = (inicio + timedelta(days=i)).date()
        do_dia = [c for c in cmds if c.enviado_em.date() == dia]
        out.append({
            "dia": dia.isoformat(),
            "ph_mais": sum(1 for c in do_dia if c.params.get("alvo") == "bomba_ph_mais"),
            "ph_menos": sum(1 for c in do_dia if c.params.get("alvo") == "bomba_ph_menos"),
        })
    return out


def uptime(s: Session, periodo: str, t: datetime | None = None) -> dict:
    """% do período em que cada dispositivo esteve online, a partir de dispositivo_status."""
    t = t or agora()
    inicio = t - PERIODOS[periodo][0]
    out = {}
    for device_id in config.DISPOSITIVOS:
        anterior = s.scalars(
            select(DispositivoStatus).where(DispositivoStatus.device_id == device_id, DispositivoStatus.ts < inicio)
            .order_by(DispositivoStatus.ts.desc()).limit(1)
        ).first()
        eventos = s.scalars(
            select(DispositivoStatus).where(DispositivoStatus.device_id == device_id,
                                            DispositivoStatus.ts >= inicio, DispositivoStatus.ts <= t)
            .order_by(DispositivoStatus.ts)
        ).all()
        if anterior is None and not eventos:
            out[device_id] = None
            continue
        # antes do primeiro registro o dispositivo não existia: conta a partir dele
        cursor = inicio if anterior else eventos[0].ts
        online = anterior.online if anterior else eventos[0].online
        seg_online = 0.0
        for e in eventos:
            if online:
                seg_online += (e.ts - cursor).total_seconds()
            cursor, online = max(cursor, e.ts), e.online
        d = s.get(Dispositivo, device_id)
        if online and d and d.ultimo_contato and t - d.ultimo_contato < timedelta(minutes=2):
            seg_online += (t - cursor).total_seconds()
        base = (t - (inicio if anterior else eventos[0].ts)).total_seconds()
        out[device_id] = round(100 * seg_online / base, 1) if base > 0 else None
    return out


def painel(s: Session, periodo: str = "24h") -> dict:
    if periodo not in PERIODOS:
        raise ValueError("período deve ser 24h ou 7d")
    return {
        "periodo": periodo,
        "ph": serie(s, "ph", periodo),
        "temperatura": serie(s, "temperatura", periodo),
        "doses_por_dia": doses_por_dia(s),
        "uptime_pct": uptime(s, periodo),
    }
