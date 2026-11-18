import json

import pytest

from app import comandos
from app.contrato import ErroContrato
from app.ingestao import processar
from app.models import Comando, ComandoEvento

from .util import ack, estado_ctrl


def _cmd(s, pub, acao="dosar", params=None):
    params = params or {"alvo": "bomba_ph_mais", "duracao_ms": 1000}
    return comandos.criar_comando(s, pub, "ctrl-01", acao, params, origem="usuario", usuario="admin")


def test_publica_no_topico_cmd_com_contrato(s, pub):
    c = _cmd(s, pub)
    topico, payload = pub.msgs[0]
    assert topico == "aquario/v1/ctrl-01/cmd"
    p = json.loads(payload)
    assert p["v"] == 1 and p["commandId"] == c.command_id and p["acao"] == "dosar"
    assert p["origem"] == "usuario" and p["expira_em_s"] == 10
    assert s.get(Comando, c.command_id).status == "enviado"


def test_ciclo_completo_ate_confirmado(s, pub):
    c = _cmd(s, pub)
    cid = c.command_id
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "recebido"))
    assert s.get(Comando, cid).status == "recebido"
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "executado"))
    assert s.get(Comando, cid).status == "executado"
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(ultimo=cid))
    s.commit()
    c = s.get(Comando, cid)
    assert c.status == "confirmado" and c.confirmado_em is not None
    fases = [e.fase for e in s.query(ComandoEvento).filter_by(command_id=cid).order_by(ComandoEvento.id)]
    assert fases == ["enviado", "ack_recebido", "ack_executado", "confirmado"]


def test_estado_antes_do_ack_executado_tambem_confirma(s, pub):
    cid = _cmd(s, pub, "cooler", {"estado": "ON"}).command_id
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "recebido"))
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(ultimo=cid, cooler="ON"))
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "executado"))
    assert s.get(Comando, cid).status == "confirmado"


def test_estado_que_nao_bate_nao_confirma(s, pub):
    cid = _cmd(s, pub, "cooler", {"estado": "ON"}).command_id
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "executado"))
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(ultimo=cid, cooler="OFF"))
    assert s.get(Comando, cid).status == "executado"


def test_rejeitado_com_codigo(s, pub):
    cid = _cmd(s, pub).command_id
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "recebido", "rejeitado", "E_INTERTRAVAMENTO"))
    c = s.get(Comando, cid)
    assert (c.status, c.codigo) == ("rejeitado", "E_INTERTRAVAMENTO")


def test_duplicado_nao_muda_comando_ja_confirmado(s, pub):
    cid = _cmd(s, pub).command_id
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "executado"))
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(ultimo=cid))
    processar(s, "aquario/v1/ctrl-01/ack", ack(cid, "recebido", "rejeitado", "E_DUPLICADO"))
    s.commit()
    assert s.get(Comando, cid).status == "confirmado"
    assert s.query(ComandoEvento).filter_by(command_id=cid, codigo="E_DUPLICADO").count() == 1


def test_expira_sem_resposta(s, pub):
    from datetime import timedelta
    c = _cmd(s, pub)
    c.enviado_em -= timedelta(seconds=30)
    s.commit()
    assert comandos.expirar(s) == 1
    assert s.get(Comando, c.command_id).status == "expirado"


def test_nao_expira_dentro_do_prazo(s, pub):
    _cmd(s, pub)
    assert comandos.expirar(s) == 0


def test_ack_de_outro_dispositivo_e_ignorado(s, pub):
    cid = _cmd(s, pub).command_id
    processar(s, "aquario/v1/sonda-01/ack", ack(cid, "recebido", device="sonda-01"))
    assert s.get(Comando, cid).status == "enviado"


def test_comando_invalido_nao_e_publicado(s, pub):
    with pytest.raises(ErroContrato):
        _cmd(s, pub, "dosar", {"alvo": "bomba_ph_mais", "duracao_ms": 99999})
    assert pub.msgs == []
