# Aquário Inteligente — pH e temperatura sob controle, de qualquer lugar

Projeto da disciplina de Internet das Coisas (2026/2): **Condição de Equipamento**.

## Integrantes

- Gabrieli Eduarda Lembeck
- Heloisa Rebello Cabral
- Julio Bezerra de Mattos Manoel
- Mileine da Silva de Freitas
- Thomas Henry Steinback

## Problema e usuário

**Usuário:** o aquarista (doméstico ou de loja pequena) que passa o dia fora e mantém peixes ou plantas
sensíveis a variações da água.

**Problema:** pH e temperatura mudam ao longo do dia. Fora da faixa da espécie, isso causa estresse, doença e
morte. A medição manual com kit é feita de vez em quando, e ninguém percebe o problema quando está longe do aquário.

## Estado atual (herdado da N1)

Um ESP32 lê o pH real (sensor PH-4502C), mostra o valor num display OLED e publica a leitura por MQTT. Um
servidor FastAPI em Docker compara o pH com a faixa 6,5–7,5 e manda de volta um comando `ON`/`OFF`, que o ESP32
executa num LED. Há também um dashboard web simples. Detalhes da N1 em [docs/N1_README.md](docs/N1_README.md).

## Para onde o upgrade está indo (N3)

Um produto que **mede, avisa e corrige sozinho**:

- **Mede:** pH **e temperatura**, em uma sonda com ESP32.
- **Avisa:** alerta no **WhatsApp/SMS** quando algo sai da faixa, o dispositivo cai ou um sensor falha.
- **Corrige:** um segundo ESP32 controla bombas dosadoras de **pH+ / pH-**, **aquecedor** e **cooler**, a partir
  de regras no backend. Tem travas de segurança locais: limite de dose, intertravamento e estado seguro.
- **Mostra:** interface web com login, histórico, gráficos e comandos com confirmação.
- **Roda na nuvem:** Mosquitto (TLS) + backend FastAPI + PostgreSQL num `docker compose` remoto.

Documentos do upgrade:

- [Proposta de upgrade (CP12)](docs/CP12_proposta_upgrade.md): ponto de partida, upgrade por camada,
  conferência R1–R18 e arquitetura-alvo.
- [Backlog](BACKLOG.md).

## Estrutura atual

```
codigo/            firmware da N1 (ESP32) e sketch de calibração
ph-server/         servidor FastAPI + dashboard (N1)
docs/              documentação do upgrade e README da N1
```

As instruções completas de instalação e execução entram na versão final da N3 (R11).

## Licença

MIT — ver [LICENSE](LICENSE).
