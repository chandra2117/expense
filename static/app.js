// app.js
const CATEGORIES = ["Food","Travel","Shopping","Bills","Medical","Trip","Dress","Cosmetics","JunkFood","Other"];

document.addEventListener("DOMContentLoaded", ()=> {
  // populate category select
  const catSel = document.getElementById("category");
  CATEGORIES.forEach(c => {
    const opt = document.createElement("option"); opt.value = c; opt.textContent = c; catSel.appendChild(opt);
  });

  // set default date
  document.getElementById("date").value = new Date().toISOString().slice(0,10);

  // event handlers
  document.getElementById("add-form").addEventListener("submit", handleAdd);
  document.getElementById("refresh-btn").addEventListener("click", loadExpenses);
  document.getElementById("set-budget-btn").addEventListener("click", openSetBudget);
  document.getElementById("set-cat-limit-btn").addEventListener("click", openSetCategoryLimit);
  document.getElementById("mark-unwanted-btn").addEventListener("click", openMarkUnwanted);
  document.getElementById("suggestions-btn").addEventListener("click", openSuggestions);
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("export-xlsx").addEventListener("click", ()=>{ window.location = "/api/export/excel"; });
  document.getElementById("export-pdf").addEventListener("click", ()=>{ window.location = "/api/export/pdf"; });
  document.getElementById("block-mode-toggle").addEventListener("change", toggleBlockMode);

  loadSettings();
  loadExpenses();
  loadCharts();
});

function showModal(html){
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal").classList.remove("hidden");
}
function closeModal(){
  document.getElementById("modal").classList.add("hidden");
}

// load settings: budget, block mode
async function loadSettings(){
  const res = await fetch("/api/settings");
  const json = await res.json();
  const budget = json["monthly_budget"] ? Number(json["monthly_budget"]) : 0;
  document.getElementById("budget-amt").textContent = budget.toFixed(0);
  // block mode
  const blockMode = json["block_mode"] === "1";
  document.getElementById("block-mode-toggle").checked = blockMode;
  // spent & savings update
  refreshBudgetPanel();
}

async function refreshBudgetPanel(){
  const res = await fetch("/api/expenses");
  const data = await res.json();
  const today = new Date();
  const ym = today.toISOString().slice(0,7);
  let spent = 0;
  data.forEach(e => { if (e.date && e.date.startsWith(ym)) spent += Number(e.amount); });
  const settings = await (await fetch("/api/settings")).json();
  const budget = settings["monthly_budget"] ? Number(settings["monthly_budget"]) : 0;
  const savings = Math.max(0, budget - spent);
  document.getElementById("spent-amt").textContent = spent.toFixed(0);
  document.getElementById("savings-amt").textContent = savings.toFixed(0);
}

async function loadExpenses(){
  const res = await fetch("/api/expenses");
  const data = await res.json();
  const tbody = document.querySelector("#expenses-table tbody");
  tbody.innerHTML = "";
  data.forEach(e => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${e.id}</td><td>₹${Number(e.amount).toFixed(2)}</td><td>${e.category}</td><td>${e.description||''}</td><td>${e.date}</td>
      <td><button data-id="${e.id}" class="del-btn">Delete</button></td>`;
    tbody.appendChild(tr);
  });
  document.querySelectorAll(".del-btn").forEach(b => b.addEventListener("click", async ev=>{
    const id = ev.target.dataset.id;
    if (!confirm("Delete this expense?")) return;
    await fetch("/api/expenses/" + id, {method:"DELETE"});
    await loadExpenses();
    await refreshBudgetPanel();
    await loadCharts();
  }));
  await refreshBudgetPanel();
  await loadCharts();
}

async function handleAdd(e){
  e.preventDefault();
  const amount = document.getElementById("amount").value;
  const category = document.getElementById("category").value;
  const description = document.getElementById("description").value;
  const date = document.getElementById("date").value;
  const payload = {amount, category, description, date};
  const res = await fetch("/api/expenses", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(()=>({}));
  if (res.status === 201 && json.ok){
    alert("Added.");
    document.getElementById("add-form").reset();
    document.getElementById("date").value = new Date().toISOString().slice(0,10);
    await loadExpenses();
    return;
  }
  // handle warnings/errors from backend
  if (json.error){
    if (json.error === "category_blocked"){
      alert("Category is blocked and block mode is ON. Cannot add.");
      return;
    }
    alert("Error: " + json.error);
    return;
  }
  if (json.warning){
    if (json.warning === "category_limit_exceeded"){
      const ok = confirm(`This will exceed category limit (limit ₹${json.limit}). Cancel? Click OK to CANCEL, Cancel to FORCE add.`);
      if (!ok){
        // force add
        await fetch("/api/expenses/force_add", {
          method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)
        });
        alert("Added.");
        await loadExpenses(); return;
      } else { return; }
    }
    if (json.warning === "budget_exceeded"){
      const ok = confirm(`This will exceed monthly budget (budget ₹${json.budget}). Add anyway?`);
      if (ok){
        await fetch("/api/expenses/force_add", {
          method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)
        });
        alert("Added.");
        await loadExpenses(); return;
      } else { return; }
    }
    // generic
    alert("Warning: " + JSON.stringify(json));
    return;
  }
  // fallback error
  alert("Unexpected response from server.");
}

function openSetBudget(){
  showModal(`<h3>Set Budget</h3>
    <div><input id="modal-budget" placeholder="Enter budget (₹)"></div>
    <div style="margin-top:8px"><button id="save-budget">Save</button></div>`);
  document.getElementById("save-budget").addEventListener("click", async ()=>{
    const v = Number(document.getElementById("modal-budget").value||0);
    await fetch("/api/set_budget", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({budget:v})});
    closeModal(); loadSettings(); refreshBudgetPanel();
  });
}

function openSetCategoryLimit(){
  // build select + input
  let html = `<h3>Set Category Limit</h3>
    <div><select id="modal-cat">`;
  CATEGORIES.forEach(c=> html += `<option>${c}</option>`);
  html += `</select></div>
    <div style="margin-top:8px"><input id="modal-limit" placeholder="Limit (₹)"></div>
    <div style="margin-top:8px"><button id="save-cat-limit">Save</button></div>`;
  showModal(html);
  document.getElementById("save-cat-limit").addEventListener("click", async ()=>{
    const cat = document.getElementById("modal-cat").value;
    const limit = Number(document.getElementById("modal-limit").value||0);
    await fetch("/api/set_category_limit", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({category:cat, limit})});
    closeModal(); alert("Saved"); 
  });
}

function openMarkUnwanted(){
  let html = `<h3>Mark Unwanted Category</h3>
    <div><select id="modal-unw-cat">`;
  CATEGORIES.forEach(c=> html += `<option>${c}</option>`);
  html += `</select></div>
    <div style="margin-top:8px"><label><input type="checkbox" id="modal-unw-flag"> Mark as unwanted</label></div>
    <div style="margin-top:8px"><button id="save-unw">Save</button></div>`;
  showModal(html);
  document.getElementById("save-unw").addEventListener("click", async ()=>{
    const cat = document.getElementById("modal-unw-cat").value;
    const unw = document.getElementById("modal-unw-flag").checked;
    await fetch("/api/mark_unwanted", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({category:cat, unwanted:unw})});
    closeModal(); alert("Saved");
  });
}

async function openSuggestions(){
  const res = await fetch("/api/suggestions");
  const s = await res.json();
  let html = "<h3>Suggestions</h3><ul>";
  s.forEach(x=> html += `<li>${x}</li>`);
  html += "</ul><div style='margin-top:8px'><button id='close-sugg'>Close</button></div>";
  showModal(html);
  document.getElementById("close-sugg").addEventListener("click", closeModal);
}

async function toggleBlockMode(ev){
  const enabled = ev.target.checked;
  await fetch("/api/toggle_block", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({enabled})});
  alert("Block mode set to " + enabled);
}

let pieChart=null, trendChart=null;
async function loadCharts(){
  // pie
  const r1 = await fetch("/api/chart/category_pie");
  const d1 = await r1.json();
  const ctx1 = document.getElementById("pie-chart").getContext("2d");
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(ctx1, {
    type: "pie",
    data: { labels: d1.labels || [], datasets:[{data: d1.values || []}] },
    options: { 
      responsive:true,
      maintainAspectRatio:false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth:10, padding:8, usePointStyle:true } }
      }
    }
  });

  // trend
  const r2 = await fetch("/api/chart/monthly_trend");
  const d2 = await r2.json();
  const ctx2 = document.getElementById("trend-chart").getContext("2d");
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx2, {
    type: "line",
    data: { labels: d2.months || [], datasets:[{label:"Total", data: d2.totals || [], fill:false, tension:0.2}] },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      scales: {
        y: { beginAtZero:true }
      },
      plugins: {
        legend: { display: false }
      }
    }
  });
}
