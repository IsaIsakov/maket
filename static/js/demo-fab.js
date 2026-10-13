/* Demo mode: floating theme switcher, enabled ONLY via ?demo=1 in the URL.
   Perfect for pitching the template to a salon owner on a tablet. */
(function () {
  const params = new URLSearchParams(location.search);

  // restore previously chosen theme (persists across pages even without demo flag)
  const saved = localStorage.getItem("demo-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);

  if (params.get("demo") !== "1") return;

  const themes = [
    ["light", "Minimalist White"],
    ["dark", "Dark Mode"],
    ["gold", "Luxury Gold"],
    ["rose", "Rose Beauty"],
  ];

  const wrap = document.createElement("div");
  wrap.id = "demo-fab";
  wrap.style.display = "flex";
  wrap.innerHTML = `
    <div class="fab-panel">
      ${themes.map(([t, label]) =>
        `<div class="swatch" data-t="${t}" title="${label}"></div>`).join("")}
    </div>
    <div class="fab-btn" title="Demo themes">🎨</div>`;
  document.body.appendChild(wrap);

  const panel = wrap.querySelector(".fab-panel");
  wrap.querySelector(".fab-btn").addEventListener("click", () => {
    panel.style.display = panel.style.display === "flex" ? "none" : "flex";
  });

  wrap.querySelectorAll(".swatch").forEach(el => {
    el.addEventListener("click", () => {
      const t = el.dataset.t;
      document.documentElement.setAttribute("data-theme", t);
      localStorage.setItem("demo-theme", t);
      panel.style.display = "none";
    });
  });
})();
