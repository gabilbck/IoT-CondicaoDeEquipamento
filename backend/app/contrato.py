"""Modelos Pydantic do contrato MQTT v1 (ver CONTRATOS.md).

Toda mensagem que chega do broker passa por `validar_mensagem`. O que não bate com o contrato é
registrado em `mensagens_invalidas` e descartado.
"""
import json
import re
from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PREFIXO = "aquario/v1"
DEVICE_IDS = ("sonda-01", "ctrl-01")
TIPOS = ("telemetria", "estado", "cmd", "ack", "status")
TAMANHO_MAXIMO = 1024

CODIGOS_ERRO = (
    "E_PAYLOAD_INVALIDO", "E_VERSAO", "E_ACAO_DESCONHECIDA", "E_DUPLICADO",
    "E_INTERTRAVAMENTO", "E_EXPIRADO", "E_FALHA_EXECUCAO",
)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ErroContrato(ValueError):
    pass


class _Base(BaseModel):
    # campos novos e opcionais podem entrar na v1: ignorados aqui
    model_config = ConfigDict(extra="ignore")

    v: Literal[1]
    deviceId: Literal["sonda-01", "ctrl-01"]
    ts: Optional[datetime] = None
    ts_sync: bool = True

    @model_validator(mode="after")
    def _ts_coerente(self):
        if self.ts is None and self.ts_sync:
            raise ValueError("ts null exige ts_sync=false")
        return self


class Leitura(BaseModel):
    model_config = ConfigDict(extra="ignore")
    grandeza: Literal["ph", "temperatura"]
    valor: Optional[float]
    unidade: Literal["pH", "°C"]
    valido: bool
    tensao_v: Optional[float] = None

    @model_validator(mode="after")
    def _unidade(self):
        esperado = {"ph": "pH", "temperatura": "°C"}[self.grandeza]
        if self.unidade != esperado:
            raise ValueError(f"unidade de {self.grandeza} deve ser {esperado}")
        if self.valido and self.valor is None:
            raise ValueError("leitura válida sem valor")
        return self


class Telemetria(_Base):
    deviceId: Literal["sonda-01"]
    seq: int = Field(ge=0)
    leituras: list[Leitura] = Field(min_length=1, max_length=4)
    estado_local: Literal["NORMAL", "ALERTA_LOCAL", "FALHA_SENSOR"]


class Atuadores(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bomba_ph_mais: Literal["ON", "OFF"]
    bomba_ph_menos: Literal["ON", "OFF"]
    aquecedor: Literal["ON", "OFF"]
    cooler: Literal["ON", "OFF"]


class EstadoControlador(_Base):
    deviceId: Literal["ctrl-01"]
    modo: Literal["BOOT", "AUTO", "MANUAL", "SEGURO"]
    causa_seguro: Optional[Literal["rede", "sensor", "comando", "config"]] = None
    atuadores: Atuadores
    nivel: Literal["OK", "BAIXO"]
    ultimo_command_id: Optional[str] = None
    fw: str
    config_versao: int = Field(ge=0)
    rssi_dbm: Optional[int] = None
    uptime_s: int = Field(ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class EstadoSonda(_Base):
    deviceId: Literal["sonda-01"]
    estado_local: Literal["NORMAL", "ALERTA_LOCAL", "FALHA_SENSOR"]
    silenciado_s: int = Field(default=0, ge=0)
    ultimo_command_id: Optional[str] = None
    fw: str
    config_versao: int = Field(ge=0)
    rssi_dbm: Optional[int] = None
    uptime_s: int = Field(ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class Status(_Base):
    status: Literal["online", "offline"]
    fw: Optional[str] = None


class Ack(_Base):
    commandId: Optional[str]
    fase: Literal["recebido", "executado"]
    resultado: Literal["ok", "rejeitado", "falha"]
    codigo: Optional[str] = None
    detalhe: Optional[str] = None

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v):
        if v is not None and v not in CODIGOS_ERRO:
            raise ValueError(f"código fora do catálogo: {v}")
        return v

    @model_validator(mode="after")
    def _coerencia(self):
        if self.resultado != "ok" and not self.codigo:
            raise ValueError("resultado diferente de ok exige código")
        if self.commandId is None and self.codigo != "E_PAYLOAD_INVALIDO":
            raise ValueError("commandId null só com E_PAYLOAD_INVALIDO")
        return self


# ----------------------------------------------------------------------------
# Comandos (backend → dispositivo): validados antes de publicar
# ----------------------------------------------------------------------------
class ParamsDosar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alvo: Literal["bomba_ph_mais", "bomba_ph_menos"]
    duracao_ms: int = Field(ge=100, le=5000)


class ParamsLiga(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["ON", "OFF"]


class ParamsModo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modo: Literal["AUTO", "MANUAL", "SEGURO"]


class ParamsSilenciar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duracao_s: int = Field(ge=60, le=3600)


class ParamsOta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(pattern=r"^https?://")
    versao: str = Field(min_length=1, max_length=32)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


CONFIG_DISPOSITIVO = {
    "sonda-01": {
        "ph_crit_min": (0, 14), "ph_crit_max": (0, 14),
        "temp_crit_min": (0, 45), "temp_crit_max": (0, 45),
        "ph_slope": (-20, 20), "ph_offset": (-50, 50),
        "intervalo_ph_ms": (1000, 60000), "intervalo_temp_ms": (2000, 60000),
    },
    "ctrl-01": {
        "dose_max_ms": (100, 5000), "manual_timeout_s": (60, 3600),
        "telemetria_timeout_s": (10, 300), "rede_timeout_s": (10, 300),
    },
}

# ação -> (dispositivos que aceitam, modelo dos params)
CATALOGO = {
    "dosar": (("ctrl-01",), ParamsDosar),
    "aquecedor": (("ctrl-01",), ParamsLiga),
    "cooler": (("ctrl-01",), ParamsLiga),
    "modo": (("ctrl-01",), ParamsModo),
    "silenciar": (("sonda-01",), ParamsSilenciar),
    "config": (("sonda-01", "ctrl-01"), None),
    "ota": (("sonda-01", "ctrl-01"), ParamsOta),
}


def validar_params(device_id: str, acao: str, params: dict) -> dict:
    """Valida ação e parâmetros de um comando. Lança ErroContrato com mensagem legível."""
    if acao not in CATALOGO:
        raise ErroContrato(f"ação desconhecida: {acao}")
    dispositivos, modelo = CATALOGO[acao]
    if device_id not in dispositivos:
        raise ErroContrato(f"{device_id} não aceita a ação {acao}")
    if acao == "config":
        faixas = CONFIG_DISPOSITIVO[device_id]
        if not params:
            raise ErroContrato("config sem chaves")
        limpo = {}
        for chave, valor in params.items():
            if chave not in faixas:
                raise ErroContrato(f"chave de config desconhecida: {chave}")
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ErroContrato(f"{chave} deve ser número")
            lo, hi = faixas[chave]
            if not lo <= valor <= hi:
                raise ErroContrato(f"{chave} fora da faixa {lo}–{hi}")
            limpo[chave] = valor
        for a, b in (("ph_crit_min", "ph_crit_max"), ("temp_crit_min", "temp_crit_max")):
            if a in limpo and b in limpo and limpo[a] >= limpo[b]:
                raise ErroContrato(f"{a} deve ser menor que {b}")
        return limpo
    try:
        return modelo(**(params or {})).model_dump()
    except ValidationError as e:
        raise ErroContrato(_resumo(e)) from e


def _resumo(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'payload'}: {err['msg']}" for err in e.errors())


def separar_topico(topico: str) -> tuple[str, str]:
    partes = topico.split("/")
    if len(partes) != 4 or "/".join(partes[:2]) != PREFIXO:
        raise ErroContrato(f"tópico fora do contrato: {topico}")
    device_id, tipo = partes[2], partes[3]
    if device_id not in DEVICE_IDS:
        raise ErroContrato(f"deviceId desconhecido: {device_id}")
    if tipo not in TIPOS:
        raise ErroContrato(f"tipo de tópico desconhecido: {tipo}")
    return device_id, tipo


Mensagem = Union[Telemetria, EstadoControlador, EstadoSonda, Status, Ack]


def validar_mensagem(topico: str, payload: bytes) -> tuple[str, str, Mensagem]:
    """Valida uma mensagem recebida do broker. Retorna (device_id, tipo, modelo)."""
    device_id, tipo = separar_topico(topico)
    if tipo == "cmd":
        raise ErroContrato("o backend não consome o próprio tópico cmd")
    if len(payload) > TAMANHO_MAXIMO:
        raise ErroContrato(f"payload maior que {TAMANHO_MAXIMO} bytes")
    try:
        dados = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ErroContrato(f"JSON inválido: {e}") from e
    if not isinstance(dados, dict):
        raise ErroContrato("payload deve ser um objeto JSON")
    if dados.get("deviceId") != device_id:
        raise ErroContrato("deviceId do payload não bate com o tópico")

    if tipo == "telemetria":
        modelo = Telemetria
    elif tipo == "estado":
        modelo = EstadoControlador if device_id == "ctrl-01" else EstadoSonda
    elif tipo == "status":
        modelo = Status
    else:
        modelo = Ack
    try:
        return device_id, tipo, modelo(**dados)
    except ValidationError as e:
        raise ErroContrato(_resumo(e)) from e


def uuid_valido(valor: str) -> bool:
    return bool(_UUID.match(valor or ""))
