"""Tabelas do banco (R5). O esquema versionado está em alembic/versions/."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

JsonCol = JSON().with_variant(JSONB(), "postgresql")


def agora() -> datetime:
    """Hora UTC sem tzinfo (o banco guarda tudo em UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Dispositivo(Base):
    __tablename__ = "dispositivos"
    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(16))
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    ultimo_contato: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_estado: Mapped[dict | None] = mapped_column(JsonCol, nullable=True)
    fw: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DispositivoStatus(Base):
    """Histórico online/offline (uptime do painel R14)."""
    __tablename__ = "dispositivo_status"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    online: Mapped[bool] = mapped_column(Boolean)
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Medicao(Base):
    __tablename__ = "medicoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(32))
    grandeza: Mapped[str] = mapped_column(String(16))
    valor: Mapped[float | None] = mapped_column(Float, nullable=True)
    unidade: Mapped[str] = mapped_column(String(8))
    valido: Mapped[bool] = mapped_column(Boolean, default=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (Index("ix_medicoes_dev_grand_ts", "device_id", "grandeza", "ts"),)


class Comando(Base):
    __tablename__ = "comandos"
    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    origem: Mapped[str] = mapped_column(String(48))
    usuario: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acao: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict] = mapped_column(JsonCol, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="enviado")
    codigo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expira_em_s: Mapped[int] = mapped_column(Integer, default=10)
    enviado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ComandoEvento(Base):
    __tablename__ = "comando_eventos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command_id: Mapped[str] = mapped_column(String(36), index=True)
    fase: Mapped[str] = mapped_column(String(16))
    resultado: Mapped[str | None] = mapped_column(String(16), nullable=True)
    codigo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Alerta(Base):
    __tablename__ = "alertas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(32))
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severidade: Mapped[str] = mapped_column(String(16), default="aviso")
    mensagem: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notificado: Mapped[bool] = mapped_column(Boolean, default=False)


class Configuracao(Base):
    __tablename__ = "configuracoes"
    chave: Mapped[str] = mapped_column(String(48), primary_key=True)
    valor: Mapped[float] = mapped_column(Float)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    atualizado_por: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MensagemInvalida(Base):
    __tablename__ = "mensagens_invalidas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topico: Mapped[str] = mapped_column(String(128))
    payload: Mapped[str] = mapped_column(Text)
    erro: Mapped[str] = mapped_column(Text)
    recebido_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
