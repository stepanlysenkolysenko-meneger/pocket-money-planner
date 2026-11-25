import { api } from "./api.js";

const money = value => `${new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Number(value) || 0)} ₴`;
const escapeHtml = text => String(text || "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const monthLabel = value => new Date(`${value}-01T00:00:00`).toLocaleDateString("uk-UA", { month: "long", year: "numeric" });

export function setupReports({ notify, loading }) {
  const modal = document.querySelector("#reports-modal");
  const monthInput = document.querySelector("#report-month");
  const scopeSelect = document.querySelector("#report-scope");
  const workspaceSelect = document.querySelector("#report-workspace");
  const content = document.querySelector("#report-content");
  const banner = document.querySelector("#monthly-report-banner");
  let currentReport = null;

  const now = new Date();
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const previousKey = `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, "0")}`;
  monthInput.value = previousKey;

  const filters = () => {
    const [year, month] = monthInput.value.split("-").map(Number);
    return { year, month, scope: scopeSelect.value, workspace_id: Number(workspaceSelect.value) || null };
  };

  const loadWorkspaceOptions = async selectedId => {
    if (scopeSelect.value === "all") {
      workspaceSelect.innerHTML = '<option value="">Усі профілі</option>';
      workspaceSelect.disabled = true;
      return;
    }
    const rows = await api.getWorkspaces(scopeSelect.value);
    workspaceSelect.disabled = false;
    workspaceSelect.innerHTML = `<option value="">Усі ${scopeSelect.value === "business" ? "бізнеси" : "побутові профілі"}</option>${rows.map(row => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join("")}`;
    workspaceSelect.value = selectedId || "";
  };

  const rowsHtml = (rows, labelKey) => rows.length ? rows.map(row => `<div class="report-row"><span>${escapeHtml(row[labelKey])}</span><small>дохід ${money(row.income)} · витрати ${money(row.expense)}</small><b class="${row.balance >= 0 ? "report-positive" : "report-negative"}">${money(row.balance)}</b></div>`).join("") : '<div class="bank-empty"><span>Немає даних за цей місяць</span></div>';

  const render = report => {
    const scopeNames = { personal: "🏠 Побут", business: "💼 Бізнес" };
    content.innerHTML = `<div class="report-summary-grid">
      <article class="report-summary-card"><span>Доходи</span><strong class="report-positive">${money(report.summary.income)}</strong><small>${monthLabel(report.period)}</small></article>
      <article class="report-summary-card"><span>Витрати</span><strong class="report-negative">${money(report.summary.expense)}</strong><small>за вибраний період</small></article>
      <article class="report-summary-card"><span>Результат</span><strong class="${report.summary.balance >= 0 ? "report-positive" : "report-negative"}">${money(report.summary.balance)}</strong><small>доходи мінус витрати</small></article>
      <article class="report-summary-card"><span>Операції</span><strong>${report.summary.transaction_count}</strong><small>усього записів</small></article>
    </div>
    <div class="report-breakdowns">
      <section class="report-block"><h3>Профілі</h3>${rowsHtml(report.workspace_totals, "workspace_name")}</section>
      <section class="report-block"><h3>Картки</h3>${rowsHtml(report.card_totals, "card_name")}</section>
      <section class="report-block"><h3>Категорії витрат</h3>${report.expense_categories.length ? report.expense_categories.map(row => `<div class="report-row"><span>${escapeHtml(row.category)}</span><small></small><b class="report-negative">${money(row.amount)}</b></div>`).join("") : '<div class="bank-empty"><span>Витрат немає</span></div>'}</section>
      <section class="report-block"><h3>Розділи</h3>${report.scope_totals.length ? report.scope_totals.map(row => `<div class="report-row"><span>${scopeNames[row.scope]}</span><small>${row.count} операцій</small><b>${money(row.balance)}</b></div>`).join("") : '<div class="bank-empty"><span>Даних немає</span></div>'}</section>
    </div>
    <section class="report-block"><h3>Усі операції за ${monthLabel(report.period)}</h3><div class="report-table-wrap"><table class="report-table"><thead><tr><th>Дата</th><th>Опис</th><th>Профіль</th><th>Категорія</th><th>Сума</th></tr></thead><tbody>${report.transactions.map(item => `<tr><td>${new Date(`${item.date}T00:00:00`).toLocaleDateString("uk-UA")}</td><td>${escapeHtml(item.description)}${item.bank_account_name ? `<small> · 💳 ${escapeHtml(item.bank_account_name)}</small>` : ""}</td><td>${item.scope === "business" ? "💼" : "🏠"} ${escapeHtml(item.workspace_name || "Основний")}</td><td>${escapeHtml(item.category)}</td><td class="${item.type === "income" ? "report-positive" : "report-negative"}">${item.type === "income" ? "+" : "−"}${money(item.amount)}</td></tr>`).join("") || '<tr><td colspan="5">Операцій за цей місяць немає</td></tr>'}</tbody></table></div></section>`;
  };

  const loadReport = async () => {
    if (!monthInput.value) return;
    loading(true);
    try {
      currentReport = await api.getMonthlyReport(filters());
      render(currentReport);
    } catch (error) { notify(error.message, true); }
    finally { loading(false); }
  };

  const open = async (latest = false) => {
    if (latest) monthInput.value = previousKey;
    scopeSelect.value = latest ? "all" : api.getScope();
    await loadWorkspaceOptions(latest ? null : api.getWorkspaceId());
    modal.classList.remove("hidden");
    localStorage.setItem(`pocket-report-viewed-${previousKey}`, "1");
    banner.classList.add("hidden");
    await loadReport();
  };

  document.querySelector("#reports-button").addEventListener("click", () => open(false));
  document.querySelector("#open-latest-report").addEventListener("click", () => open(true));
  document.querySelector("#dismiss-report-banner").addEventListener("click", () => { localStorage.setItem(`pocket-report-viewed-${previousKey}`, "1"); banner.classList.add("hidden"); });
  scopeSelect.addEventListener("change", () => loadWorkspaceOptions(null).catch(error => notify(error.message, true)));
  document.querySelector("#report-filter-form").addEventListener("submit", event => { event.preventDefault(); loadReport(); });
  document.querySelector("#download-report-csv").addEventListener("click", () => {
    if (!monthInput.value) return;
    const anchor = document.createElement("a");
    anchor.href = api.monthlyReportCsvUrl(filters());
    anchor.download = `Pocket-Money-${monthInput.value}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    notify("Завантаження місячного звіту розпочато");
  });

  if (!localStorage.getItem(`pocket-report-viewed-${previousKey}`)) {
    document.querySelector("#monthly-report-banner-title").textContent = `Звіт за ${monthLabel(previousKey)} готовий`;
    banner.classList.remove("hidden");
  }
}
