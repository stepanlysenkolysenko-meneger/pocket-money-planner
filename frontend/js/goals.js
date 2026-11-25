import { api } from "./api.js";

let goals = [];
const money = value => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 2 }).format(value)} ₴`;
const safe = value => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

export function setupGoals({ refreshAll, notify, loading }) {
  const form = document.querySelector("#goal-form");
  let submitting = false;
  const pendingActions = new Set();
  document.querySelector("#show-goal-form").addEventListener("click", () => { reset(); form.classList.remove("hidden"); form.scrollIntoView({ behavior:"smooth", block:"center" }); });
  document.querySelector("#cancel-goal").addEventListener("click", () => form.classList.add("hidden"));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    const data = { title: document.querySelector("#goal-title").value.trim(), target_amount: Number(document.querySelector("#target-amount").value), saved_amount: Number(document.querySelector("#saved-amount").value), deadline: document.querySelector("#deadline").value };
    const error = !data.title ? "Вкажи назву цілі." : data.target_amount <= 0 ? "Потрібна сума має бути більшою за нуль." : data.saved_amount < 0 || data.saved_amount > data.target_amount ? "Накопичена сума має бути від 0 до суми цілі." : !data.deadline ? "Обери дату." : "";
    document.querySelector("#goal-error").textContent = error; if (error) return;
    submitting = true;
    const submitButton = form.querySelector("button[type='submit']");
    submitButton.disabled = true;
    try {
      await run(async () => { const id = document.querySelector("#goal-id").value; if (id) await api.updateGoal(id,data); else await api.createGoal(data); notify(id ? "Ціль оновлено" : "Нову ціль створено"); form.classList.add("hidden"); await refreshAll(); });
    } finally {
      submitting = false;
      submitButton.disabled = false;
    }
  });
  document.querySelector("#goals-list").addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]"); if (!button) return; const goal = goals.find(x => x.id === Number(button.dataset.id));
    if (!goal || pendingActions.has(goal.id)) return;
    if (button.dataset.action === "edit") { fill(goal); form.classList.remove("hidden"); form.scrollIntoView({behavior:"smooth",block:"center"}); }
    if (button.dataset.action === "delete" && confirm(`Видалити ціль «${goal.title}»?`)) {
      pendingActions.add(goal.id);
      try { await run(async()=>{await api.deleteGoal(goal.id);notify("Ціль видалено");await refreshAll();}); }
      finally { pendingActions.delete(goal.id); }
    }
    if (button.dataset.action === "deposit") {
      const amount = prompt(`Скільки додати? Залишилося ${money(goal.target_amount-goal.saved_amount)}`);
      if (amount === null) return;
      const number = Number(String(amount).replace(",",".")); if (!number || number <= 0) return notify("Вкажи коректну суму",true);
      pendingActions.add(goal.id);
      try { await run(async()=>{const result=await api.depositGoal(goal.id,number);notify(Number(result.saved_amount) >= Number(result.target_amount) ? "Вітаємо! Фінансову ціль досягнуто!" : "Гроші додано до цілі");await refreshAll();}); }
      finally { pendingActions.delete(goal.id); }
    }
  });
  async function run(fn){loading(true);try{await fn();}catch(error){notify(error.message,true);}finally{loading(false);}}
}
export function setGoals(data){goals=data;render();}
function render(){const list=document.querySelector("#goals-list");document.querySelector("#goals-empty").classList.toggle("hidden",goals.length>0);list.innerHTML=goals.map(goal=>{const percent=Math.min(100,Math.round(goal.saved_amount/goal.target_amount*100));return `<article class="panel goal-card"><h3>🎧 ${safe(goal.title)}</h3><span class="deadline">До ${new Date(`${goal.deadline}T00:00:00`).toLocaleDateString("uk-UA")}</span><div class="goal-money"><strong>${money(goal.saved_amount)}</strong><span>із ${money(goal.target_amount)}</span></div><progress class="progress-track" max="100" value="${percent}" aria-label="Виконано ${percent} відсотків"></progress><div class="goal-bottom"><span class="goal-percent">${percent}% готово</span><div class="goal-actions">${percent<100?`<button class="deposit-btn" data-action="deposit" data-id="${goal.id}">＋ Додати</button>`:""}<button data-action="edit" data-id="${goal.id}">✎</button><button data-action="delete" data-id="${goal.id}">×</button></div></div>${percent===100?'<div class="completed">✓ Вітаємо! Фінансову ціль досягнуто!</div>':""}</article>`}).join("");}
function reset(){document.querySelector("#goal-form").reset();document.querySelector("#goal-id").value="";document.querySelector("#saved-amount").value=0;document.querySelector("#goal-error").textContent="";}
function fill(goal){document.querySelector("#goal-id").value=goal.id;document.querySelector("#goal-title").value=goal.title;document.querySelector("#target-amount").value=goal.target_amount;document.querySelector("#saved-amount").value=goal.saved_amount;document.querySelector("#deadline").value=goal.deadline;}
