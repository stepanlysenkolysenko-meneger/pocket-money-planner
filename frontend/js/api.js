// Відносна адреса працює і з localhost, і з 127.0.0.1, і в локальній мережі.
const API_URL = "/api";
let activeScope = localStorage.getItem("pocket-scope") === "business" ? "business" : "personal";
const storedWorkspace = scope => Number(localStorage.getItem(`pocket-workspace-${scope}`)) || null;
let activeWorkspaceId = storedWorkspace(activeScope);
const scoped = path => {
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}scope=${activeScope}${activeWorkspaceId ? `&workspace_id=${activeWorkspaceId}` : ""}`;
};
const withScope = data => ({ ...data, scope: activeScope });
const withWorkspace = data => ({ ...data, scope: activeScope, workspace_id: activeWorkspaceId });
const reportQuery = ({ year, month, scope = "all", workspace_id = null }) => `year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}&scope=${encodeURIComponent(scope)}${workspace_id ? `&workspace_id=${encodeURIComponent(workspace_id)}` : ""}`;

async function request(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!response.ok) {
    let message = "Сталася помилка. Спробуй ще раз.";
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg || message;
    } catch (_) { /* Сервер повернув відповідь без JSON. */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

export const api = {
  getScope: () => activeScope,
  setScope: scope => { activeScope = scope === "business" ? "business" : "personal"; activeWorkspaceId = storedWorkspace(activeScope); localStorage.setItem("pocket-scope", activeScope); },
  getWorkspaceId: () => activeWorkspaceId,
  setWorkspaceId: id => { activeWorkspaceId = Number(id) || null; if (activeWorkspaceId) localStorage.setItem(`pocket-workspace-${activeScope}`, activeWorkspaceId); else localStorage.removeItem(`pocket-workspace-${activeScope}`); },
  getWorkspaces: (scope = activeScope) => request(`/workspaces?scope=${scope}`),
  createWorkspace: data => request("/workspaces", { method: "POST", body: JSON.stringify(data) }),
  renameWorkspace: (id, name) => request(`/workspaces/${id}`, { method: "PUT", body: JSON.stringify({ name }) }),
  deleteWorkspace: id => request(`/workspaces/${id}`, { method: "DELETE" }),
  getMonthlyReport: filters => request(`/reports/monthly?${reportQuery(filters)}`),
  monthlyReportCsvUrl: filters => `${API_URL}/reports/monthly.csv?${reportQuery(filters)}`,
  getAuthStatus: () => request("/auth/status"),
  register: data => request("/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: data => request("/auth/login", { method: "POST", body: JSON.stringify(data) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  getBankVaultStatus: () => request("/security/bank-vault"),
  unlockBankVault: pin => request("/security/bank-vault/unlock", { method: "POST", body: JSON.stringify({ pin }) }),
  lockBankVault: () => request("/security/bank-vault/lock", { method: "POST" }),
  getTransactions: () => request(scoped("/transactions")),
  createTransaction: data => request("/transactions", { method: "POST", body: JSON.stringify(withWorkspace(data)) }),
  updateTransaction: (id, data) => request(`/transactions/${id}`, { method: "PUT", body: JSON.stringify(withWorkspace(data)) }),
  deleteTransaction: id => request(`/transactions/${id}`, { method: "DELETE" }),
  getGoals: () => request(scoped("/goals")),
  createGoal: data => request("/goals", { method: "POST", body: JSON.stringify(withScope(data)) }),
  updateGoal: (id, data) => request(`/goals/${id}`, { method: "PUT", body: JSON.stringify(withScope(data)) }),
  deleteGoal: id => request(`/goals/${id}`, { method: "DELETE" }),
  depositGoal: (id, amount) => request(`/goals/${id}/deposit`, { method: "PATCH", body: JSON.stringify({ amount }) }),
  getSummary: () => request(scoped("/summary")),
  getStatistics: () => request(scoped("/statistics")),
  getLimits: () => request(scoped("/limits")),
  saveLimit: data => request("/limits", { method: "POST", body: JSON.stringify(withScope(data)) }),
  deleteLimit: id => request(`/limits/${id}`, { method: "DELETE" }),
  getBankAccounts: () => request("/banks/accounts"),
  refreshBankBalances: () => request("/banks/refresh", { method: "POST" }),
  connectMonobank: token => request("/banks/monobank/connect", { method: "POST", body: JSON.stringify({ token, scope: activeScope, workspace_id: activeWorkspaceId }) }),
  connectPrivatBusiness: data => request("/banks/privat-business/connect", { method: "POST", body: JSON.stringify(data) }),
  importBankStatement: data => request("/banks/import", { method: "POST", body: JSON.stringify(data) }),
  syncBankAccount: id => request(`/banks/accounts/${id}/sync`, { method: "POST" }),
  setBankAccountScope: (id, scope) => request(`/banks/accounts/${id}/scope`, { method: "PATCH", body: JSON.stringify({ scope }) }),
  setBankAccountWorkspace: (id, workspace_id) => request(`/banks/accounts/${id}/workspace`, { method: "PATCH", body: JSON.stringify({ workspace_id }) }),
  disconnectMonobank: () => request("/banks/monobank", { method: "DELETE" }),
  disconnectPrivatBusiness: () => request("/banks/privat-business", { method: "DELETE" }),
  getTaxProfile: () => request("/tax/profile"),
  saveTaxProfile: data => request("/tax/profile", { method: "PUT", body: JSON.stringify(data) }),
  getTaxSummary: (year, quarter) => request(`/tax/summary?year=${year}&quarter=${quarter}`),
  getCrypto: () => request("/crypto"),
  connectCrypto: data => request("/crypto/connect", { method: "POST", body: JSON.stringify(data) }),
  syncCrypto: () => request("/crypto/sync", { method: "POST" }),
  disconnectCrypto: () => request("/crypto", { method: "DELETE" }),
  readReceipt: image_data => request("/receipts/read", { method: "POST", body: JSON.stringify({ image_data }) }),
  getAiStatus: () => request("/ai/status"),
  getAiHistory: () => request(scoped("/ai/history")),
  aiChat: message => request("/ai/chat", { method: "POST", body: JSON.stringify({ message, scope: activeScope }) }),
  aiReceipt: image_data => request("/ai/receipt", { method: "POST", body: JSON.stringify({ image_data }) }),
  translateUi: (language, texts) => request("/ai/translate", { method: "POST", body: JSON.stringify({ language, texts }) }),
};
