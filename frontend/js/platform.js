import { api } from "./api.js";

const money = (value, currency = "₴") => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(Number(value) || 0)} ${currency}`;

export function setupPlatform({ notify }) {
  let installPrompt = null;
  const button = document.querySelector("#install-app");
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    installPrompt = event;
    button.classList.remove("hidden");
  });
  button.addEventListener("click", async () => {
    if (!installPrompt) return notify("На комп’ютері вже є окрема програма. На телефоні відкрий меню браузера → «Встановити застосунок».");
    await installPrompt.prompt();
    installPrompt = null;
    button.classList.add("hidden");
  });
  window.addEventListener("appinstalled", () => notify("Pocket Money встановлено"));
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

export function setupTaxAndCrypto({ notify, loading }) {
  const taxModal = document.querySelector("#tax-modal");
  const cryptoModal = document.querySelector("#crypto-modal");
  const taxSystem = document.querySelector("#tax-system");
  const customFields = document.querySelector("#custom-tax-fields");
  const year = new Date().getFullYear();
  const quarter = Math.floor(new Date().getMonth() / 3) + 1;
  document.querySelector("#tax-year").value = year;
  document.querySelector("#tax-quarter").value = quarter;

  document.querySelector("#tax-button").addEventListener("click", async () => {
    taxModal.classList.remove("hidden");
    try { fillTax(await api.getTaxProfile()); await renderTax(); } catch (error) { notify(error.message, true); }
  });
  taxSystem.addEventListener("change", () => customFields.classList.toggle("hidden", taxSystem.value !== "custom"));
  document.querySelector("#tax-form").addEventListener("submit", async event => {
    event.preventDefault(); loading(true);
    try {
      const data = taxData();
      fillTax(await api.saveTaxProfile(data));
      await renderTax(); notify("Податкові налаштування збережено");
    } catch (error) { notify(error.message, true); } finally { loading(false); }
  });
  document.querySelector("#tax-calculate").addEventListener("click", renderTax);

  function taxData() {
    return { system: taxSystem.value, single_tax_rate: Number(document.querySelector("#tax-rate").value || 0) / 100, single_tax_monthly: Number(document.querySelector("#tax-monthly").value || 0), military_rate: Number(document.querySelector("#military-rate").value || 0) / 100, military_monthly: Number(document.querySelector("#military-monthly").value || 0), esv_monthly: Number(document.querySelector("#esv-monthly").value || 0) };
  }
  function fillTax(profile) {
    taxSystem.value = profile.system;
    document.querySelector("#tax-rate").value = profile.single_tax_rate * 100;
    document.querySelector("#tax-monthly").value = profile.single_tax_monthly;
    document.querySelector("#military-rate").value = profile.military_rate * 100;
    document.querySelector("#military-monthly").value = profile.military_monthly;
    document.querySelector("#esv-monthly").value = profile.esv_monthly;
    customFields.classList.toggle("hidden", profile.system !== "custom");
  }
  async function renderTax() {
    try {
      const data = await api.getTaxSummary(Number(document.querySelector("#tax-year").value), Number(document.querySelector("#tax-quarter").value));
      document.querySelector("#tax-summary").innerHTML = `<div class="tool-total"><span>Резерв на податки</span><strong>${money(data.total)}</strong><small>з доходу ${money(data.income)} за ${data.quarter} квартал</small></div><div class="tax-breakdown"><span>Єдиний податок <b>${money(data.single_tax)}</b></span><span>Військовий збір <b>${money(data.military_tax)}</b></span><span>ЄСВ <b>${money(data.esv)}</b></span></div>`;
    } catch (error) { notify(error.message, true); }
  }

  document.querySelector("#crypto-button").addEventListener("click", async () => { cryptoModal.classList.remove("hidden"); await renderCrypto(); });
  document.querySelector("#crypto-form").addEventListener("submit", async event => {
    event.preventDefault(); loading(true);
    try {
      const data = await api.connectCrypto({ provider: "binance", api_key: document.querySelector("#crypto-key").value.trim(), api_secret: document.querySelector("#crypto-secret").value.trim() });
      document.querySelector("#crypto-key").value = ""; document.querySelector("#crypto-secret").value = "";
      showCrypto(data); notify("Binance підключено в режимі лише для читання");
    } catch (error) { notify(error.message, true); } finally { loading(false); }
  });
  document.querySelector("#crypto-sync").addEventListener("click", async () => { loading(true); try { showCrypto(await api.syncCrypto()); notify("Криптопортфель оновлено"); } catch (error) { notify(error.message, true); } finally { loading(false); } });
  document.querySelector("#crypto-disconnect").addEventListener("click", async () => { if (!confirm("Відключити Binance та видалити зашифровані ключі з цього комп’ютера?")) return; await api.disconnectCrypto(); await renderCrypto(); notify("Binance відключено"); });
  async function renderCrypto() { try { showCrypto(await api.getCrypto()); } catch (error) { notify(error.message, true); } }
  function showCrypto(data) {
    const form = document.querySelector("#crypto-form"); const actions = document.querySelector("#crypto-actions"); const box = document.querySelector("#crypto-portfolio");
    form.classList.toggle("hidden", data.connected); actions.classList.toggle("hidden", !data.connected);
    if (!data.connected) { box.innerHTML = '<div class="tool-empty">₿<b>Криптопортфель ще не підключено</b><span>Створи на Binance окремий API-ключ лише для читання.</span></div>'; return; }
    box.innerHTML = `<div class="tool-total"><span>Орієнтовна вартість</span><strong>${money(data.total_usdt, "USDT")}</strong><small>${data.last_sync ? `Оновлено ${new Date(data.last_sync).toLocaleString("uk-UA")}` : "Ще не синхронізовано"}</small></div><div class="asset-list">${data.assets.length ? data.assets.map(asset => `<div><b>${asset.symbol}</b><span>${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 8 }).format(asset.free + asset.locked)}</span><strong>${money(asset.value_usdt, "USDT")}</strong></div>`).join("") : "Немає активів з ненульовим балансом"}</div>`;
  }
}
