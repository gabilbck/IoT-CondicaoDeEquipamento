// Interface do Aquário Inteligente: cards, alertas, gráficos (Chart.js), comandos e configuração (sem login).
const $ = (s) => document.querySelector(s);
let graficos = {};
let timerRapido = null, timerLento = null;

const NOMES_CONFIG = {
  ph_min: "pH mínimo", ph_max: "pH máximo", temp_min: "Temp. mínima (°C)", temp_max: "Temp. máxima (°C)",
  histerese_temp: "Histerese temp. (°C)", janela_media_ph_s: "Janela média pH (s)",
  leituras_minimas_media: "Leituras mín. na média", dose_ms: "Dose (ms)",
  intervalo_min_doses_s: "Intervalo entre doses (s)", doses_max_hora: "Doses máx./hora",
  descartar_ph_apos_dose_s: "Descartar pH após dose (s)", alerta_fora_faixa_min: "Alerta fora da faixa (min)",
  offline_alerta_min: "Alerta offline (min)", alerta_intervalo_min: "Intervalo entre alertas (min)",
  comando_expira_s: "Comando expira (s)",
};

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, {
    ...opcoes,
    headers: { "Content-Type": "application/json", ...(opcoes.headers || {}) },
  });
  const corpo = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(corpo?.detail ? (typeof corpo.detail === "string" ? corpo.detail : JSON.stringify(corpo.detail)) : r.statusText);
  return corpo;
}

const hora = (iso) => iso ? new Date(iso).toLocaleString("pt-BR") : "—";
const atras = (iso) => {
  if (!iso) return "nunca";
  const s = Math.round((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `há ${s} s`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  return `há ${Math.round(s / 3600)} h`;
};
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------- início ----------------
function iniciar() {
  atualizarRapido(); atualizarLento(); carregarConfig();
  timerRapido = setInterval(atualizarRapido, 2000);
  timerLento = setInterval(atualizarLento, 60000);
}

// ---------------- estado atual ----------------
function selo(el, online) { el.textContent = online ? "online" : "offline"; el.className = "selo " + (online ? "on" : "off"); }

function dl(el, pares) { el.innerHTML = pares.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join(""); }

async function atualizarRapido() {
  try {
    const [e, ativos, cmds] = await Promise.all([api("/api/estado"), api("/api/alertas?ativos=true"), api("/api/comandos?limite=15")]);
    const b = $("#broker"); b.textContent = e.broker_conectado ? "broker conectado" : "broker indisponível";
    b.className = "selo " + (e.broker_conectado ? "on" : "off");

    const cfg = e.config;
    const ph = e.leituras.ph, temp = e.leituras.temperatura;
    $("#v-ph").textContent = ph && ph.valido ? `${ph.valor.toFixed(2)} pH` : (ph ? "inválido" : "—");
    $("#v-ph-info").textContent = ph ? `faixa ${cfg.ph_min}–${cfg.ph_max} · ${atras(ph.ts)}` : "";
    $("#v-ph").parentElement.classList.toggle("fora", !!ph && (!ph.valido || ph.valor < cfg.ph_min || ph.valor > cfg.ph_max));
    $("#v-temp").textContent = temp && temp.valido ? `${temp.valor.toFixed(1)} °C` : (temp ? "inválido" : "—");
    $("#v-temp-info").textContent = temp ? `faixa ${cfg.temp_min}–${cfg.temp_max} °C · ${atras(temp.ts)}` : "";
    $("#v-temp").parentElement.classList.toggle("fora", !!temp && (!temp.valido || temp.valor < cfg.temp_min || temp.valor > cfg.temp_max));

    const s = e.dispositivos["sonda-01"], c = e.dispositivos["ctrl-01"];
    selo($("#on-sonda"), s.online); selo($("#on-ctrl"), c.online);
    const se = s.estado || {};
    dl($("#d-sonda"), [
      ["Último contato", atras(s.ultimo_contato)], ["Estado local", se.estado_local || "—"],
      ["Buzzer silenciado", se.silenciado_s ? `${se.silenciado_s} s` : "não"], ["Firmware", s.fw || "—"],
      ["Wi-Fi", se.rssi_dbm != null ? `${se.rssi_dbm} dBm` : "—"],
    ]);
    const ce = c.estado || {}, at = ce.atuadores || {};
    dl($("#d-ctrl"), [
      ["Último contato", atras(c.ultimo_contato)],
      ["Modo", (ce.modo || "—") + (ce.causa_seguro ? ` (causa: ${ce.causa_seguro})` : "")],
      ["Bomba pH+", at.bomba_ph_mais || "—"], ["Bomba pH−", at.bomba_ph_menos || "—"],
      ["Aquecedor", at.aquecedor === "ON" ? "liberado (termostato)" : at.aquecedor === "OFF" ? "bloqueado" : "—"],
      ["Cooler", at.cooler || "—"], ["Nível", ce.nivel || "—"], ["Firmware", c.fw || "—"],
    ]);

    $("#alertas-ativos").innerHTML = ativos.map((a) =>
      `<div class="alerta ${a.severidade}">⚠️ ${esc(a.mensagem)} <span class="pequeno" style="color:#fff">· ${hora(a.criado_em)}</span></div>`).join("");

    $("#t-comandos").innerHTML = cmds.map((c) => `<tr>
      <td>${hora(c.enviado_em)}</td><td>${esc(c.device_id)}</td><td>${esc(c.acao)}</td>
      <td>${esc(JSON.stringify(c.params))}</td><td>${esc(c.origem)}${c.usuario ? " (" + esc(c.usuario) + ")" : ""}</td>
      <td class="st-${c.status}">${esc(c.status)}${c.codigo ? " · " + esc(c.codigo) : ""}</td>
      <td><button class="secundario" data-reenviar="${c.command_id}" title="Reenvia o mesmo commandId (teste de duplicidade)">↻</button></td>
    </tr>`).join("");
  } catch (err) { console.error(err); }
}

// ---------------- comandos ----------------
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-cmd], button[data-reenviar]");
  if (!b) return;
  b.disabled = true;
  try {
    if (b.dataset.cmd) {
      const c = await api("/api/comandos", { method: "POST", body: b.dataset.cmd });
      $("#msg-cmd").textContent = `Comando ${c.acao} enviado (${c.command_id.slice(0, 8)}…). Acompanhe o estado na tabela.`;
    } else {
      await api(`/api/comandos/${b.dataset.reenviar}/reenviar`, { method: "POST" });
      $("#msg-cmd").textContent = "Mesmo commandId reenviado: o dispositivo deve responder E_DUPLICADO.";
    }
    atualizarRapido();
  } catch (err) { $("#msg-cmd").textContent = "Erro: " + err.message; }
  b.disabled = false;
});

// ---------------- configuração ----------------
async function carregarConfig() {
  const { valores, faixas } = await api("/api/config");
  $("#form-config").innerHTML = Object.keys(valores).map((k) =>
    `<label>${esc(NOMES_CONFIG[k] || k)}<input type="number" step="any" name="${k}" value="${valores[k]}" min="${faixas[k][0]}" max="${faixas[k][1]}"></label>`
  ).join("") + `<button type="submit">Salvar</button>`;
}
$("#form-config").addEventListener("submit", async (e) => {
  e.preventDefault();
  const dados = Object.fromEntries([...new FormData(e.target)].map(([k, v]) => [k, Number(v)]));
  try { await api("/api/config", { method: "PUT", body: JSON.stringify(dados) }); $("#msg-config").textContent = "Configuração salva."; }
  catch (err) { $("#msg-config").textContent = "Erro: " + err.message; }
});

// ---------------- gráficos / indicadores (R14) ----------------
$("#periodo").addEventListener("change", atualizarLento);

function grafico(id, cfg) {
  if (graficos[id]) graficos[id].destroy();
  graficos[id] = new Chart(document.getElementById(id), cfg);
}

function linha(serie, titulo, cor) {
  const labels = serie.pontos.map((p) => new Date(p.ts).toLocaleString("pt-BR", { day: "2-digit", hour: "2-digit", minute: "2-digit" }));
  const n = labels.length;
  return {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: titulo, data: serie.pontos.map((p) => p.media), borderColor: cor, pointRadius: 0, tension: .2 },
        { label: "média móvel 30 min", data: serie.pontos.map((p) => p.media_movel_30min), borderColor: "#888", borderDash: [5, 4], pointRadius: 0 },
        { label: "mín.", data: Array(n).fill(serie.faixa[0]), borderColor: "#c5303066", pointRadius: 0, borderWidth: 1 },
        { label: "máx.", data: Array(n).fill(serie.faixa[1]), borderColor: "#c5303066", pointRadius: 0, borderWidth: 1 },
      ],
    },
    options: { maintainAspectRatio: false, animation: false, plugins: { title: { display: true, text: titulo } } },
  };
}

async function atualizarLento() {
  try {
    const [p, todos] = await Promise.all([api("/api/analitico?periodo=" + $("#periodo").value), api("/api/alertas?limite=30")]);
    const up = p.uptime_pct;
    const ind = [
      ["pH fora da faixa", p.ph.pct_fora_faixa != null ? p.ph.pct_fora_faixa + " %" : "—"],
      ["Temp. fora da faixa", p.temperatura.pct_fora_faixa != null ? p.temperatura.pct_fora_faixa + " %" : "—"],
      ["Doses hoje", (() => { const d = p.doses_por_dia.at(-1); return d ? d.ph_mais + d.ph_menos : 0; })()],
      ["Uptime sonda-01", up["sonda-01"] != null ? up["sonda-01"] + " %" : "—"],
      ["Uptime ctrl-01", up["ctrl-01"] != null ? up["ctrl-01"] + " %" : "—"],
    ];
    $("#indicadores").innerHTML = ind.map(([k, v]) => `<div class="indicador"><span class="pequeno">${k}</span><b>${v}</b></div>`).join("");
    grafico("g-ph", linha(p.ph, "pH", "#0e7c86"));
    grafico("g-temp", linha(p.temperatura, "Temperatura (°C)", "#d98e04"));
    grafico("g-doses", {
      type: "bar",
      data: {
        labels: p.doses_por_dia.map((d) => d.dia.slice(5)),
        datasets: [
          { label: "pH+", data: p.doses_por_dia.map((d) => d.ph_mais), backgroundColor: "#1f9d55" },
          { label: "pH−", data: p.doses_por_dia.map((d) => d.ph_menos), backgroundColor: "#c53030" },
        ],
      },
      options: { maintainAspectRatio: false, animation: false, plugins: { title: { display: true, text: "Doses por dia (7 dias)" } },
        scales: { x: { stacked: true }, y: { stacked: true, ticks: { precision: 0 } } } },
    });
    $("#t-alertas").innerHTML = todos.map((a) => `<tr><td>${hora(a.criado_em)}</td><td>${esc(a.tipo)}</td>
      <td>${esc(a.mensagem)}</td><td>${a.resolvido_em ? hora(a.resolvido_em) : "ativo"}</td></tr>`).join("");
  } catch (err) { console.error(err); }
}

iniciar();
