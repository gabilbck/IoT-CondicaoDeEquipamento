"""Conexão do backend com o Mosquitto (TLS validado pela CA própria + usuário/senha)."""
import logging
import ssl
import threading
import uuid
from datetime import datetime
from typing import Optional

import paho.mqtt.client as mqtt

from . import config, db, ingestao
from .models import agora

log = logging.getLogger("mqtt")


class Ponte:
    def __init__(self):
        self.conectado = False
        self.desconectado_desde: Optional[datetime] = agora()
        self._lock = threading.Lock()
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=f"backend-{uuid.uuid4().hex[:8]}")
        self.cliente.username_pw_set(config.MQTT_USUARIO, config.MQTT_SENHA)
        if config.MQTT_TLS:
            # valida o certificado do broker contra a CA própria (sem tls_insecure)
            self.cliente.tls_set(ca_certs=config.MQTT_CA, cert_reqs=ssl.CERT_REQUIRED,
                                 tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=30)
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_disconnect = self._ao_desconectar
        self.cliente.on_message = self._ao_receber

    def iniciar(self):
        self.cliente.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        self.cliente.loop_start()

    def parar(self):
        self.cliente.loop_stop()
        self.cliente.disconnect()

    def publicar(self, topico: str, payload: str) -> bool:
        """Comandos: QoS 1, sem retain (CONTRATOS.md §2)."""
        if not self.conectado:
            log.warning("broker desconectado: comando em %s não publicado (vai expirar)", topico)
            return False
        info = self.cliente.publish(topico, payload, qos=1, retain=False)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def _ao_conectar(self, cliente, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("falha ao conectar no broker: %s", reason_code)
            return
        self.conectado = True
        self.desconectado_desde = None
        cliente.subscribe(f"{config.PREFIXO}/#", qos=1)
        log.info("conectado a %s:%s, assinando %s/#", config.MQTT_HOST, config.MQTT_PORT, config.PREFIXO)

    def _ao_desconectar(self, cliente, userdata, flags, reason_code, properties):
        if self.conectado:
            self.desconectado_desde = agora()
        self.conectado = False
        log.warning("desconectado do broker (%s); reconectando...", reason_code)

    def _ao_receber(self, cliente, userdata, msg):
        if msg.topic.endswith("/cmd"):
            return  # o backend não consome os próprios comandos
        with self._lock:
            try:
                with db.sessao() as s:
                    ingestao.processar(s, msg.topic, msg.payload)
            except Exception:  # nunca derrubar a thread do paho
                log.exception("erro ao processar %s", msg.topic)


class PonteDesligada:
    """Usada quando MQTT_HABILITADO=0 (testes): guarda o que seria publicado."""

    def __init__(self):
        self.conectado = True
        self.desconectado_desde = None
        self.publicados: list[tuple[str, str]] = []

    def iniciar(self):
        pass

    def parar(self):
        pass

    def publicar(self, topico: str, payload: str) -> bool:
        self.publicados.append((topico, payload))
        return True
