let expenseChart;
let monthlyChart;

export function renderStatistics(data) {
  document.querySelector("#top-category").textContent = data.top_expense_category || "Ще немає";
  document.querySelector("#transaction-count").textContent = data.transaction_count;
  if (!window.Chart) return;
  const textColor = getComputedStyle(document.body).getPropertyValue("--muted").trim();
  const gridColor = getComputedStyle(document.body).getPropertyValue("--border").trim();
  expenseChart?.destroy(); monthlyChart?.destroy();
  expenseChart = new Chart(document.querySelector("#expense-chart"), { type:"doughnut", data:{labels:data.expenses_by_category.map(x=>x.category),datasets:[{data:data.expenses_by_category.map(x=>x.amount),backgroundColor:["#7557ed","#19a974","#f05b72","#ffc94d","#4cb7e8","#b078f3","#ff8b57"],borderWidth:0,hoverOffset:6}]}, options:{responsive:true,maintainAspectRatio:false,cutout:"68%",plugins:{legend:{position:"bottom",labels:{color:textColor,usePointStyle:true,boxWidth:8,font:{size:10}}}}} });
  monthlyChart = new Chart(document.querySelector("#monthly-chart"), { type:"bar", data:{labels:data.monthly.map(x=>x.month),datasets:[{label:"Доходи",data:data.monthly.map(x=>x.income),backgroundColor:"#19a974",borderRadius:7},{label:"Витрати",data:data.monthly.map(x=>x.expense),backgroundColor:"#f05b72",borderRadius:7}]}, options:{responsive:true,maintainAspectRatio:false,scales:{x:{grid:{display:false},ticks:{color:textColor}},y:{beginAtZero:true,grid:{color:gridColor},ticks:{color:textColor}}},plugins:{legend:{labels:{color:textColor,usePointStyle:true}}}} });
}
