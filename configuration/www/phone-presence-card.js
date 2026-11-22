// Phone presence card: one row per phone with online/offline status and a
// colored phone icon by time since the phone was last seen on the LAN.
// Data: device_tracker.<name> from presence/lan_watch.py (MQTT discovery).
// State "home" = seen within the last 10 min; when "not_home", attribute
// "since" = the last time the phone was seen.
// Color: green < 30 min, yellow 30-60 min, red >= 60 min, grey = no data.
//
// config:
//   type: custom:phone-presence-card
//   phones:
//     - entity: device_tracker.realme_6
//       name: Катерина І.
class PhonePresenceCard extends HTMLElement {
  setConfig(config) {
    if (!Array.isArray(config.phones) || !config.phones.length) {
      throw new Error("phones: list of {entity, name} required");
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    // Refresh "N хв тому" and colors even when the entity state does not change.
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return 1 + this._config.phones.length;
  }

  getGridOptions() {
    return { columns: "full" };
  }

  _ago(minutes) {
    if (minutes < 1) return "щойно";
    if (minutes < 60) return `${Math.floor(minutes)} хв тому`;
    const h = Math.floor(minutes / 60);
    if (h < 24) return `${h} год ${Math.floor(minutes % 60)} хв тому`;
    const d = Math.floor(h / 24);
    return `${d} дн ${h % 24} год тому`;
  }

  _time(date) {
    const today = new Date();
    const opts = { hour: "2-digit", minute: "2-digit" };
    if (date.toDateString() !== today.toDateString()) {
      Object.assign(opts, { day: "2-digit", month: "2-digit" });
    }
    return date.toLocaleString("uk-UA", opts);
  }

  _row(phone) {
    const st = this._hass && this._hass.states[phone.entity];
    let color = "var(--disabled-text-color, #9e9e9e)";
    let status = "немає даних";
    let detail = "";
    if (st && (st.state === "home" || st.state === "not_home")) {
      const online = st.state === "home";
      const since = st.attributes.since ? new Date(st.attributes.since) : null;
      const minutes = online ? 0 : since ? (Date.now() - since) / 60000 : Infinity;
      color = minutes < 30 ? "var(--success-color, #43a047)"
        : minutes < 60 ? "var(--warning-color, #ffa600)"
        : "var(--error-color, #db4437)";
      status = online ? "в мережі" : "не в мережі";
      if (online && since) detail = `з ${this._time(since)}`;
      else if (!online && since) detail = `востаннє ${this._time(since)} · ${this._ago(minutes)}`;
    }
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    return `
      <div class="row" data-entity="${esc(phone.entity)}">
        <div class="icon" style="color:${color};background:color-mix(in srgb, ${color} 18%, transparent)">
          <ha-icon icon="mdi:cellphone"></ha-icon>
        </div>
        <div class="text">
          <div class="name">${esc(phone.name || phone.entity)}</div>
          <div class="detail">${esc(detail)}</div>
        </div>
        <div class="status" style="color:${color}">${esc(status)}</div>
      </div>`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this.appendChild(this._card);
      this._card.addEventListener("click", (e) => {
        const row = e.target.closest(".row");
        if (!row) return;
        this.dispatchEvent(new CustomEvent("hass-more-info", {
          bubbles: true, composed: true, detail: { entityId: row.dataset.entity },
        }));
      });
    }
    const html = `
      <style>
        .wrap { padding: 8px 16px; }
        .title { font-size: 16px; font-weight: 500; padding: 8px 0 4px; }
        .row { display: flex; align-items: center; gap: 12px; padding: 8px 0; cursor: pointer; }
        .row + .row { border-top: 1px solid var(--divider-color); }
        .icon { width: 40px; height: 40px; border-radius: 50%; display: flex;
                align-items: center; justify-content: center; flex: none; }
        .text { flex: 1; min-width: 0; }
        .name { font-weight: 500; }
        .detail { font-size: 12px; color: var(--secondary-text-color); }
        .status { font-weight: 500; white-space: nowrap; }
      </style>
      <div class="wrap">
        ${this._config.title ? `<div class="title">${this._config.title}</div>` : ""}
        ${this._config.phones.map((p) => this._row(p)).join("")}
      </div>`;
    if (html !== this._last) {
      this._card.innerHTML = html;
      this._last = html;
    }
  }
}

customElements.define("phone-presence-card", PhonePresenceCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "phone-presence-card", name: "Phone presence" });
