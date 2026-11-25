import { api } from "./api.js";

const symbols = { 980: "₴", 840: "$", 978: "€", 985: "zł" };
const formatMoney = (amount, currency) => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(Number(amount) || 0)} ${symbols[currency] || currency}`;
const escapeHtml = text => String(text || "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

export function setupBanks({ notify, refreshAll, loading }) {
  const modal = document.querySelector("#banks-modal");
  const form = document.querySelector("#monobank-form");
  const list = document.querySelector("#bank-accounts");
  const disconnect = document.querySelector("#disconnect-monobank");
  const disconnectPrivat = document.querySelector("#disconnect-privat-business");
  const importForm = document.querySelector("#statement-import-form");
  const bankSelect = document.querySelector("#statement-bank");
  const providerTitle = document.querySelector("#statement-provider-title");
  const providerPicker = document.querySelector("#bank-provider-picker");
  const monobankPanel = document.querySelector("#monobank-provider-panel");
  const privatPanel = document.querySelector("#privat-business-provider-panel");
  const statementPanel = document.querySelector("#statement-provider-panel");
  const statementSubmit = document.querySelector("#statement-submit");
  const statementBankLabel = document.querySelector("#statement-bank-label");
  const vaultBanner = document.querySelector("#bank-vault-banner");
  const vaultStatus = document.querySelector("#bank-vault-status");
  const vaultLock = document.querySelector("#bank-vault-lock");

  const showVaultState = unlocked => {
    vaultBanner.classList.toggle("unlocked", unlocked);
    vaultStatus.textContent = unlocked ? "Відкрито на 5 хв" : "Заблоковано";
    vaultLock.classList.toggle("hidden", !unlocked);
  };

  const askForBankPin = () => new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "vault-confirm-overlay";
    overlay.innerHTML = `<form class="vault-confirm-card">
      <h3>🛡️ Підтвердження безпеки</h3>
      <p>Введи свій 4-значний PIN. Після підтвердження зміни банків будуть доступні 5 хвилин.</p>
      <input type="password" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" autocomplete="off" aria-label="PIN-код" required>
      <div class="vault-confirm-actions"><button class="secondary-btn" type="button">Скасувати</button><button class="primary-btn" type="submit">Підтвердити</button></div>
    </form>`;
    const finish = value => { overlay.remove(); resolve(value); };
    overlay.querySelector("button[type=button]").addEventListener("click", () => finish(null));
    overlay.addEventListener("click", event => { if (event.target === overlay) finish(null); });
    overlay.querySelector("form").addEventListener("submit", event => {
      event.preventDefault();
      const pin = overlay.querySelector("input").value;
      if (/^\d{4}$/.test(pin)) finish(pin);
    });
    document.body.appendChild(overlay);
    overlay.querySelector("input").focus();
  });

  const refreshVaultState = async () => {
    const state = await api.getBankVaultStatus();
    showVaultState(state.unlocked);
    return state.unlocked;
  };

  const ensureBankVault = async () => {
    if (await refreshVaultState()) return true;
    const pin = await askForBankPin();
    if (!pin) return false;
    await api.unlockBankVault(pin);
    showVaultState(true);
    notify("Банківський сейф відкрито на 5 хвилин");
    return true;
  };

  vaultLock.addEventListener("click", async () => {
    await api.lockBankVault();
    showVaultState(false);
    notify("Банківський сейф заблоковано");
  });
  const quickBanks = new Set(["ПриватБанк", "ПУМБ", "Ощадбанк", "Sense Bank", "Raiffeisen Bank"]);
  const updateProviderTitle = () => {
    providerTitle.textContent = bankSelect.value;
    statementSubmit.textContent = `Імпортувати з ${bankSelect.value}`;
  };
  bankSelect.addEventListener("change", updateProviderTitle);
  updateProviderTitle();

  providerPicker.addEventListener("click", event => {
    const button = event.target.closest("button[data-bank-provider]");
    if (!button) return;
    providerPicker.querySelectorAll(".bank-provider-option").forEach(item => item.classList.toggle("active", item === button));
    const provider = button.dataset.bankProvider;
    const isMono = provider === "Monobank";
    const isPrivat = provider === "ПриватБанк";
    monobankPanel.classList.toggle("hidden", !isMono);
    privatPanel.classList.toggle("hidden", !isPrivat);
    statementPanel.classList.toggle("hidden", isMono || isPrivat);
    if (isMono) {
      document.querySelector("#monobank-token").focus();
      return;
    }
    if (isPrivat) {
      document.querySelector("#privat-business-token").focus();
      return;
    }
    bankSelect.value = provider;
    statementBankLabel.classList.toggle("bank-select-emphasis", provider === "Інший банк");
    updateProviderTitle();
    if (quickBanks.has(provider)) document.querySelector("#statement-account-name").placeholder = `Наприклад, картка ${provider}`;
    else document.querySelector("#statement-account-name").placeholder = "Наприклад, Картка для виплат";
    statementPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  document.querySelector("#banks-button").addEventListener("click", async () => {
    modal.classList.remove("hidden");
    document.querySelector("#statement-scope").value = api.getScope();
    loading(true);
    try {
      const refresh = await api.refreshBankBalances();
      if (refresh.errors?.length) notify(`Не всі банки оновлено: ${refresh.errors.join(" · ")}`, true);
      await Promise.all([refreshAccounts(), refreshVaultState()]);
    } finally { loading(false); }
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const input = document.querySelector("#monobank-token");
    const token = input.value.trim();
    if (!token) return;
    try {
      if (!await ensureBankVault()) return;
      loading(true);
      const result = await api.connectMonobank(token);
      input.value = "";
      notify(`Monobank підключено${result.client_name ? `: ${result.client_name}` : ""}`);
      await refreshAccounts();
    } catch (error) {
      notify(error.message, true);
    } finally {
      loading(false);
    }
  });

  document.querySelector("#privat-business-form").addEventListener("submit", async event => {
    event.preventDefault();
    const input = document.querySelector("#privat-business-token");
    const token = input.value.trim();
    if (!token) return;
    try {
      if (!await ensureBankVault()) return;
      loading(true);
      const selectedScope = document.querySelector("#privat-business-scope").value;
      const result = await api.connectPrivatBusiness({ token, scope: selectedScope, workspace_id: selectedScope === api.getScope() ? api.getWorkspaceId() : null });
      input.value = "";
      notify(`ПриватБанк підключено · рахунків ${result.accounts.length}`);
      await refreshAccounts();
      await refreshAll();
    } catch (error) { notify(error.message, true); }
    finally { loading(false); }
  });

  document.querySelector("#show-privat-import").addEventListener("click", () => {
    statementPanel.classList.remove("hidden");
    bankSelect.value = "ПриватБанк";
    updateProviderTitle();
    statementPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  importForm.addEventListener("submit", async event => {
    event.preventDefault();
    const file = document.querySelector("#statement-file").files[0];
    if (!file) return notify("Обери CSV-виписку банку", true);
    if (file.size > 5 * 1024 * 1024) return notify("Виписка має бути не більшою за 5 МБ", true);
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        if (!await ensureBankVault()) return;
        loading(true);
        const result = await api.importBankStatement({
          bank: document.querySelector("#statement-bank").value,
          account_name: document.querySelector("#statement-account-name").value.trim(),
          scope: document.querySelector("#statement-scope").value,
          workspace_id: document.querySelector("#statement-scope").value === api.getScope() ? api.getWorkspaceId() : null,
          file_data: reader.result,
        });
        notify(`${document.querySelector("#statement-bank").value}: імпортовано ${result.imported} · пропущено повторів ${result.duplicates}`);
        document.querySelector("#statement-file").value = "";
        await refreshAccounts();
        await refreshAll();
      } catch (error) { notify(error.message, true); }
      finally { loading(false); }
    };
    reader.readAsDataURL(file);
  });

  list.addEventListener("click", async event => {
    const button = event.target.closest("button[data-sync-account]");
    if (!button) return;
    button.disabled = true;
    button.textContent = "Синхронізую…";
    try {
      const result = await api.syncBankAccount(Number(button.dataset.syncAccount));
      if (result.inactive) {
        notify("Ця картка більше не доступна через API банку й прихована зі списку", true);
        await refreshAccounts();
        return;
      }
      const details = [];
      if (result.imported) details.push(`додано ${result.imported}`);
      if (result.recategorized) details.push(`уточнено категорії для ${result.recategorized}`);
      notify(details.length ? details.join(" · ") : "Нових операцій немає, категорії актуальні");
      await refreshAccounts();
      await refreshAll();
    } catch (error) {
      notify(error.message, true);
      button.disabled = false;
      button.textContent = "Синхронізувати";
    }
  });

  list.addEventListener("change", async event => {
    const select = event.target.closest("select[data-account-workspace]");
    if (!select) return;
    select.disabled = true;
    try {
      const workspaceId = Number(select.value);
      const workspaceName = select.options[select.selectedIndex]?.textContent || "профілю";
      await api.setBankAccountWorkspace(Number(select.dataset.accountWorkspace), workspaceId);
      notify(`Картку прив’язано до «${workspaceName}»`);
      await refreshAccounts();
      await refreshAll();
    } catch (error) {
      notify(error.message, true);
      select.disabled = false;
    }
  });

  disconnect.addEventListener("click", async () => {
    if (!confirm("Відключити Monobank? Імпортовані операції залишаться, але токен і список карток буде видалено.")) return;
    try {
      if (!await ensureBankVault()) return;
      await api.disconnectMonobank();
      notify("Monobank відключено");
      await refreshAccounts();
      await refreshAll();
    } catch (error) { notify(error.message, true); }
  });

  disconnectPrivat.addEventListener("click", async () => {
    if (!confirm("Відключити Приват24 для бізнесу? Операції залишаться, але зашифрований токен і список рахунків буде видалено.")) return;
    try {
      if (!await ensureBankVault()) return;
      await api.disconnectPrivatBusiness();
      notify("Приват24 для бізнесу відключено");
      await refreshAccounts();
      await refreshAll();
    } catch (error) { notify(error.message, true); }
  });

  async function refreshAccounts() {
    try {
      const [accounts, personalWorkspaces, businessWorkspaces] = await Promise.all([api.getBankAccounts(), api.getWorkspaces("personal"), api.getWorkspaces("business")]);
      const allWorkspaces = [...personalWorkspaces, ...businessWorkspaces];
      const workspaceOptions = account => allWorkspaces.map(workspace => `<option value="${workspace.id}" ${workspace.id === account.workspace_id ? "selected" : ""}>${workspace.scope === "business" ? "💼" : "🏠"} ${escapeHtml(workspace.name)}</option>`).join("");
      disconnect.classList.toggle("hidden", !accounts.some(account => account.provider === "monobank"));
      disconnectPrivat.classList.toggle("hidden", !accounts.some(account => account.provider === "privat_business"));
      list.innerHTML = accounts.length ? accounts.map(account => `
        <article class="bank-account">
          <div class="${account.provider === "monobank" ? "bank-account-logo" : "bank-provider-badge"}">${account.provider === "monobank" ? "M" : account.provider === "privat_business" ? "П" : escapeHtml(account.bank_name.slice(0, 1).toUpperCase())}</div>
          <div class="bank-account-info">
            <strong>${escapeHtml(account.display_name)}</strong>
            <span>${escapeHtml(account.masked_pan || `Рахунок ${account.bank_name}`)}</span>
            <small>${account.balance_updated_at ? `Баланс: ${new Date(account.balance_updated_at).toLocaleString("uk-UA")}` : "Баланс ще не звірено"}${account.last_sync ? ` · операції: ${new Date(account.last_sync).toLocaleString("uk-UA")}` : " · операції ще не синхронізовано"}</small>
          </div>
          <div class="bank-account-balance"><strong>${formatMoney(account.balance, account.currency_code)}</strong><span>Кредитний ліміт: ${formatMoney(account.credit_limit, account.currency_code)}</span></div>
          <label class="bank-scope-label">Профіль<select data-account-workspace="${account.id}">${workspaceOptions(account)}</select></label>
          ${["monobank", "privat_business"].includes(account.provider) ? `<button class="secondary-btn" data-sync-account="${account.id}" type="button">Синхронізувати</button>` : '<span class="bank-imported-label">Файл банку</span>'}
        </article>`).join("") : '<div class="bank-empty">💳<strong>Картки ще не підключені</strong><span>Обери банк вище та підключи токен або імпортуй CSV-виписку.</span></div>';
    } catch (error) { notify(error.message, true); }
  }
}
