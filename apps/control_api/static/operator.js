"use strict";

const $ = (id) => document.getElementById(id);
const state = { history: [] };

const ACTIONS = {
  observe: "Наблюдать",
  hold: "Удерживать",
  open: "Открыть позицию",
  close: "Закрыть позицию",
  reduce: "Сократить позицию",
  rebalance: "Перебалансировать",
  block: "Заблокировать действие",
};

function number(value, digits = 4) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("ru-RU", { maximumFractionDigits: digits }) : "Нет данных";
}

function money(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "Нет данных";
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${parsed.toLocaleString("ru-RU", { minimumFractionDigits: 4, maximumFractionDigits: 4 })} USDT`;
}

function dateTime(value) {
  if (!value) return "Нет данных";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Нет данных" : date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function renderRuntime(carry, scanner) {
  const observer = carry.last_status || {};
  const performance = carry.performance || {};
  const performanceValues = performance.performance || {};
  const funding = performance.funding || {};
  const alerts = carry.alerts || {};
  const alertDecision = alerts.decision || {};
  const activeAlerts = alertDecision.alerts || [];
  const automatic = Boolean(carry.orders_enabled || scanner.automatic_actions_enabled);

  $("safety-badge").textContent = automatic ? "Автодействия включены" : "Автодействия выключены";
  $("safety-badge").classList.toggle("on", automatic);

  let title = "Наблюдать";
  let summary = "Стратегия собирает данные. Оснований для изменения позиции сейчас нет.";
  let indicator = "ok";
  if (alertDecision.state === "action_required") {
    title = "Требуется решение";
    summary = activeAlerts[0]?.message || "Защитные проверки обнаружили состояние, требующее внимания.";
    indicator = "risk";
  } else if (activeAlerts.length) {
    title = "Обратить внимание";
    summary = activeAlerts.map((item) => item.message).join(" ");
    indicator = "";
  }
  $("current-decision-title").textContent = title;
  $("current-decision-summary").textContent = summary;
  $("decision-indicator").className = `decision-indicator ${indicator}`;
  $("position-phase").textContent = observer.status || "Нет данных";
  $("last-updated").textContent = dateTime(performance.updated_at || observer.updated_at);
  $("net-pnl").textContent = money(performanceValues.estimated_net_pnl_usdt);
  $("funding-income").textContent = money(funding.income_usdt);
  $("funding-count").textContent = `${funding.settlement_count || 0} выплат`;
  const guard = observer.guard || {};
  $("position-delta").textContent = number(guard.coin_delta, 8);

  const windowData = scanner.window || {};
  const eligibleSymbols = (scanner.symbols || []).filter((item) => Number(item.eligible_count) > 0).length;
  $("eligible-count").textContent = number(eligibleSymbols, 0);
  $("scan-count").textContent = `${windowData.run_count || 0} запусков за 24 часа`;
}

function createDecisionItem(record) {
  const payload = record.payload || {};
  const decision = payload.decision || {};
  const analysis = payload.analysis || {};
  const execution = payload.execution || {};
  const action = decision.action || "observe";
  const item = document.createElement("article");
  item.className = "decision-item";

  const badge = document.createElement("span");
  badge.className = `action-badge ${["close", "reduce", "block"].includes(action) ? "risk" : ["observe", "hold"].includes(action) ? "wait" : ""}`;
  badge.textContent = ACTIONS[action] || action;
  item.appendChild(badge);

  const head = document.createElement("div");
  head.className = "item-head";
  const title = document.createElement("strong");
  title.textContent = `${record.instrument || "Инструмент не указан"} · ${record.strategy || "Стратегия"}`;
  const time = document.createElement("time");
  time.textContent = dateTime(record.ts_event);
  head.append(title, time);
  item.appendChild(head);

  const summary = document.createElement("p");
  summary.className = "item-summary";
  const confidence = Number(decision.confidence);
  const confidenceText = Number.isFinite(confidence) ? ` Уверенность: ${(confidence * 100).toFixed(0)}%.` : "";
  summary.textContent = `${decision.summary || record.rationale || "Причина не записана."}${confidenceText}`;
  item.appendChild(summary);

  if (analysis.news_summary) {
    const block = document.createElement("div");
    block.className = "analysis-block";
    const label = document.createElement("span");
    label.textContent = "Новостной вывод";
    const text = document.createElement("p");
    text.textContent = analysis.news_summary;
    block.append(label, text);
    item.appendChild(block);
  }

  const executionBlock = document.createElement("div");
  executionBlock.className = "analysis-block";
  const executionLabel = document.createElement("span");
  executionLabel.textContent = "Исполнение";
  const executionText = document.createElement("p");
  executionText.textContent = `${execution.status || "not_requested"} · автоматический режим ${execution.automatic ? "включён" : "выключен"}`;
  executionBlock.append(executionLabel, executionText);
  item.appendChild(executionBlock);
  return item;
}

function renderDecisions(payload) {
  const decisions = payload.decisions || [];
  $("decision-count").textContent = String(decisions.length);
  const feed = $("decision-feed");
  feed.replaceChildren();
  if (!decisions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Алгоритмические решения пока не записывались. Текущий режим только наблюдает рынок.";
    feed.appendChild(empty);
    return;
  }
  decisions.forEach((record) => feed.appendChild(createDecisionItem(record)));
}

function createNewsItem(item) {
  const analysis = item.analysis;
  const direction = Number(analysis?.direction || 0);
  const article = document.createElement("article");
  const imageUrl = safeUrl(item.image_url);
  article.className = `news-item ${imageUrl ? "" : "no-image"}`;
  if (imageUrl) {
    const image = document.createElement("img");
    image.className = "news-image";
    image.src = imageUrl;
    image.alt = "";
    image.loading = "lazy";
    article.appendChild(image);
  }

  const body = document.createElement("div");
  body.className = "news-body";
  const heading = document.createElement("div");
  heading.className = "news-heading";
  const link = document.createElement("a");
  const articleUrl = safeUrl(item.article_url);
  link.href = articleUrl || "#";
  link.target = articleUrl ? "_blank" : "";
  link.rel = articleUrl ? "noreferrer" : "";
  link.textContent = item.title || "Без заголовка";
  const tone = document.createElement("span");
  tone.className = `tone ${direction > 0.05 ? "positive" : direction < -0.05 ? "negative" : ""}`;
  heading.append(link, tone);

  const meta = document.createElement("div");
  meta.className = "news-meta";
  meta.textContent = `${item.source || "Источник не указан"} · ${dateTime(item.published_at)}`;
  const summary = document.createElement("p");
  summary.className = "news-summary";
  summary.textContent = analysis?.summary || item.excerpt || "Новость ожидает анализа.";
  body.append(heading, meta, summary);

  const tags = document.createElement("div");
  tags.className = "tag-row";
  if (analysis) {
    const assets = analysis.assets || [];
    [...assets.slice(0, 4), `${Math.round(Number(analysis.confidence || 0) * 100)}% уверенность`].forEach((value) => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = value;
      tags.appendChild(tag);
    });
  } else {
    const tag = document.createElement("span");
    tag.className = "tag pending";
    tag.textContent = "Ожидает 14B";
    tags.appendChild(tag);
  }
  body.appendChild(tags);
  article.appendChild(body);
  return article;
}

function renderNews(payload) {
  const items = payload.items || [];
  $("news-count").textContent = String(items.length);
  const feed = $("news-feed");
  feed.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Новости пока не собраны.";
    feed.appendChild(empty);
    return;
  }
  items.forEach((item) => feed.appendChild(createNewsItem(item)));
}

function drawChart(observations) {
  state.history = observations || [];
  const canvas = $("carry-chart");
  const empty = $("chart-empty");
  if (state.history.length < 2) {
    empty.style.display = "grid";
    return;
  }
  empty.style.display = "none";
  const values = [...state.history].reverse().map((item) => Number(item.estimated_net_usdt)).filter(Number.isFinite);
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * scale));
  canvas.height = Math.max(1, Math.floor(rect.height * scale));
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  const width = rect.width;
  const height = rect.height;
  const padding = { left: 52, right: 18, top: 18, bottom: 28 };
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const spread = max - min || 1;
  const x = (index) => padding.left + index * ((width - padding.left - padding.right) / Math.max(1, values.length - 1));
  const y = (value) => padding.top + (max - value) * ((height - padding.top - padding.bottom) / spread);

  context.strokeStyle = "#d9dfdc";
  context.lineWidth = 1;
  [min, 0, max].forEach((value) => {
    context.beginPath();
    context.moveTo(padding.left, y(value));
    context.lineTo(width - padding.right, y(value));
    context.stroke();
  });
  context.fillStyle = "#68726d";
  context.font = "10px system-ui";
  context.fillText(number(max, 3), 7, y(max) + 4);
  context.fillText(number(min, 3), 7, y(min) + 4);

  context.beginPath();
  values.forEach((value, index) => index ? context.lineTo(x(index), y(value)) : context.moveTo(x(index), y(value)));
  context.strokeStyle = values.at(-1) >= 0 ? "#087a55" : "#b43a43";
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = context.strokeStyle;
  context.beginPath();
  context.arc(x(values.length - 1), y(values.at(-1)), 3.5, 0, Math.PI * 2);
  context.fill();
  $("chart-range").textContent = `${values.length} наблюдений · сейчас ${money(values.at(-1))}`;
}

async function refresh() {
  const button = $("refresh-button");
  button.disabled = true;
  $("connection-status").textContent = "Обновление данных...";
  const requests = await Promise.allSettled([
    getJson("/runtime/carry"),
    getJson("/runtime/carry-scanner/summary?hours=24"),
    getJson("/runtime/carry-scanner/history?symbol=BTCUSDT&limit=96"),
    getJson("/operator/api/decisions?limit=30"),
    getJson("/operator/api/news?limit=30"),
  ]);
  const [carry, scanner, history, decisions, news] = requests.map((result) => result.status === "fulfilled" ? result.value : null);
  if (carry && scanner) renderRuntime(carry, scanner);
  if (history) drawChart(history.observations || []);
  if (decisions) renderDecisions(decisions);
  if (news) renderNews(news);
  const failed = requests.filter((result) => result.status === "rejected").length;
  $("connection-status").textContent = failed ? `Часть данных недоступна: ${failed} источника` : "Все источники доступны";
  $("refresh-time").textContent = `Обновлено ${new Date().toLocaleTimeString("ru-RU")}`;
  button.disabled = false;
}

$("refresh-button").addEventListener("click", refresh);
window.addEventListener("resize", () => drawChart(state.history));
refresh();
window.setInterval(refresh, 30000);
