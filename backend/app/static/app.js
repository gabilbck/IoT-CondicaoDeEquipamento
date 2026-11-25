// Interface do Aquário Inteligente: painéis de pH e temperatura, dispositivos, comandos, alertas e configuração.
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let graficos = {};

// ---------------- textos da interface ----------------
// Nome e explicação de cada regra do servidor (PUT /api/config)
const CAMPOS_CONFIG = {
  ph_min: ["pH mínimo", "Abaixo da média deste valor, o servidor dosa pH+ (modo AUTO)."],
  ph_max: ["pH máximo", "Acima da média deste valor, o servidor dosa pH− (modo AUTO)."],
  janela_media_ph_s: ["Janela da média (s)", "O servidor decide pela média do pH neste intervalo, para não reagir a picos. 300 s = 5 min."],
  leituras_minimas_media: ["Leituras mínimas na média", "Quantidade mínima de leituras válidas na janela para o servidor agir."],
  dose_ms: ["Duração da dose (ms)", "Quanto tempo a bomba fica ligada em cada dose automática. 1000 ms = 1 s."],
  intervalo_min_doses_s: ["Intervalo entre doses (s)", "Tempo mínimo entre duas doses, para o pH ter tempo de se misturar. 900 s = 15 min."],
  doses_max_hora: ["Doses máximas por hora", "Limite de segurança: nunca dosa mais que isso em 1 hora."],
  descartar_ph_apos_dose_s: ["Ignorar pH após dose (s)", "Leituras logo depois de uma dose são descartadas da média (a água ainda está misturando)."],
  temp_min: ["Temperatura mínima (°C)", "Abaixo disso, o servidor libera o aquecedor (modo AUTO)."],
  temp_max: ["Temperatura máxima (°C)", "Acima disso, o servidor liga o cooler (modo AUTO)."],
  histerese_temp: ["Histerese (°C)", "Margem para não ficar ligando e desligando: o aquecedor só é bloqueado de novo em mínima + histerese; o cooler só desliga em máxima − histerese."],
  alerta_fora_faixa_min: ["Alerta de fora da faixa após (min)", "Só gera alerta se o pH ou a temperatura ficarem fora da faixa ideal por este tempo."],
  offline_alerta_min: ["Alerta de offline após (min)", "Só gera alerta se um dispositivo ficar sem contato por este tempo."],
  alerta_intervalo_min: ["Intervalo entre alertas iguais (min)", "Evita repetir o mesmo alerta (e a mesma mensagem de WhatsApp) antes deste tempo."],
  comando_expira_s: ["Prazo de resposta do comando (s)", "Se a placa não responder neste tempo, o comando vira “expirado”."],
};

const NOMES_ACAO = { dosar: "Dosar", aquecedor: "Aquecedor", cooler: "Cooler", modo: "Mudar modo", silenciar: "Silenciar buzzer", config: "Ajustar configuração", ota: "Atualizar firmware" };
const NOMES_ALVO = { bomba_ph_mais: "bomba pH+", bomba_ph_menos: "bomba pH−" };
const NOMES_DISP = { "sonda-01": "Sonda", "ctrl-01": "Controlador" };
const NOMES_ALERTA = {
  ph_fora_faixa: "pH fora da faixa", temp_fora_faixa: "Temperatura fora da faixa",
  falha_sensor_ph: "Falha no sensor de pH", falha_sensor_temperatura: "Falha no sensor de temperatura",
  dispositivo_offline: "Dispositivo offline", modo_seguro: "Controlador em modo SEGURO", broker_indisponivel: "Broker fora do ar",
};
const ESTADO_LOCAL = {
  NORMAL: "Normal",
  ALERTA_LOCAL: "Alerta (fora da faixa crítica)",
  FALHA_SENSOR: "Falha de sensor",
};
const CAUSA_SEGURO = { rede: "sem rede/telemetria", sensor: "falha de sensor", comando: "pedido pelo usuário", config: "configuração inválida" };

// ---------------- utilidades ----------------
async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, { ...opcoes, headers: { "Content-Type": "application/json", ...(opcoes.headers || {}) } });
  const corpo = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(corpo?.detail ? (typeof corpo.detail === "string" ? corpo.detail : JSON.stringify(corpo.detail)) : r.statusText);
  return corpo;
}
const hora = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR") : "—");
const atras = (iso) => {
  if (!iso) return "nunca";
  const s = Math.round((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `há ${s} s`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  return `há ${Math.round(s / 3600)} h`;
};
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (v, casas) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));
const faixa = (a, b, un = "") => (a == null || b == null ? "—" : `${num(a, 1)} a ${num(b, 1)}${un}`);
const duracao = (s) => (s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`);

function selo(el, online) { el.textContent = online ? "online" : "offline"; el.className = "selo " + (online ? "on" : "off"); }
function dl(el, pares) {
  el.innerHTML = pares.map(([k, v, ajuda]) =>
    `<dt>${esc(k)}${ajuda ? ` <span class="i" title="${esc(ajuda)}">i</span>` : ""}</dt><dd>${esc(v)}</dd>`).join("");
}
function detalheComando(c) {
  const p = c.params || {};
  switch (c.acao) {
    case "dosar": return `${NOMES_ALVO[p.alvo] || p.alvo} por ${p.duracao_ms / 1000} s`;
    case "aquecedor": return p.estado === "ON" ? "liberar" : "bloquear";
    case "cooler": return p.estado === "ON" ? "ligar" : "desligar";
    case "modo": return p.modo;
    case "silenciar": return `por ${duracao(p.duracao_s)}`;
    case "ota": return `versão ${p.versao}`;
    default: return JSON.stringify(p);
  }
}
function origemComando(c) {
  if (c.origem === "usuario") return "Usuário (painel)";
  if (c.origem?.startsWith("regra:")) return `Automático (${c.origem.slice(6).replace(/_/g, " ")})`;
  return c.origem;
}

// Situação de uma leitura em relação à faixa ideal
function situacao(leitura, min, max) {
  if (!leitura) return ["sem dados", ""];
  if (!leitura.valido) return ["leitura inválida", "off"];
  if (leitura.valor < min) return ["abaixo da faixa", "aviso"];
  if (leitura.valor > max) return ["acima da faixa", "aviso"];
  return ["dentro da faixa", "on"];
}

// ---------------- estado atual (a cada 2 s) ----------------
async function atualizarRapido() {
  try {
    const [e, ativos, cmds] = await Promise.all([api("/api/estado"), api("/api/alertas?ativos=true"), api("/api/comandos?limite=15")]);
    const b = $("#broker");
    b.textContent = e.broker_conectado ? "broker conectado" : "broker indisponível";
    b.className = "selo " + (e.broker_conectado ? "on" : "off");

    const cfg = e.config;
    const s = e.dispositivos["sonda-01"], c = e.dispositivos["ctrl-01"];
    const se = s.estado || {}, scfg = se.config || {};
    const ce = c.estado || {}, at = ce.atuadores || {};
    const ph = e.leituras.ph, temp = e.leituras.temperatura;

    // pH
    $("#v-ph").textContent = ph && ph.valido ? num(ph.valor, 2) : ph ? "inválido" : "—";
    const [tph, cph] = situacao(ph, cfg.ph_min, cfg.ph_max);
    $("#st-ph").textContent = tph; $("#st-ph").className = "selo " + cph;
    $("#atual-ph").classList.toggle("fora", cph === "aviso" || cph === "off");
    $("#ph-faixa").textContent = faixa(cfg.ph_min, cfg.ph_max);
    $("#ph-crit").textContent = faixa(scfg.ph_crit_min, scfg.ph_crit_max);
    const tel = se.ultima_telemetria?.leituras?.find((l) => l.grandeza === "ph");
    $("#ph-tensao").textContent = tel?.tensao_v != null ? `${num(tel.tensao_v, 3)} V` : "—";
    $("#ph-quando").textContent = ph ? atras(ph.ts) : "—";

    // Temperatura
    $("#v-temp").textContent = temp && temp.valido ? `${num(temp.valor, 1)} °C` : temp ? "inválido" : "—";
    const [tt, ct] = situacao(temp, cfg.temp_min, cfg.temp_max);
    $("#st-temp").textContent = tt; $("#st-temp").className = "selo " + ct;
    $("#atual-temp").classList.toggle("fora", ct === "aviso" || ct === "off");
    $("#temp-faixa").textContent = faixa(cfg.temp_min, cfg.temp_max, " °C");
    $("#temp-crit").textContent = faixa(scfg.temp_crit_min, scfg.temp_crit_max, " °C");
    $("#temp-aquec").textContent = !c.online ? "— (controlador offline)" : at.aquecedor === "ON" ? "liberado (termostato)" : at.aquecedor === "OFF" ? "bloqueado" : "—";
    $("#temp-cooler").textContent = !c.online ? "— (controlador offline)" : at.cooler === "ON" ? "ligado" : at.cooler === "OFF" ? "desligado" : "—";
    $("#temp-quando").textContent = temp ? atras(temp.ts) : "—";

    // Dispositivos
    selo($("#on-sonda"), s.online); selo($("#on-ctrl"), c.online);
    dl($("#d-sonda"), [
      ["Último contato", atras(s.ultimo_contato), "Quando a sonda mandou a última mensagem. Fica offline após 2 min sem contato."],
      ["Situação local", ESTADO_LOCAL[se.estado_local] || "—", "Avaliada pela própria sonda: Normal; Alerta = fora da faixa crítica (buzzer apita); Falha de sensor = leitura impossível (sensor solto ou com defeito)."],
      ["Buzzer", se.silenciado_s ? `silenciado por mais ${duracao(se.silenciado_s)}` : se.estado_local === "ALERTA_LOCAL" ? "apitando" : "em espera", "O buzzer só apita em Alerta. “Silenciado” = alguém clicou em Silenciar buzzer."],
      ["Firmware", s.fw || "—", "Versão do programa gravado na placa."],
      ["Sinal Wi-Fi", se.rssi_dbm != null ? `${se.rssi_dbm} dBm (${se.rssi_dbm > -60 ? "ótimo" : se.rssi_dbm > -75 ? "bom" : "fraco"})` : "—", "Intensidade do Wi-Fi na placa. Quanto mais perto de 0, melhor."],
      ["Disponibilidade", $("#d-sonda").dataset.uptime || "—", "Percentual do período escolhido em que a sonda ficou online."],
    ]);
    dl($("#d-ctrl"), [
      ["Último contato", atras(c.ultimo_contato), "Quando o controlador mandou a última mensagem."],
      ["Modo", (ce.modo || "—") + (ce.causa_seguro ? ` (causa: ${CAUSA_SEGURO[ce.causa_seguro] || ce.causa_seguro})` : ""), "AUTO, MANUAL, SEGURO ou BOOT (iniciando)."],
      ["Bomba pH+", at.bomba_ph_mais === "ON" ? "dosando" : at.bomba_ph_mais ? "parada" : "—"],
      ["Bomba pH−", at.bomba_ph_menos === "ON" ? "dosando" : at.bomba_ph_menos ? "parada" : "—"],
      ["Nível da água", ce.nivel === "OK" ? "OK" : ce.nivel === "BAIXO" ? "BAIXO (aquecedor bloqueado)" : "—", "Lido pela boia. Com nível baixo o aquecedor é bloqueado por segurança."],
      ["Firmware", c.fw || "—"],
      ["Disponibilidade", $("#d-ctrl").dataset.uptime || "—", "Percentual do período escolhido em que o controlador ficou online."],
    ]);
    preencherSonda(scfg);
    marcarBotoesAtivos(c.online, ce.modo, at);

    // Alertas ativos
    $("#alertas-ativos").innerHTML = ativos.map((a) =>
      `<div class="alerta ${a.severidade}"><b>⚠️ ${esc(NOMES_ALERTA[a.tipo] || a.tipo)}</b> · ${esc(a.mensagem)} <span class="quando">desde ${hora(a.criado_em)}</span></div>`).join("");

    // Comandos
    $("#t-comandos").innerHTML = cmds.length ? cmds.map((c) => `<tr>
      <td>${hora(c.enviado_em)}</td><td>${esc(NOMES_DISP[c.device_id] || c.device_id)}</td>
      <td>${esc(NOMES_ACAO[c.acao] || c.acao)}</td><td>${esc(detalheComando(c))}</td><td>${esc(origemComando(c))}</td>
      <td class="st-${c.status}">${esc(c.status)}${c.codigo ? ` <span class="codigo" title="Código de erro do contrato MQTT (CONTRATOS.md)">${esc(c.codigo)}</span>` : ""}</td>
      <td><button class="secundario" data-reenviar="${c.command_id}" title="Reenvia exatamente o mesmo comando (mesmo identificador). Serve para o teste de duplicidade: a placa deve recusar com E_DUPLICADO.">↻</button></td>
    </tr>`).join("") : `<tr><td colspan="7" class="vazio">Nenhum comando ainda.</td></tr>`;
  } catch (err) { console.error(err); }
}

// ---------------- botões que mostram o estado atual ----------------
// Destaca o botão que corresponde ao que o controlador está fazendo agora:
// modo AUTO (verde), MANUAL (laranja) ou SEGURO (vermelho); aquecedor liberado/bloqueado; cooler ligado/desligado.
// Com o controlador offline, nenhum fica destacado (o estado real é desconhecido).
const TOM_MODO = { AUTO: "ok", MANUAL: "aviso", SEGURO: "perigo" };
function marcarBotoesAtivos(online, modo, atuadores) {
  for (const b of $$("button[data-cmd]")) {
    const cmd = JSON.parse(b.dataset.cmd);
    let ativo;
    if (cmd.device_id !== "ctrl-01") continue;
    if (cmd.acao === "modo") { ativo = modo === cmd.params.modo; b.dataset.tom = TOM_MODO[cmd.params.modo]; }
    else if (cmd.acao === "aquecedor" || cmd.acao === "cooler") { ativo = atuadores[cmd.acao] === cmd.params.estado; b.dataset.tom = "ok"; }
    else continue;
    ativo = Boolean(online && ativo);
    b.classList.toggle("ativo", ativo);
    b.setAttribute("aria-pressed", String(ativo));
  }
}

// ---------------- comandos ----------------
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-cmd], button[data-reenviar]");
  if (!b) return;
  b.disabled = true;
  try {
    if (b.dataset.cmd) {
      const c = await api("/api/comandos", { method: "POST", body: b.dataset.cmd });
      aviso(`Comando “${NOMES_ACAO[c.acao] || c.acao}: ${detalheComando(c)}” enviado para ${NOMES_DISP[c.device_id]}. Acompanhe a situação em “Últimos comandos”.`);
    } else {
      await api(`/api/comandos/${b.dataset.reenviar}/reenviar`, { method: "POST" });
      aviso("Mesmo comando reenviado: a placa deve recusar com E_DUPLICADO.");
    }
    atualizarRapido();
  } catch (err) { aviso("Erro: " + err.message, true); }
  b.disabled = false;
});
function aviso(texto, erro = false) {
  const el = $("#msg-cmd"); el.textContent = texto; el.className = "mensagem visivel" + (erro ? " erro" : "");
  clearTimeout(aviso.t); aviso.t = setTimeout(() => (el.className = "mensagem"), 8000);
}

// ---------------- regras do servidor (PUT /api/config) ----------------
async function carregarConfig() {
  const { valores, faixas } = await api("/api/config");
  for (const form of $$("form[data-chaves]")) {
    const chaves = form.dataset.chaves.split(",");
    form.innerHTML = chaves.map((k) => {
      const [nome, ajuda] = CAMPOS_CONFIG[k] || [k, ""];
      return `<label>${esc(nome)} <small>${esc(ajuda)}</small>
        <input type="number" step="any" name="${k}" value="${valores[k]}" min="${faixas[k][0]}" max="${faixas[k][1]}"
               title="Valores aceitos: ${faixas[k][0]} a ${faixas[k][1]}"></label>`;
    }).join("") + `<div class="rodape-form"><button type="submit">Salvar</button><span class="pequeno msg"></span></div>`;
  }
}
for (const form of $$("form[data-chaves]")) {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const dados = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, Number(v)]));
    const msg = form.querySelector(".msg");
    try {
      await api("/api/config", { method: "PUT", body: JSON.stringify(dados) });
      msg.textContent = "✓ Salvo."; atualizarRapido(); atualizarLento();
    } catch (err) { msg.textContent = "Erro: " + err.message; }
  });
}

// ---------------- ajustes da sonda (comando config) ----------------
let sondaEditando = false;
// Valores enviados que a sonda ainda não informou de volta no estado (evita o formulário "voltar" ao valor antigo)
let sondaPendente = null;
function msgSonda(texto, tom) { const m = $("#msg-sonda"); m.textContent = texto; m.className = "envio" + (tom ? " " + tom : ""); }
$("#form-sonda").addEventListener("input", () => (sondaEditando = true));
function preencherSonda(scfg) {
  if (sondaPendente) {
    const aplicado = Object.entries(sondaPendente.params).every(([k, v]) => scfg[k] != null && Math.abs(scfg[k] - v) < 0.001);
    if (!aplicado && Date.now() - sondaPendente.desde < 15000) return; // mantém o que foi enviado até a sonda confirmar
    msgSonda(aplicado ? "✓ A sonda confirmou e já está usando os valores novos." : "✗ A sonda não confirmou em 15 s (offline?). Veja o motivo em “Últimos comandos”.", aplicado ? "ok" : "erro");
    sondaPendente = null; // aplicado, ou passou o prazo (aí mostra o valor real da sonda)
  }
  if (sondaEditando) return; // não sobrescreve o que a pessoa está digitando
  for (const k of ["ph_crit_min", "ph_crit_max", "temp_crit_min", "temp_crit_max", "ph_slope", "ph_offset"]) {
    const el = $(`#form-sonda [name=${k}]`);
    if (el && scfg[k] != null) el.value = Math.round(scfg[k] * 1000) / 1000;
  }
}
$("#form-sonda").addEventListener("submit", async (e) => {
  e.preventDefault();
  const params = Object.fromEntries([...new FormData(e.target)].filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
  const botao = e.target.querySelector("button[type=submit]");
  botao.disabled = true;
  msgSonda("Enviando…");
  try {
    await api("/api/comandos", { method: "POST", body: JSON.stringify({ device_id: "sonda-01", acao: "config", params }) });
    msgSonda("✓ Enviado. Aguardando a sonda confirmar…", "aviso");
    sondaPendente = { params, desde: Date.now() };
    sondaEditando = false;
    atualizarRapido();
  } catch (err) { msgSonda("✗ Erro ao enviar: " + err.message, "erro"); }
  finally { botao.disabled = false; }
});
$("#cal-calcular").addEventListener("click", () => {
  const p1 = Number($("#cal-p1").value), v1 = Number($("#cal-v1").value);
  const p2 = Number($("#cal-p2").value), v2 = Number($("#cal-v2").value);
  if (!v1 || !v2 || v1 === v2) { $("#cal-msg").textContent = "Preencha as duas tensões (diferentes entre si)."; return; }
  const slope = (p1 - p2) / (v1 - v2), offset = p1 - slope * v1;
  $("#form-sonda [name=ph_slope]").value = slope.toFixed(3);
  $("#form-sonda [name=ph_offset]").value = offset.toFixed(3);
  sondaEditando = true;
  const ok = slope < -4 && slope > -8;
  $("#cal-msg").textContent = `Inclinação ${slope.toFixed(3)} · deslocamento ${offset.toFixed(3)}. ` +
    (ok ? "Valores dentro do esperado. Clique em “Enviar para a sonda”." : "Atenção: inclinação fora do esperado (−4 a −8). Confira as medições ou o eletrodo.");
});

// ---------------- gráficos e indicadores (a cada 60 s) ----------------
$("#periodo").addEventListener("change", atualizarLento);
function grafico(id, cfg) { if (graficos[id]) graficos[id].destroy(); graficos[id] = new Chart(document.getElementById(id), cfg); }
function linha(serie, titulo, cor) {
  const labels = serie.pontos.map((p) => new Date(p.ts).toLocaleString("pt-BR", { day: "2-digit", hour: "2-digit", minute: "2-digit" }));
  const n = labels.length;
  return {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: titulo, data: serie.pontos.map((p) => p.media), borderColor: cor, pointRadius: 0, tension: 0.2 },
        { label: "média móvel 30 min", data: serie.pontos.map((p) => p.media_movel_30min), borderColor: "#888", borderDash: [5, 4], pointRadius: 0 },
        { label: "faixa ideal", data: Array(n).fill(serie.faixa[0]), borderColor: "#c5303088", pointRadius: 0, borderWidth: 1 },
        { label: "_max", data: Array(n).fill(serie.faixa[1]), borderColor: "#c5303088", pointRadius: 0, borderWidth: 1 },
      ],
    },
    options: { maintainAspectRatio: false, animation: false,
      plugins: { legend: { labels: { filter: (i) => !i.text.startsWith("_") } } } },
  };
}
async function atualizarLento() {
  try {
    const [p, todos] = await Promise.all([api("/api/analitico?periodo=" + $("#periodo").value), api("/api/alertas?limite=30")]);
    const pct = (v) => (v != null ? `${num(v, 1)} %` : "—");
    $("#ph-pct").textContent = pct(p.ph.pct_fora_faixa);
    $("#temp-pct").textContent = pct(p.temperatura.pct_fora_faixa);
    const hoje = p.doses_por_dia.at(-1);
    $("#ph-doses").textContent = hoje ? `${hoje.ph_mais} de pH+ · ${hoje.ph_menos} de pH−` : "0";
    $("#d-sonda").dataset.uptime = pct(p.uptime_pct["sonda-01"]);
    $("#d-ctrl").dataset.uptime = pct(p.uptime_pct["ctrl-01"]);

    if (window.Chart) {
      grafico("g-ph", linha(p.ph, "pH", "#0e7c86"));
      grafico("g-temp", linha(p.temperatura, "Temperatura (°C)", "#d98e04"));
      grafico("g-doses", {
        type: "bar",
        data: {
          labels: p.doses_por_dia.map((d) => d.dia.slice(8, 10) + "/" + d.dia.slice(5, 7)),
          datasets: [
            { label: "pH+", data: p.doses_por_dia.map((d) => d.ph_mais), backgroundColor: "#1f9d55" },
            { label: "pH−", data: p.doses_por_dia.map((d) => d.ph_menos), backgroundColor: "#c53030" },
          ],
        },
        options: { maintainAspectRatio: false, animation: false,
          plugins: { title: { display: true, text: "Doses por dia (últimos 7 dias)" } },
          scales: { x: { stacked: true }, y: { stacked: true, ticks: { precision: 0 } } } },
      });
    }
    $("#t-alertas").innerHTML = todos.length ? todos.map((a) => `<tr>
      <td>${hora(a.criado_em)}</td><td>${esc(NOMES_ALERTA[a.tipo] || a.tipo)}</td><td>${esc(a.mensagem)}</td>
      <td>${a.resolvido_em ? hora(a.resolvido_em) : '<span class="st-rejeitado">ainda ativo</span>'}</td></tr>`).join("")
      : `<tr><td colspan="4" class="vazio">Nenhum alerta.</td></tr>`;
  } catch (err) { console.error(err); }
}

// ---------------- início ----------------
atualizarLento().then(atualizarRapido);
carregarConfig();
setInterval(atualizarRapido, 2000);
setInterval(atualizarLento, 60000);
