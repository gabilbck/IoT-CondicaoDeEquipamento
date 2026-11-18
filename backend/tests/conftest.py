import os
import tempfile

os.environ.update({
    "DATABASE_URL": "sqlite://",
    "MQTT_HABILITADO": "0",
    "LACO_TAREFAS": "0",
    "FIRMWARE_DIR": tempfile.mkdtemp(),
})

import pytest  # noqa: E402

from app import alertas, db  # noqa: E402
from app.db import Base  # noqa: E402

NOTIFICACOES: list[str] = []
alertas.notificador = lambda texto: NOTIFICACOES.append(texto) or True


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(db.engine)
    Base.metadata.create_all(db.engine)
    NOTIFICACOES.clear()
    yield


@pytest.fixture
def s():
    sess = db.SessionLocal()
    yield sess
    sess.close()


class Publicador:
    def __init__(self):
        self.msgs = []

    def __call__(self, topico, payload):
        self.msgs.append((topico, payload))
        return True


@pytest.fixture
def pub():
    return Publicador()
