import { api } from "./api.js";

const expenseCategories = {
  personal: ["Супермаркети", "Кафе та ресторани", "Аптеки", "Медицина", "Громадський транспорт", "Таксі", "Пальне", "Авто", "Комунальні послуги та зв’язок", "Дім і ремонт", "Одяг і взуття", "Техніка", "Цифрові покупки та підписки", "Ігри", "Розваги", "Спорт і відпочинок", "Освіта та книги", "Краса та догляд", "Подорожі та авіаквитки", "Готелі", "Подарунки", "Страхування", "Перекази та готівка", "Благодійність", "Податки та держпослуги", "Доставка", "Інші покупки"],
  business: ["Товари та закупівлі", "Оренда", "Реклама і маркетинг", "Податки та збори", "Зарплата", "Логістика та доставка", "Професійні послуги", "Зв’язок і комунальні послуги", "Офіс і техніка", "Транспорт і пальне", "ПЗ та підписки", "Відрядження", "Банківські операції", "Інші бізнес-витрати"],
};
const money = value => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ₴`;
let snapshot = { transactions: [], summary: {}, limits: [] };
let notifyUser = () => {};
let refreshApp = async () => {};
let aiConfigured = false;
let originalUi = null;
let authenticated = false;
let featureStateGeneration = 0;
let chatHistoryGeneration = 0;

export async function setupFeatures({ notify, refreshAll }) {
  notifyUser = notify;
  refreshApp = refreshAll;
  const limitCategory = document.querySelector("#limit-category");
  const chat = document.querySelector("#assistant-chat");
  const welcomeMessage = chat.textContent.trim();
  let savingLimit = false;
  const pendingLimitDeletes = new Set();
  const renderLimitCategories = () => { limitCategory.innerHTML = expenseCategories[api.getScope()].map(category => `<option>${category}</option>`).join(""); };
  const loadChatHistory = async () => {
    if (!authenticated) return;
    const generation = ++chatHistoryGeneration;
    try {
      const history = await api.getAiHistory();
      if (!authenticated || generation !== chatHistoryGeneration) return;
      chat.innerHTML = "";
      if (history.length) history.forEach(item => addMessage(item.content, item.role === "user" ? "user" : "assistant"));
      else addMessage(api.getScope() === "business" ? "Привіт! Я допоможу вести бізнес-доходи, витрати, ліміти та цілі окремо від побуту." : welcomeMessage, "assistant");
    } catch (_) { /* Історія завантажиться після наступного запиту. */ }
  };
  renderLimitCategories();
  window.addEventListener("scope:changed", () => { renderLimitCategories(); if (authenticated) loadChatHistory(); });
  const loadAuthenticatedState = async () => {
    const generation = ++featureStateGeneration;
    try {
      const status = await api.getAiStatus();
      if (!authenticated || generation !== featureStateGeneration) return;
      aiConfigured = status.configured;
      updateAiStatus(status.model);
    } catch (_) {
      if (!authenticated || generation !== featureStateGeneration) return;
      updateAiStatus();
    }
    await loadChatHistory();
  };
  window.addEventListener("auth:ready", event => {
    authenticated = event.detail.authenticated;
    if (authenticated) loadAuthenticatedState();
  });
  window.addEventListener("auth:login", () => {
    authenticated = true;
    loadAuthenticatedState();
  });
  window.addEventListener("auth:logout", () => {
    authenticated = false;
    featureStateGeneration += 1;
    chatHistoryGeneration += 1;
  });

  document.querySelector("#limits-button").addEventListener("click", async () => {
    if (!authenticated) return;
    document.querySelector("#limits-modal").classList.remove("hidden");
    try {
      await refreshLimits();
    } catch (error) {
      notify(error.message, true);
    }
  });
  document.querySelector("#assistant-button").addEventListener("click", () => document.querySelector("#assistant-modal").classList.remove("hidden"));
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`).classList.add("hidden")));
  document.querySelectorAll(".feature-modal").forEach(modal => modal.addEventListener("click", event => { if (event.target === modal) modal.classList.add("hidden"); }));

  document.querySelector("#limit-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!authenticated || savingLimit) return;
    savingLimit = true;
    const submitButton = event.currentTarget.querySelector("button[type='submit']");
    submitButton.disabled = true;
    try {
      await api.saveLimit({ category: limitCategory.value, amount: Number(document.querySelector("#limit-amount").value) });
      document.querySelector("#limit-amount").value = "";
      await refreshLimits();
      notify("Ліміт збережено");
    } catch (error) { notify(error.message, true); }
    finally {
      savingLimit = false;
      submitButton.disabled = false;
    }
  });
  document.querySelector("#limits-list").addEventListener("click", async event => {
    const button = event.target.closest("button[data-limit-id]");
    const id = Number(button?.dataset.limitId);
    if (!authenticated || !id || pendingLimitDeletes.has(id) || !confirm("Видалити цей ліміт?")) return;
    pendingLimitDeletes.add(id);
    try {
      await api.deleteLimit(id);
      await refreshLimits();
    } catch (error) {
      notify(error.message, true);
    } finally {
      pendingLimitDeletes.delete(id);
    }
  });

  document.querySelector("#assistant-form").addEventListener("submit", event => {
    event.preventDefault();
    const input = document.querySelector("#assistant-input");
    askAssistant(input.value);
    input.value = "";
  });
  document.querySelectorAll(".assistant-suggestions button").forEach(button => button.addEventListener("click", () => askAssistant(button.textContent)));
  document.querySelector("#language-select").addEventListener("change", changeLanguage);
}

export async function setFeatureData(transactions, summary) {
  snapshot.transactions = transactions;
  snapshot.summary = summary;
  try { snapshot.limits = await api.getLimits(); renderLimits(); checkLimits(); } catch (_) { /* Наступне оновлення повторить запит. */ }
}

async function refreshLimits() {
  snapshot.limits = await api.getLimits();
  renderLimits();
}

function monthExpenses() {
  const month = new Date().toISOString().slice(0, 7);
  return snapshot.transactions.filter(item => item.type === "expense" && item.date.startsWith(month));
}

function renderLimits() {
  const expenses = monthExpenses();
  document.querySelector("#limits-list").innerHTML = snapshot.limits.length ? snapshot.limits.map(limit => {
    const spent = expenses.filter(item => item.category === limit.category).reduce((sum, item) => sum + Number(item.amount), 0);
    const percent = Math.min(100, Math.round(spent / Number(limit.amount) * 100));
    return `<article class="limit-item"><div><strong>${limit.category}</strong><span>${money(spent)} із ${money(limit.amount)}</span></div><button data-limit-id="${limit.id}" type="button">×</button><progress max="100" value="${percent}"></progress></article>`;
  }).join("") : '<p class="modal-copy">Лімітів ще немає.</p>';
}

function checkLimits() {
  const expenses = monthExpenses();
  snapshot.limits.forEach(limit => {
    const spent = expenses.filter(item => item.category === limit.category).reduce((sum, item) => sum + Number(item.amount), 0);
    if (spent >= Number(limit.amount)) notifyUser(`Ліміт «${limit.category}» вичерпано: ${money(spent)}`, true);
    else if (spent >= Number(limit.amount) * .8) notifyUser(`Використано понад 80% ліміту «${limit.category}»`);
  });
}

async function askAssistant(question) {
  const clean = question.trim();
  if (!clean) return;
  addMessage(clean, "user");
  if (!aiConfigured) {
    addMessage("OpenRouter не підключено. Додай OPENROUTER_API_KEY у файл %LOCALAPPDATA%\\PocketMoney\\.env і перезапусти програму.", "assistant");
    return;
  }
  const pending = addMessage("Думаю…", "assistant");
  try {
    const result = await api.aiChat(clean);
    pending.textContent = result.reply;
    if (result.changed) await refreshApp();
  } catch (error) { pending.textContent = `Помилка: ${error.message}`; }
}

function offlineAnswer(question) {
  const clean = question.trim();
  const lower = clean.toLowerCase();
  const expenses = monthExpenses();
  const monthSpent = expenses.reduce((sum, item) => sum + Number(item.amount), 0);
  const byCategory = expenses.reduce((result, item) => ({ ...result, [item.category]: (result[item.category] || 0) + Number(item.amount) }), {});
  const top = Object.entries(byCategory).sort((a, b) => b[1] - a[1])[0];
  let answer;
  if (/баланс|залиш/.test(lower)) answer = `Твій поточний баланс: ${money(snapshot.summary.balance)}.`;
  else if (/найбільш|найбільше|категор/.test(lower)) answer = top ? `Цього місяця найбільше пішло на «${top[0]}» — ${money(top[1])}.` : "Цього місяця витрат ще немає.";
  else if (/місяц|витратив|витрати/.test(lower)) answer = `Цього місяця ти витратив ${money(monthSpent)} у ${expenses.length} операціях.`;
  else if (/економ|заощад|порад/.test(lower)) answer = top ? `Спробуй зменшити витрати в категорії «${top[0]}» на 10%. Це збереже приблизно ${money(top[1] * .1)} на місяць.` : "Спочатку додай кілька витрат — тоді я дам персональну пораду.";
  else if (/ліміт/.test(lower)) answer = snapshot.limits.length ? `У тебе встановлено ${snapshot.limits.length} місячних лімітів. Відкрий «Ліміти», щоб побачити прогрес.` : "Лімітів ще немає. Натисни кнопку «Ліміти» угорі.";
  else answer = "Я можу розповісти про баланс, витрати за місяць, найбільшу категорію, ліміти або запропонувати спосіб заощадити.";
  return answer;
}

function addMessage(text, type) {
  const chat = document.querySelector("#assistant-chat");
  const message = document.createElement("div");
  message.className = `assistant-message ${type}`;
  message.textContent = text;
  chat.append(message);
  chat.scrollTop = chat.scrollHeight;
  return message;
}

function updateAiStatus(model = "openai/gpt-4o-mini") {
  document.querySelector("#assistant-button").classList.toggle("ai-ready", aiConfigured);
  document.querySelector("#assistant-button").title = aiConfigured ? `OpenRouter: ${model}` : "OpenRouter не налаштовано у .env";
}

async function changeLanguage(event) {
  let language = event.target.value;
  if (language === "custom") {
    language = prompt("Напиши назву мови, наприклад Türkçe або العربية:");
    if (!language) { event.target.value = "uk"; return; }
  }
  if (!originalUi) originalUi = collectUiStrings();
  if (language === "uk") { restoreUiStrings(); return; }
  if (!aiConfigured) { notifyUser("Додай OPENROUTER_API_KEY у локальний .env і перезапусти програму", true); event.target.value = "uk"; return; }
  const source = originalUi.map(item => item.original);
  const cacheKey = `pocket-ui-translation:${language.toLocaleLowerCase()}`;
  let translations;
  try {
    const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
    if (cached?.source === JSON.stringify(source) && cached.translations?.length === source.length) {
      translations = cached.translations;
    }
  } catch (_) { /* Пошкоджений кеш буде замінено новим. */ }
  notifyUser(translations ? `Застосовую мову: ${language}` : `Швидко перекладаю інтерфейс: ${language}…`);
  try {
    if (!translations) {
      const chunks = [];
      for (let index = 0; index < source.length; index += 60) chunks.push(source.slice(index, index + 60));
      const results = await Promise.all(chunks.map(chunk => api.translateUi(language, chunk)));
      translations = results.flatMap(result => result.translations);
      localStorage.setItem(cacheKey, JSON.stringify({ source: JSON.stringify(source), translations }));
    }
    originalUi.forEach((item, index) => { if (item.kind === "text") item.node.textContent = translations[index]; else item.node.setAttribute(item.kind, translations[index]); });
    localStorage.setItem("pocket-language", language);
    notifyUser(`Мову змінено: ${language}`);
  } catch (error) { notifyUser(error.message, true); }
}

function collectUiStrings() {
  const items = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let textNode;
  while ((textNode = walker.nextNode())) {
    const parent = textNode.parentElement;
    const value = textNode.textContent.trim();
    if (!value || parent.closest("script,style,canvas,#assistant-chat,#transactions-list,#goals-list,#toast") || (parent.tagName === "OPTION" && !parent.hasAttribute("value")) || /^[-+−\d\s.,₴%]+$/.test(value)) continue;
    items.push({ node: textNode, kind: "text", original: textNode.textContent });
  }
  document.querySelectorAll("body *").forEach(node => {
    ["placeholder", "title", "aria-label"].forEach(kind => { const value = node.getAttribute?.(kind); if (value) items.push({ node, kind, original: value }); });
  });
  return items.slice(0, 250);
}

function restoreUiStrings() {
  originalUi?.forEach(item => { if (item.kind === "text") item.node.textContent = item.original; else item.node.setAttribute(item.kind, item.original); });
  localStorage.setItem("pocket-language", "uk");
}
