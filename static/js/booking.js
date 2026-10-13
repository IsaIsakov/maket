/* Public booking flow: settings -> services -> slot picker -> submit */
const $ = (s) => document.querySelector(s);

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Request failed");
  return data;
}

let selectedSlot = null;

async function loadSettings() {
  const s = await api("/api/settings/public");
  document.title = s.company_name;
  $("#brand-name").textContent = s.company_name;
  $("#footer-name").textContent = s.company_name;
  $("#hero-desc").textContent = s.description;
  $("#hours-line").textContent = "Open daily " + s.opening_hours;
  if (s.logo_url) {
    $("#brand-logo").src = s.logo_url;
    $("#brand-logo").classList.remove("hidden");
  }
}

async function loadServices() {
  const services = await api("/api/services");
  const sel = $("#service");
  sel.innerHTML = services.map(s =>
    `<option value="${s.id}">${s.name} — $${s.price} (${s.duration_min} min)</option>`
  ).join("");
  const grid = $("#services-grid");
  grid.innerHTML = services.map(s => `
    <div class="surface rounded-2xl p-6 border brd">
      <div class="text-lg font-semibold">${s.name}</div>
      <p class="dim text-sm mt-2">${s.description || ""}</p>
      <div class="mt-4 flex justify-between items-center">
        <span class="accent font-bold text-xl">$${s.price}</span>
        <span class="dim text-sm">${s.duration_min} min</span>
      </div>
    </div>`).join("");
}

async function loadSlots() {
  const date = $("#date").value;
  selectedSlot = null;
  $("#slot-grid").innerHTML = "";
  $("#submit-btn").disabled = true;
  if (!date) return;
  const { slots } = await api(`/api/availability?date=${date}`);
  $("#slot-grid").innerHTML = slots.length
    ? slots.map(t => `<button type="button" class="slot" data-t="${t}">${t}</button>`).join("")
    : `<span class="dim text-sm">No free slots for this day.</span>`;
  $("#slot-grid").querySelectorAll(".slot").forEach(b =>
    b.addEventListener("click", () => {
      $("#slot-grid").querySelectorAll(".slot").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      selectedSlot = b.dataset.t;
      $("#submit-btn").disabled = false;
    }));
}

async function submitBooking(ev) {
  ev.preventDefault();
  if (!selectedSlot) return;
  const btn = $("#submit-btn");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    await api("/api/bookings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_name: $("#name").value.trim(),
        phone: $("#phone").value.trim(),
        service_id: Number($("#service").value),
        start_time: `${$("#date").value}T${selectedSlot}`,
      }),
    });
    $("#booking-form").classList.add("hidden");
    $("#booking-success").classList.remove("hidden");
  } catch (e) {
    toast("⚠️ " + e.message);
    btn.disabled = false;
    btn.textContent = "Book now";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await Promise.all([loadSettings(), loadServices()]);
    const d = $("#date");
    d.min = new Date().toISOString().slice(0, 10);
    d.addEventListener("change", loadSlots);
    $("#booking-form").addEventListener("submit", submitBooking);
  } catch (e) {
    toast("Failed to load page data: " + e.message);
  }
});
