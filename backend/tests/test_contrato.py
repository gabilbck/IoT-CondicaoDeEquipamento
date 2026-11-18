import json

import pytest

from app.contrato import ErroContrato, validar_mensagem, validar_params
from app.ingestao import processar
from app.models import Medicao, MensagemInvalida

from .util import ack, estado_ctrl, status, telemetria

T = "aquario/v1/sonda-01/telemetria"


def test_telemetria_valida():
    device, tipo, msg = validar_mensagem(T, telemetria(ph=7.12, temp=25.4))
    assert (device, tipo) == ("sonda-01", "telemetria")
    assert msg.leituras[0].valor == 7.12


def test_exemplo_do_contrato_com_campo_extra_e_aceito():
    p = json.loads(telemetria())
    p["campo_novo_opcional"] = 123
    validar_mensagem(T, json.dumps(p).encode())


@pytest.mark.parametrize("mexe", [
    lambda p: p.update(v=2),
    lambda p: p.pop("deviceId"),
    lambda p: p.update(deviceId="ctrl-01"),
    lambda p: p["leituras"][0].update(unidade="°C"),
    lambda p: p["leituras"][0].update(grandeza="salinidade"),
    lambda p: p.update(estado_local="QUALQUER"),
    lambda p: p.update(ts=None),  # ts null exige ts_sync=false
    lambda p: p.update(seq=-1),
])
def test_telemetria_invalida(mexe):
    p = json.loads(telemetria())
    mexe(p)
    with pytest.raises(ErroContrato):
        validar_mensagem(T, json.dumps(p).encode())


def test_ts_null_com_ts_sync_false_e_valido():
    p = json.loads(telemetria())
    p.update(ts=None, ts_sync=False)
    validar_mensagem(T, json.dumps(p).encode())


@pytest.mark.parametrize("topico", ["sistema/aquario/ph", "aquario/v1/sonda-99/telemetria", "aquario/v1/sonda-01/xyz",
                                    "aquario/v2/sonda-01/telemetria"])
def test_topico_fora_do_contrato(topico):
    with pytest.raises(ErroContrato):
        validar_mensagem(topico, telemetria())


def test_json_invalido():
    with pytest.raises(ErroContrato):
        validar_mensagem(T, b"{nao eh json")


def test_estado_status_ack_validos():
    validar_mensagem("aquario/v1/ctrl-01/estado", estado_ctrl())
    validar_mensagem("aquario/v1/ctrl-01/status", status(False))
    validar_mensagem("aquario/v1/ctrl-01/ack", ack("6f1c2a7e-4b1d-4a8f-9a63-0c2f5d9e8b11"))


def test_ack_rejeitado_exige_codigo_do_catalogo():
    cid = "6f1c2a7e-4b1d-4a8f-9a63-0c2f5d9e8b11"
    with pytest.raises(ErroContrato):
        validar_mensagem("aquario/v1/ctrl-01/ack", ack(cid, resultado="rejeitado"))
    with pytest.raises(ErroContrato):
        validar_mensagem("aquario/v1/ctrl-01/ack", ack(cid, resultado="rejeitado", codigo="E_INVENTADO"))
    validar_mensagem("aquario/v1/ctrl-01/ack", ack(cid, resultado="rejeitado", codigo="E_INTERTRAVAMENTO"))


def test_invalida_e_registrada_e_descartada(s):
    assert processar(s, T, b'{"v":1}') is False
    s.commit()
    assert s.query(MensagemInvalida).count() == 1
    assert s.query(Medicao).count() == 0


def test_valida_grava_medicoes(s):
    assert processar(s, T, telemetria(ph=6.9, temp=24.0)) is True
    s.commit()
    assert {m.grandeza: m.valor for m in s.query(Medicao)} == {"ph": 6.9, "temperatura": 24.0}


@pytest.mark.parametrize("device,acao,params", [
    ("ctrl-01", "dosar", {"alvo": "bomba_ph_mais", "duracao_ms": 50}),
    ("ctrl-01", "dosar", {"alvo": "bomba_ph_mais", "duracao_ms": 6000}),
    ("ctrl-01", "dosar", {"alvo": "aquecedor", "duracao_ms": 1000}),
    ("ctrl-01", "modo", {"modo": "TURBO"}),
    ("ctrl-01", "silenciar", {"duracao_s": 100}),
    ("sonda-01", "silenciar", {"duracao_s": 10}),
    ("sonda-01", "config", {"ph_crit_min": 9, "ph_crit_max": 8}),
    ("sonda-01", "config", {"chave_inexistente": 1}),
    ("ctrl-01", "ota", {"url": "ftp://x", "versao": "1", "sha256": "0" * 64}),
    ("ctrl-01", "voar", {}),
])
def test_params_de_comando_invalidos(device, acao, params):
    with pytest.raises(ErroContrato):
        validar_params(device, acao, params)


def test_params_de_comando_validos():
    assert validar_params("ctrl-01", "dosar", {"alvo": "bomba_ph_menos", "duracao_ms": 1000})["duracao_ms"] == 1000
    assert validar_params("sonda-01", "config", {"ph_crit_min": 6.2}) == {"ph_crit_min": 6.2}
