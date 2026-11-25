import { api } from "./api.js";
import { setupTransactions, setTransactions } from "./transactions.js";
import { setupGoals, setGoals } from "./goals.js";
import { renderStatistics } from "./statistics.js";
import { setupFeatures, setFeatureData } from "./features.js";
import { setupBanks } from "./banks.js";
import { setupPlatform, setupTaxAndCrypto } from "./platform.js";
import { setupWorkspaces } from "./workspaces.js";
import { setupReports } from "./reports.js";

const money = value => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(value)} ₴`;
const loader = document.querySelector("#loader");
const toast = document.querySelector("#toast");
const loginScreen = document.querySelector("#login-screen");
let toastTimer;
let authenticated = false;
let loadingCount = 0;
let refreshGeneration = 0;
function loading(show) {
  loadingCount = Math.max(0, loadingCount + (show ? 1 : -1));
  loader.classList.toggle("hidden", loadingCount === 0);
}
function notify(message, error = false) { clearTimeout(toastTimer); toast.textContent = message; toast.classList.toggle("error", error); toast.classList.add("show"); toastTimer = setTimeout(() => toast.classList.remove("show"), 3200); }

function setupScopeSwitch() {
  const switcher = document.querySelector("#scope-switch");
  const apply = scope => {
    api.setScope(scope);
    document.body.dataset.scope = scope;
    switcher.querySelectorAll("button").forEach(button => button.classList.toggle("active", button.dataset.scope === scope));
    document.querySelector("#workspace-label").textContent = scope === "business" ? "Бізнес-фінанси" : "Побутові фінанси";
  };
  apply(api.getScope());
  switcher.addEventListener("click", async event => {
    const button = event.target.closest("button[data-scope]");
    if (!button || button.dataset.scope === api.getScope()) return;
    apply(button.dataset.scope);
    window.dispatchEvent(new CustomEvent("scope:changed", { detail: { scope: api.getScope() } }));
    loading(true);
    try {
      await refreshAll();
      notify(api.getScope() === "business" ? "Відкрито бізнес-фінанси" : "Відкрито побутові фінанси");
    } finally { loading(false); }
  });
}

function updateSmartAdvice(transactions, summary) {
  const advice = document.querySelector("#smart-advice");
  const title = document.querySelector("#smart-advice-title");
  const text = document.querySelector("#smart-advice-text");
  const planButton = document.querySelector("#smart-plan-button");
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const spentToday = transactions.filter(item => item.type === "expense" && item.date === todayKey).reduce((sum, item) => sum + Number(item.amount), 0);
  const lowBalance = transactions.length > 0 && (Number(summary.balance) < 500 || (Number(summary.income) > 0 && Number(summary.balance) < Number(summary.income) * .2));

  if (!spentToday && !lowBalance) {
    advice.classList.add("hidden");
    return;
  }

  advice.classList.remove("hidden");
  advice.classList.toggle("low-balance", lowBalance);
  planButton.classList.toggle("hidden", !spentToday);
  if (lowBalance) {
    title.textContent = "Баланс стає низьким";
    text.textContent = spentToday
      ? `Сьогодні ти витратив ${money(spentToday)}. Залишилося ${money(summary.balance)} — хочеш додати план?`
      : `Залишилося ${money(summary.balance)}. Спробуй запланувати наступні витрати.`;
  } else {
    title.textContent = "Підсумок дня";
    text.textContent = `Сьогодні ти витратив ${money(spentToday)}. Хочеш додати план?`;
  }
}

document.querySelector("#smart-plan-button").addEventListener("click", () => {
  document.querySelector("#show-goal-form").click();
  document.querySelector("#goals").scrollIntoView({ behavior: "smooth", block: "start" });
});
document.querySelector("#smart-advice-close").addEventListener("click", () => document.querySelector("#smart-advice").classList.add("hidden"));

function setupPigAnimations() {
  const depositPig = document.querySelector("#deposit-pig");
  const expensePig = document.querySelector("#expense-pig");
  const card = document.querySelector("#balance-card");
  let depositTimer;
  let expenseTimer;

  window.addEventListener("money:income", () => {
    clearInterval(depositTimer);
    let frame = 0;
    expensePig.classList.remove("active");
    depositPig.classList.add("active");
    card.classList.remove("money-arrived");
    void card.offsetWidth;
    card.classList.add("money-arrived");

    const showFrame = () => {
      const column = frame % 4;
      const row = Math.floor(frame / 4);
      depositPig.style.backgroundPosition = `${column * 100 / 3}% ${row * 50}%`;
      frame += 1;
      if (frame >= 12) {
        clearInterval(depositTimer);
        setTimeout(() => {
          depositPig.classList.remove("active");
          card.classList.remove("money-arrived");
          depositPig.style.backgroundPosition = "0 0";
        }, 650);
      }
    };
    showFrame();
    depositTimer = setInterval(showFrame, 120);
  });

  window.addEventListener("money:expense", () => {
    clearInterval(expenseTimer);
    let frame = 0;
    depositPig.classList.remove("active");
    expensePig.classList.add("active");
    card.classList.remove("money-spent");
    void card.offsetWidth;
    card.classList.add("money-spent");

    const showFrame = () => {
      expensePig.style.backgroundPosition = `${frame * 100 / 7}% 50%`;
      frame += 1;
      if (frame >= 8) {
        clearInterval(expenseTimer);
        setTimeout(() => {
          expensePig.classList.remove("active");
          card.classList.remove("money-spent");
          expensePig.style.backgroundPosition = "0 50%";
        }, 500);
      }
    };
    showFrame();
    expenseTimer = setInterval(showFrame, 135);
  });
}

async function setupLogin() {
  const form = document.querySelector("#login-form");
  const nameInput = document.querySelector("#login-name");
  const pinInput = document.querySelector("#login-pin");
  const confirmInput = document.querySelector("#confirm-pin");
  const confirmLabel = document.querySelector("#confirm-pin-label");
  const errorBox = document.querySelector("#login-error");
  let mode = "login";
  let submitting = false;

  try {
    const status = await api.getAuthStatus();
    authenticated = status.authenticated;
    if (status.name) nameInput.value = status.name;
    if (status.authenticated) loginScreen.classList.add("hidden");
  } catch (error) {
    errorBox.textContent = `Не вдалося перевірити акаунт: ${error.message}`;
  }

  function setMode(nextMode) {
    mode = nextMode;
    const registering = mode === "register";
    document.querySelector("#show-login").classList.toggle("active", !registering);
    document.querySelector("#show-register").classList.toggle("active", registering);
    confirmLabel.classList.toggle("hidden", !registering);
    document.querySelector("#auth-title").textContent = registering ? "Створення профілю" : "Вхід у Pocket Money";
    document.querySelector("#auth-copy").textContent = registering ? "Придумай ім’я та PIN-код для входу." : "Увійди у свій локальний профіль.";
    document.querySelector("#auth-submit").textContent = registering ? "Зареєструватися" : "Увійти";
    pinInput.value = "";
    confirmInput.value = "";
    errorBox.textContent = "";
  }

  document.querySelector("#show-login").addEventListener("click", () => setMode("login"));
  document.querySelector("#show-register").addEventListener("click", () => setMode("register"));

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    const name = nameInput.value.trim();
    const pin = pinInput.value;
    const submitButton = document.querySelector("#auth-submit");

    if (!name) return errorBox.textContent = "Введи своє ім’я.";
    if (!/^\d{6,8}$/.test(pin)) return errorBox.textContent = "PIN-код має містити 6–8 цифр.";

    if (mode === "register") {
      if (confirmInput.value !== pin) return errorBox.textContent = "PIN-коди не збігаються.";
    }

    submitting = true;
    submitButton.disabled = true;
    errorBox.textContent = "";
    try {
      if (mode === "register") await api.register({ name, pin });
      else await api.login({ name, pin });
      authenticated = true;
      pinInput.value = "";
      confirmInput.value = "";
      loginScreen.classList.add("hidden");
      window.dispatchEvent(new CustomEvent("auth:login"));
      await refreshAll();
      api.refreshBankBalances().catch(() => {});
      notify(`Привіт, ${name}!`);
    } catch (error) {
      errorBox.textContent = error.message;
    } finally {
      submitting = false;
      submitButton.disabled = false;
    }
  });

  document.querySelector("#logout-button").addEventListener("click", async () => {
    if (!authenticated) return;
    if (!confirm("Ви точно хочете вийти з акаунта?")) return;
    try {
      await api.logout();
      authenticated = false;
      refreshGeneration += 1;
      pinInput.value = "";
      setMode("login");
      loginScreen.classList.remove("hidden");
      window.dispatchEvent(new CustomEvent("auth:logout"));
    } catch (error) {
      notify(error.message, true);
    }
  });
  return authenticated;
}

async function refreshAll() {
  if (!authenticated) return;
  const generation = ++refreshGeneration;
  try {
    const [transactions, goals, summary, statistics] = await Promise.all([api.getTransactions(), api.getGoals(), api.getSummary(), api.getStatistics()]);
    if (!authenticated || generation !== refreshGeneration) return;
    setTransactions(transactions); setGoals(goals);
    document.querySelector("#balance").textContent = money(summary.balance);
    document.querySelector("#total-income").textContent = money(summary.income);
    document.querySelector("#total-expense").textContent = money(summary.expense);
    updateSmartAdvice(transactions, summary);
    await setFeatureData(transactions, summary);
    if (!authenticated || generation !== refreshGeneration) return;
    renderStatistics(statistics);
  } catch (error) { notify(`Не вдалося підключитися до API: ${error.message}`, true); }
}

const savedTheme = localStorage.getItem("pocket-theme");
if (savedTheme === "dark") document.body.classList.add("dark");
const themeButton = document.querySelector("#theme-toggle");
function updateThemeButton() { themeButton.textContent = document.body.classList.contains("dark") ? "☀️" : "🌙"; }
themeButton.addEventListener("click", () => { document.body.classList.toggle("dark"); localStorage.setItem("pocket-theme", document.body.classList.contains("dark") ? "dark" : "light"); updateThemeButton(); refreshAll(); });
updateThemeButton();
setupScopeSwitch();
const loginReady = setupLogin();
setupPigAnimations();
setupWorkspaces({ refreshAll, notify, loading });
setupReports({ notify, loading });
setupTransactions({ refreshAll, notify, loading });
setupGoals({ refreshAll, notify, loading });
setupFeatures({ notify, refreshAll });
setupBanks({ notify, refreshAll, loading });
setupTaxAndCrypto({ notify, loading });
setupPlatform({ notify });
window.addEventListener("beforeunload", () => {
  if (authenticated) {
    // Спроба очистити сесію на бекенді при закритті вікна, щоб наступний запуск вимагав PIN.
    navigator.sendBeacon("/api/auth/logout");
  }
});

loginReady.then(isAuthenticated => {
  window.dispatchEvent(new CustomEvent("auth:ready", { detail: { authenticated: isAuthenticated } }));
  if (isAuthenticated) {
    loading(true);
    refreshAll().finally(() => loading(false));
    api.refreshBankBalances().catch(() => {});
  }
});
