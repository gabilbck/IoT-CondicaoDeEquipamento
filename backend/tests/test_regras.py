from datetime import timedelta

from app import regras
from app.ingestao import processar
from app.models import Comando, Medicao, agora

from .util import estado_ctrl, status


def _ctrl(s, **kw):
    processar(s, "aquario/v1/ctrl-01/status", status(True))
    processar(s, "aquario/v1/ctrl-01/estado", estado_ctrl(**kw))
    s.commit()


def _ph(s, valor, n=20, ate_s=0, passo_s=10):
    t = agora() - timedelta(seconds=ate_s)
    for i in range(n):
        s.add(Medicao(device_id="sonda-01", grandeza="ph", valor=valor, unidade="pH", valido=True,
                      ts=t - timedelta(seconds=i * passo_s)))
    s.commit()


def _temp(s, valor):
    s.add(Medicao(device_id="sonda-01", grandeza="temperatura", valor=valor, unidade="°C", valido=True, ts=agora()))
    s.commit()


def test_ph_baixo_dosa_ph_mais(s, pub):
    _ctrl(s)
    _ph(s, 6.0)
    criados = regras.executar_regras(s, pub)
    assert len(criados) == 1
    c = criados[0]
    assert c.acao == "dosar" and c.params == {"alvo": "bomba_ph_mais", "duracao_ms": 1000}
    assert c.origem == "regra:ph_baixo"


def test_ph_alto_dosa_ph_menos(s, pub):
    _ctrl(s)
    _ph(s, 8.2)
    assert regras.executar_regras(s, pub)[0].params["alvo"] == "bomba_ph_menos"


def test_ph_na_faixa_nao_dosa(s, pub):
    _ctrl(s)
    _ph(s, 7.0)
    assert regras.executar_regras(s, pub) == []


def test_poucas_leituras_nao_dosa(s, pub):
    _ctrl(s)
    _ph(s, 6.0, n=3)
    assert regras.executar_regras(s, pub) == []


def test_respeita_intervalo_minimo_entre_doses(s, pub):
    _ctrl(s)
    _ph(s, 6.0)
    c = regras.executar_regras(s, pub)[0]
    c.status = "confirmado"
    s.commit()
    assert regras.executar_regras(s, pub) == []  # dose há menos de 15 min


def test_respeita_limite_de_doses_por_hora(s, pub):
    _ctrl(s)
    _ph(s, 6.0)
    for minutos in (20, 40, 55):
        s.add(Comando(command_id=f"00000000-0000-4000-8000-0000000000{minutos}", device_id="ctrl-01",
                      origem="regra:ph_baixo", acao="dosar", params={"alvo": "bomba_ph_mais", "duracao_ms": 1000},
                      status="confirmado", expira_em_s=10, enviado_em=agora() - timedelta(minutes=minutos)))
    s.commit()
    assert regras.executar_regras(s, pub) == []


def test_media_ignora_leituras_logo_apos_dose(s, pub):
    """Leituras nos 10 s após uma dose (ruído) não entram na média."""
    cfg = regras.config_backend(s)
    _ph(s, 7.0, n=20)
    dose = agora() - timedelta(seconds=60)
    s.add(Comando(command_id="00000000-0000-4000-8000-000000000001", device_id="ctrl-01", origem="usuario",
                  acao="dosar", params={"alvo": "bomba_ph_mais", "duracao_ms": 1000}, status="confirmado",
                  expira_em_s=10, enviado_em=dose))
    s.add(Medicao(device_id="sonda-01", grandeza="ph", valor=2.0, unidade="pH", valido=True,
                  ts=dose + timedelta(seconds=5)))
    s.commit()
    media, _ = regras.media_ph(s, cfg, agora())
    assert abs(media - 7.0) < 1e-6


def test_regras_nao_rodam_fora_do_auto(s, pub):
    _ctrl(s, modo="MANUAL")
    _ph(s, 6.0)
    assert regras.executar_regras(s, pub) == []


def test_regras_nao_rodam_com_controlador_offline(s, pub):
    _ctrl(s)
    processar(s, "aquario/v1/ctrl-01/status", status(False))
    _ph(s, 6.0)
    assert regras.executar_regras(s, pub) == []


def test_nao_empilha_comando_enquanto_outro_pendente(s, pub):
    _ctrl(s)
    _temp(s, 20.0)
    assert len(regras.executar_regras(s, pub)) == 1
    assert regras.executar_regras(s, pub) == []


# ---- temperatura com histerese ----
CFG = {"temp_min": 24.0, "temp_max": 28.0, "histerese_temp": 0.5}
OFF = {"aquecedor": "OFF", "cooler": "OFF"}


def _acoes(temp, atuadores):
    return [(d.acao, d.params["estado"]) for d in regras.decidir_temperatura(CFG, temp, atuadores)]


def test_temp_baixa_liga_aquecedor():
    assert _acoes(23.5, OFF) == [("aquecedor", "ON")]


def test_aquecedor_continua_ate_min_mais_histerese():
    assert _acoes(24.3, {"aquecedor": "ON", "cooler": "OFF"}) == []  # dentro da histerese
    assert _acoes(24.5, {"aquecedor": "ON", "cooler": "OFF"}) == [("aquecedor", "OFF")]


def test_temp_alta_liga_cooler_e_desliga_com_histerese():
    assert _acoes(28.6, OFF) == [("cooler", "ON")]
    assert _acoes(27.8, {"aquecedor": "OFF", "cooler": "ON"}) == []
    assert _acoes(27.5, {"aquecedor": "OFF", "cooler": "ON"}) == [("cooler", "OFF")]


def test_temp_baixa_com_cooler_ligado_desliga_cooler_antes():
    assert _acoes(23.0, {"aquecedor": "OFF", "cooler": "ON"}) == [("cooler", "OFF"), ("aquecedor", "ON")]


def test_sem_temperatura_nao_decide():
    assert _acoes(None, OFF) == []
