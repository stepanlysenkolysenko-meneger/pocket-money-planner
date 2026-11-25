import { api } from "./api.js";

const categories = {
  personal: {
    income: ["Кишенькові гроші", "Подарунок", "Підробіток", "Нагорода", "Інше"],
    expense: ["Супермаркети", "Кафе та ресторани", "Аптеки", "Медицина", "Громадський транспорт", "Таксі", "Пальне", "Авто", "Паркування", "Комунальні послуги та зв’язок", "Дім і ремонт", "Одяг і взуття", "Техніка", "Цифрові покупки та підписки", "Ігри", "Розваги", "Спорт і відпочинок", "Освіта та книги", "Краса та догляд", "Домашні тварини", "Подорожі та авіаквитки", "Готелі", "Подарунки", "Страхування", "Перекази та готівка", "Благодійність", "Податки та держпослуги", "Доставка", "Інші покупки"],
  },
  business: {
    income: ["Продажі", "Послуги", "Інвестиції", "Повернення", "Інше"],
    expense: ["Товари та закупівлі", "Оренда", "Реклама і маркетинг", "Податки та збори", "Зарплата", "Логістика та доставка", "Професійні послуги", "Зв’язок і комунальні послуги", "Офіс і техніка", "Транспорт і пальне", "ПЗ та підписки", "Відрядження", "Банківські операції", "Інші бізнес-витрати"],
  },
};
const savedCustomCategories = JSON.parse(localStorage.getItem("pocket-custom-categories-v2") || "null");
let customCategories = savedCustomCategories || { personal: JSON.parse(localStorage.getItem("pocket-custom-categories") || "[]"), business: [] };
const currentCustomCategories = () => customCategories[api.getScope()] || [];
const saveCustomCategories = () => localStorage.setItem("pocket-custom-categories-v2", JSON.stringify(customCategories));
let items = [];
let activeType = "all";
let receiptData = null;
const money = value => `${new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value)} ₴`;
const escapeHtml = text => String(text).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

export function setupTransactions({ refreshAll, notify, loading }) {
  const form = document.querySelector("#transaction-form");
  const list = document.querySelector("#transactions-list");
  const dateInput = document.querySelector("#transaction-date");
  const receiptFile = document.querySelector("#receipt-file");
  let gesture = null;
  let suppressClick = false;
  let submitting = false;
  const pendingDeletes = new Set();
  dateInput.valueAsDate = new Date();
  updateCategoryOptions("income");
  window.addEventListener("scope:changed", () => resetForm());
  window.addEventListener("workspace:changed", () => resetForm());

  receiptFile.addEventListener("change", () => {
    const file = receiptFile.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { receiptFile.value = ""; notify("Фото чека має бути до 2 МБ", true); return; }
    const reader = new FileReader();
    reader.onload = async () => {
      setReceipt(reader.result);
      const status = document.querySelector("#receipt-ocr-status");
      status.textContent = "⏳ Читаю суму з чека…";
      try {
        const aiStatus = await api.getAiStatus();
        const result = aiStatus.configured ? await api.aiReceipt(reader.result) : await api.readReceipt(reader.result);
        if (result.amount) {
          document.querySelector("#amount").value = result.amount.toFixed(2);
          if (aiStatus.configured) {
            document.querySelector("input[name='type'][value='expense']").checked = true;
            const category = result.category || "Інше";
            const custom = currentCustomCategories();
            if (!categories[api.getScope()].expense.includes(category) && !custom.includes(category)) {
              custom.push(category);
              saveCustomCategories();
            }
            updateCategoryOptions("expense", category);
            document.querySelector("#description").value = result.description || result.merchant || "Покупка за чеком";
            if (result.date) document.querySelector("#transaction-date").value = result.date;
            status.textContent = `✓ AI: ${money(result.amount)}${result.currency ? ` · ${result.currency}` : ""}${result.language ? ` · ${result.language}` : ""}`;
            notify("AI прочитав чек і заповнив операцію");
          } else {
            status.textContent = `✓ Знайдено суму: ${money(result.amount)}`;
            notify("Суму з чека підставлено автоматично");
          }
        } else status.textContent = "Суму не знайдено — введи її вручну";
      } catch (error) {
        try {
          const fallback = await api.readReceipt(reader.result);
          if (fallback.amount) { document.querySelector("#amount").value = fallback.amount.toFixed(2); status.textContent = `Локальний OCR: ${money(fallback.amount)}`; }
          else status.textContent = "Суму не знайдено — введи її вручну";
        } catch (_) { status.textContent = "Не вдалося прочитати суму — введи її вручну"; }
      }
    };
    reader.readAsDataURL(file);
  });
  document.querySelector("#remove-receipt").addEventListener("click", () => setReceipt(null));
  document.querySelector("#category").addEventListener("change", toggleCustomCategory);

  document.querySelectorAll("input[name='type']").forEach(radio => radio.addEventListener("change", () => updateCategoryOptions(radio.value)));
  document.querySelectorAll(".filter-tabs button").forEach(button => button.addEventListener("click", () => {
    activeType = button.dataset.filter;
    document.querySelectorAll(".filter-tabs button").forEach(x => x.classList.toggle("active", x === button));
    renderTransactions();
  }));
  ["search", "category-filter", "sort"].forEach(id => document.querySelector(`#${id}`).addEventListener("input", renderTransactions));
  document.querySelector("#clear-filters").addEventListener("click", clearFilters);
  document.querySelector("#cancel-transaction").addEventListener("click", resetForm);
  list.addEventListener("click", async event => {
    if (suppressClick) { suppressClick = false; event.preventDefault(); return; }
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const item = items.find(x => x.id === Number(button.dataset.id));
    if (button.dataset.action === "receipt" && item?.receipt_data) {
      document.querySelector("#receipt-full").src = item.receipt_data;
      document.querySelector("#receipt-modal").classList.remove("hidden");
      return;
    }
    await handleRowAction(button.dataset.action, item);
  });
  list.addEventListener("pointerdown", event => {
    if (event.target.closest("button") || event.button > 0) return;
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    gesture = { row, id: Number(row.dataset.id), pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, dx: 0, dragging: false };
  });
  list.addEventListener("pointermove", event => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const dx = event.clientX - gesture.startX;
    const dy = event.clientY - gesture.startY;
    if (!gesture.dragging && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) {
      gesture.dragging = true;
      gesture.row.setPointerCapture(event.pointerId);
    }
    if (!gesture.dragging) return;
    event.preventDefault();
    gesture.dx = Math.max(-115, Math.min(115, dx));
    gesture.row.style.transform = `translateX(${gesture.dx}px)`;
    gesture.row.classList.toggle("swipe-edit", gesture.dx > 0);
    gesture.row.classList.toggle("swipe-delete", gesture.dx < 0);
  });
  const finishGesture = async event => {
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const current = gesture;
    gesture = null;
    current.row.style.transform = "";
    current.row.classList.remove("swipe-edit", "swipe-delete");
    if (!current.dragging) return;
    suppressClick = true;
    const item = items.find(x => x.id === current.id);
    if (!item || Math.abs(current.dx) < 70) return;
    await handleRowAction(current.dx > 0 ? "edit" : "delete", item);
  };
  list.addEventListener("pointerup", finishGesture);
  list.addEventListener("pointercancel", finishGesture);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    const data = {
      type: form.elements.type.value,
      amount: Number(document.querySelector("#amount").value),
      category: document.querySelector("#category").value === "__custom__" ? document.querySelector("#custom-category").value.trim() : document.querySelector("#category").value,
      description: document.querySelector("#description").value.trim(),
      date: dateInput.value,
      receipt_data: receiptData,
    };
    const error = validate(data);
    document.querySelector("#transaction-error").textContent = error;
    if (error) return;
    submitting = true;
    const submitButton = form.querySelector("button[type='submit']");
    submitButton.disabled = true;
    try {
      const custom = currentCustomCategories();
      if (document.querySelector("#category").value === "__custom__" && !custom.includes(data.category)) {
        custom.push(data.category);
        customCategories[api.getScope()] = [...new Set(custom)].sort((a, b) => a.localeCompare(b, "uk"));
        saveCustomCategories();
      }
      const id = document.querySelector("#transaction-id").value;
      await run(async () => {
        if (data.type === "expense") {
          const limits = await api.getLimits();
          const limit = limits.find(item => item.category === data.category);
          if (limit) {
            const month = data.date.slice(0, 7);
            const currentId = Number(id) || null;
            const alreadySpent = items
              .filter(item => item.type === "expense" && item.category === data.category && item.date.startsWith(month) && item.id !== currentId)
              .reduce((sum, item) => sum + Number(item.amount), 0);
            const projected = alreadySpent + data.amount;
            if (projected > Number(limit.amount)) {
              const increase = confirm(
                `Ліміт «${data.category}» — ${money(limit.amount)}. Після цієї операції витрати становитимуть ${money(projected)}.\n\nЗбільшити ліміт до ${money(projected)} і додати операцію?\nНатисни «Скасувати», щоб не записувати витрату.`
              );
              if (!increase) {
                notify("Операцію скасовано: ліміт не перевищено");
                return;
              }
              await api.saveLimit({ category: data.category, amount: projected });
              notify(`Ліміт «${data.category}» збільшено до ${money(projected)}`);
            }
          }
        }
        if (id) await api.updateTransaction(id, data); else await api.createTransaction(data);
        if (!id && data.type === "income") window.dispatchEvent(new CustomEvent("money:income", { detail: { amount: data.amount } }));
        if (!id && data.type === "expense") window.dispatchEvent(new CustomEvent("money:expense", { detail: { amount: data.amount } }));
        notify(id ? "Операцію оновлено" : "Операцію додано"); resetForm(); await refreshAll();
      });
    } finally {
      submitting = false;
      submitButton.disabled = false;
    }
  });
  async function run(action) { loading(true); try { await action(); } catch (error) { notify(error.message, true); } finally { loading(false); } }
  async function handleRowAction(action, item) {
    if (!item || pendingDeletes.has(item.id)) return;
    if (action === "edit") fillForm(item);
    if (action === "delete" && !pendingDeletes.has(item.id)) {
      pendingDeletes.add(item.id);
      try {
        if (confirm(`Видалити «${item.description}»?`)) {
          await run(async () => { await api.deleteTransaction(item.id); notify("Операцію видалено"); await refreshAll(); });
        }
      } finally {
        pendingDeletes.delete(item.id);
      }
    }
  }
}

function validate(data) {
  if (!data.amount || data.amount <= 0) return "Вкажи суму, більшу за нуль.";
  if (!data.category) return "Обери категорію.";
  if (!data.description) return "Додай короткий опис.";
  if (!data.date) return "Обери дату.";
  return "";
}
function updateCategoryOptions(type, selected = "") {
  const custom = currentCustomCategories();
  const all = [...new Set([...categories[api.getScope()][type], ...custom])];
  if (selected && !all.includes(selected)) {
    custom.push(selected);
    saveCustomCategories();
    all.push(selected);
  }
  document.querySelector("#category").innerHTML = `<option value="">Обери категорію</option>${all.map(x => `<option value="${escapeHtml(x)}" ${x === selected ? "selected" : ""}>${escapeHtml(x)}</option>`).join("")}<option value="__custom__">＋ Написати свою категорію…</option>`;
  toggleCustomCategory();
}

function toggleCustomCategory() {
  const custom = document.querySelector("#category").value === "__custom__";
  document.querySelector("#custom-category-label").classList.toggle("hidden", !custom);
  if (custom) document.querySelector("#custom-category").focus();
  else document.querySelector("#custom-category").value = "";
}
function fillForm(item) {
  document.querySelector("#transaction-id").value = item.id;
  const radio = document.querySelector(`input[name='type'][value='${item.type}']`); radio.checked = true;
  updateCategoryOptions(item.type, item.category);
  document.querySelector("#amount").value = item.amount;
  document.querySelector("#description").value = item.description;
  document.querySelector("#transaction-date").value = item.date;
  setReceipt(item.receipt_data || null);
  document.querySelector("#transaction-form-title").textContent = "Редагування операції";
  document.querySelector("#transaction-form button[type='submit']").textContent = "Зберегти зміни";
  document.querySelector("#cancel-transaction").classList.remove("hidden");
  document.querySelector("#transaction-form").scrollIntoView({ behavior: "smooth", block: "center" });
}
function resetForm() {
  const form = document.querySelector("#transaction-form"); form.reset();
  document.querySelector("#transaction-id").value = "";
  document.querySelector("#transaction-date").valueAsDate = new Date();
  document.querySelector("input[value='income']").checked = true; updateCategoryOptions("income");
  document.querySelector("#transaction-form-title").textContent = "Нова операція";
  form.querySelector("button[type='submit']").textContent = "Додати операцію";
  document.querySelector("#cancel-transaction").classList.add("hidden");
  document.querySelector("#transaction-error").textContent = "";
  setReceipt(null);
}

function setReceipt(value) {
  receiptData = value;
  const wrap = document.querySelector("#receipt-preview-wrap");
  const preview = document.querySelector("#receipt-preview");
  document.querySelector("#receipt-file").value = "";
  wrap.classList.toggle("hidden", !value);
  preview.src = value || "";
  if (!value) document.querySelector("#receipt-ocr-status").textContent = "";
}
function clearFilters() {
  activeType = "all"; document.querySelector("#search").value = ""; document.querySelector("#category-filter").value = ""; document.querySelector("#sort").value = "desc";
  document.querySelectorAll(".filter-tabs button").forEach(x => x.classList.toggle("active", x.dataset.filter === "all")); renderTransactions();
}
export function setTransactions(data) {
  items = data;
  const allCategories = [...new Set(data.map(x => x.category))].sort();
  document.querySelector("#category-filter").innerHTML = `<option value="">Усі категорії</option>${allCategories.map(x => `<option>${escapeHtml(x)}</option>`).join("")}`;
  renderTransactions();
}
function renderTransactions() {
  const search = document.querySelector("#search").value.toLowerCase(); const category = document.querySelector("#category-filter").value; const direction = document.querySelector("#sort").value;
  const filtered = items.filter(x => (activeType === "all" || x.type === activeType) && (!category || x.category === category) && x.description.toLowerCase().includes(search)).sort((a,b) => direction === "desc" ? b.date.localeCompare(a.date) : a.date.localeCompare(b.date));
  document.querySelector("#visible-count").textContent = filtered.length;
  document.querySelector("#transactions-empty").classList.toggle("hidden", filtered.length > 0);
  document.querySelector("#transactions-list").innerHTML = filtered.map(item => `<tr data-id="${item.id}"><td><div class="transaction-name"><span class="transaction-dot ${item.type}">${item.type === "income" ? "↗" : "↘"}</span><div><b>${escapeHtml(item.description)}</b><small>${item.type === "income" ? "Дохід" : "Витрата"}${item.workspace_name ? ` · ${api.getScope() === "business" ? "💼" : "🏠"} ${escapeHtml(item.workspace_name)}` : ""}${item.bank_account_name ? ` · 💳 ${escapeHtml(item.bank_account_name)}` : ""}${item.receipt_data ? " · 📷 чек" : ""}</small></div></div></td><td>${escapeHtml(item.category)}</td><td>${new Date(`${item.date}T00:00:00`).toLocaleDateString("uk-UA")}</td><td class="${item.type === "income" ? "amount-income" : "amount-expense"}">${item.type === "income" ? "+" : "−"}${money(item.amount)}</td><td class="row-actions">${item.receipt_data ? `<button data-action="receipt" data-id="${item.id}" title="Переглянути чек">📷</button>` : ""}<button data-action="edit" data-id="${item.id}" title="Редагувати">✎</button><button data-action="delete" data-id="${item.id}" title="Видалити">×</button></td></tr>`).join("");
}
