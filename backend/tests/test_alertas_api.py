from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import alertas
from app.ingestao import processar
from app.main import app, ponte
from app.models import Alerta, Dispositivo, Medicao, agora

from .conftest import NOTIFICACOES
from .util import estado_ctrl, status


def _ph_fora(s, minutos):
    for i in range(minutos * 6):
        s.add(Medicao(device_id="sonda-01", grandeza="ph", valor=5.5, unidade="pH", valido=True,
                      ts=agora() - timedelta(seconds=i * 10)))
    s.commit()


def test_ph_fora_da_faixa_por_mais_de_10_min_alerta_uma_vez(s):
    _ph_fora(s, 12)
    alertas.avaliar(s)
    alertas.avaliar(s)
    s.commit()
    ativos = s.query(Alerta).filter_by(tipo="ph_fora_faixa", resolvido_em=None).all()
    assert len(ativos) == 1
    assert len([n for n in NOTIFICACOES if "pH" in n]) == 1


def test_ph_fora_ha_pouco_tempo_nao_alerta(s):
    _ph_fora(s, 5)
    alertas.avaliar(s)
    assert s.query(Alerta).filter_by(tipo="ph_fora_faixa").count() == 0


def test_alerta_se_resolve_quando_volta(s):
    _ph_fora(s, 12)
    alertas.avaliar(s)
    s.add(Medicao(device_id="sonda-01", grandeza="ph", valor=7.0, unidade="pH", valido=True,
                  ts=agora() + timedelta(seconds=1)))
    s.commit()
    alertas.avaliar(s, t=agora() + timedelta(seconds=2))
    s.commit()
    assert s.query(Alerta).filter_by(tipo="ph_fora_faixa", resolvido_em=None).count() == 0


def test_intervalo_minimo_entre_alertas_iguais(s):
    alertas.abrir(s, "modo_seguro", "ctrl-01", "x")
    alertas.resolver(s, "modo_seguro", "ctrl-01")
    alertas.abrir(s, "modo_seguro", "ctrl-01", "x")
    s.commit()
    assert s.query(Alerta).filter_by(tipo="modo_seguro").count() == 2
    assert len(NOTIFICACOES) == 1


def test_dispositivo_offline_e_modo_seguro(s):
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(modo="SEGURO", causa="sensor"))
    s.commit()
    alertas.avaliar(s)
    assert s.query(Alerta).filter_by(tipo="modo_seguro").count() == 1
    s.get(Dispositivo, "ctrl-01").ultimo_contato = agora() - timedelta(minutes=5)
    s.commit()
    alertas.avaliar(s)
    assert s.query(Alerta).filter_by(tipo="dispositivo_offline", device_id="ctrl-01").count() == 1


def test_falha_de_sensor(s):
    s.add(Medicao(device_id="sonda-01", grandeza="temperatura", valor=-127, unidade="°C", valido=False, ts=agora()))
    s.commit()
    alertas.avaliar(s)
    assert s.query(Alerta).filter_by(tipo="falha_sensor_temperatura").count() == 1


# ------------------------------- API -------------------------------
@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def test_api_sem_login(cliente):
    assert cliente.get("/api/estado").status_code == 200
    assert cliente.post("/api/login", json={"login": "admin", "senha": "x"}).status_code in (404, 405)


def test_envia_comando_sem_login(cliente):
    corpo = {"device_id": "ctrl-01", "acao": "dosar", "params": {"alvo": "bomba_ph_mais", "duracao_ms": 1000}}
    r = cliente.post("/api/comandos", json=corpo)
    assert r.status_code == 201 and r.json()["status"] == "enviado"
    assert ponte.publicados[-1][0] == "aquario/v1/ctrl-01/cmd"


def test_comando_fora_da_faixa_422(cliente):
    corpo = {"device_id": "ctrl-01", "acao": "dosar", "params": {"alvo": "bomba_ph_mais", "duracao_ms": 9000}}
    assert cliente.post("/api/comandos", json=corpo).status_code == 422


def test_config_valida_faixas(cliente):
    assert cliente.put("/api/config", json={"ph_min": 8, "ph_max": 7}).status_code == 422
    r = cliente.put("/api/config", json={"ph_min": 6.8})
    assert r.status_code == 200 and r.json()["valores"]["ph_min"] == 6.8


def test_analitico(cliente, s):
    processar(s, "aquario/v1/ctrl-01/status", status(True))
    for i in range(30):
        s.add(Medicao(device_id="sonda-01", grandeza="ph", valor=7.0 if i % 3 else 8.0, unidade="pH",
                      valido=True, ts=agora() - timedelta(minutes=i)))
    s.commit()
    r = cliente.get("/api/analitico?periodo=24h").json()
    assert r["ph"]["leituras"] == 30
    assert r["ph"]["pct_fora_faixa"] == pytest.approx(33.3, abs=0.1)
    assert r["ph"]["pontos"] and "media_movel_30min" in r["ph"]["pontos"][0]
    assert len(r["doses_por_dia"]) == 7
