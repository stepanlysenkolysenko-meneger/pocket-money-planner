import { api } from "./api.js";

const escapeHtml = text => String(text || "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

export function setupWorkspaces({ refreshAll, notify, loading }) {
  const select = document.querySelector("#workspace-select");
  const modal = document.querySelector("#workspaces-modal");
  const form = document.querySelector("#workspace-form");
  const nameInput = document.querySelector("#workspace-name");
  const list = document.querySelector("#workspaces-list");
  let rows = [];
  let authenticated = false;
  let creating = false;
  let loadGeneration = 0;

  const scopeWords = () => api.getScope() === "business"
    ? { icon: "💼", plural: "Бізнеси", all: "Усі бізнеси разом", defaultName: "Новий бізнес" }
    : { icon: "🏠", plural: "Побутові профілі", all: "Усі побутові профілі разом", defaultName: "Новий побутовий профіль" };

  const updateLabels = () => {
    const words = scopeWords();
    const selected = rows.find(row => row.id === api.getWorkspaceId());
    document.querySelector("#workspace-kind-icon").textContent = words.icon;
    document.querySelector("#workspace-kind-label").textContent = words.plural;
    document.querySelector("#workspace-current-label").textContent = selected?.name || words.all;
    document.querySelector("#workspace-label").textContent = selected?.name || (api.getScope() === "business" ? "Усі бізнес-фінанси" : "Усі побутові фінанси");
    nameInput.placeholder = api.getScope() === "business" ? "Наприклад, Магазин №2" : "Наприклад, Родина або Відпочинок";
  };

  const render = () => {
    const words = scopeWords();
    select.innerHTML = `<option value="">${words.all}</option>${rows.map(row => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join("")}`;
    select.value = api.getWorkspaceId() || "";
    list.innerHTML = rows.map(row => `<article class="workspace-item">
      <span class="workspace-item-icon">${words.icon}</span>
      <span><b>${escapeHtml(row.name)} ${row.is_default ? '<span class="workspace-default">ОСНОВНИЙ</span>' : ""}</b><small>Карток: ${row.card_count} · операцій: ${row.transaction_count}</small></span>
      <span class="workspace-item-actions"><button data-workspace-action="rename" data-id="${row.id}" type="button" title="Перейменувати">✎</button>${row.is_default ? "" : `<button class="danger" data-workspace-action="delete" data-id="${row.id}" type="button" title="Видалити">×</button>`}</span>
    </article>`).join("");
    updateLabels();
  };

  const load = async () => {
    const generation = ++loadGeneration;
    const scope = api.getScope();
    const result = await api.getWorkspaces(scope);
    if (!authenticated || generation !== loadGeneration || scope !== api.getScope()) return;
    rows = result;
    if (api.getWorkspaceId() && !rows.some(row => row.id === api.getWorkspaceId())) api.setWorkspaceId(null);
    render();
  };

  select.addEventListener("change", async () => {
    if (!authenticated) return;
    api.setWorkspaceId(select.value);
    updateLabels();
    window.dispatchEvent(new CustomEvent("workspace:changed", { detail: { workspaceId: api.getWorkspaceId() } }));
    loading(true);
    try {
      await refreshAll();
      notify(api.getWorkspaceId() ? `Відкрито: ${rows.find(row => row.id === api.getWorkspaceId())?.name}` : scopeWords().all);
    } finally { loading(false); }
  });

  document.querySelector("#manage-workspaces").addEventListener("click", async () => {
    if (!authenticated) return;
    await load();
    modal.classList.remove("hidden");
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!authenticated || creating) return;
    const name = nameInput.value.trim();
    if (!name) return;
    creating = true;
    const submitButton = form.querySelector("button[type='submit']");
    submitButton.disabled = true;
    try {
      const created = await api.createWorkspace({ name, scope: api.getScope() });
      nameInput.value = "";
      await load();
      api.setWorkspaceId(created.id);
      render();
      await refreshAll();
      notify(`${api.getScope() === "business" ? "Бізнес" : "Профіль"} «${created.name}» створено`);
    } catch (error) { notify(error.message, true); }
    finally {
      creating = false;
      submitButton.disabled = false;
    }
  });

  list.addEventListener("click", async event => {
    const button = event.target.closest("button[data-workspace-action]");
    if (!authenticated || !button) return;
    const row = rows.find(item => item.id === Number(button.dataset.id));
    if (!row) return;
    try {
      if (button.dataset.workspaceAction === "rename") {
        const name = prompt("Нова назва профілю:", row.name)?.trim();
        if (!name || name === row.name) return;
        await api.renameWorkspace(row.id, name);
        notify("Назву оновлено");
      } else {
        if (!confirm(`Видалити «${row.name}»? Картки та операції безпечно перейдуть до основного профілю.`)) return;
        await api.deleteWorkspace(row.id);
        if (api.getWorkspaceId() === row.id) api.setWorkspaceId(null);
        notify("Профіль видалено, дані перенесено до основного");
      }
      await load();
      await refreshAll();
    } catch (error) { notify(error.message, true); }
  });

  window.addEventListener("scope:changed", () => {
    if (authenticated) load().catch(error => notify(error.message, true));
  });
  window.addEventListener("auth:ready", event => {
    authenticated = event.detail.authenticated;
    if (authenticated) load().catch(error => notify(error.message, true));
  });
  window.addEventListener("auth:login", () => {
    authenticated = true;
    load().catch(error => notify(error.message, true));
  });
  window.addEventListener("auth:logout", () => {
    authenticated = false;
    loadGeneration += 1;
  });
}
