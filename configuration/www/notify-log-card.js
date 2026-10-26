// custom:notify-log-card — the Telegram notification history from
// sensor.telegram_notify_log (notify/notify_log.json, newest first): time,
// title and full text of every row, about `visible` rows tall and scrollable
// beyond that. Rows younger than Telegram's ~48h bot delete limit get a delete
// button (script.delete_notification_slot, with HA's confirmation dialog).
//
//   type: custom:notify-log-card
//   entity: sensor.telegram_notify_log   # default
//   visible: 10                          # rows shown before scrolling
(() => {
  const DELETE_WINDOW_MS = 48 * 3600 * 1000;

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // ts is "YYYY-MM-DD HH:MM:SS" in HA's local time.
  const parseTs = (ts) => new Date(String(ts).replace(" ", "T"));

  class NotifyLogCard extends HTMLElement {
    setConfig(config) {
      this._config = { entity: "sensor.telegram_notify_log", visible: 10, ...config };
      this._rowsJson = undefined;
    }

    set hass(hass) {
      this._hass = hass;
      const rows = hass.states[this._config.entity]?.attributes.rows || [];
      const json = JSON.stringify(rows);
      if (json === this._rowsJson) return;
      this._rowsJson = json;
      this._render(rows);
    }

    getCardSize() {
      return this._config?.visible || 10;
    }

    _render(rows) {
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const now = Date.now();
      const year = new Date().getFullYear();
      const items = rows
        .map((r, i) => {
          const d = parseTs(r.ts);
          const valid = !isNaN(d);
          const p = (n) => String(n).padStart(2, "0");
          const date = valid
            ? `${p(d.getDate())}.${p(d.getMonth() + 1)}${d.getFullYear() !== year ? "." + d.getFullYear() : ""}`
            : "";
          const time = valid ? `${p(d.getHours())}:${p(d.getMinutes())}` : "";
          const deletable = valid && now - d.getTime() < DELETE_WINDOW_MS;
          return `
            <div class="row">
              <div class="when"><div>${date}</div><div class="time">${time}</div></div>
              <div class="body">
                <div class="title">${esc(r.title)}</div>
                <div class="msg">${esc(r.message)}</div>
              </div>
              ${deletable
                ? `<ha-icon-button class="del" data-slot="${i + 1}" label="Видалити для всіх"></ha-icon-button>`
                : `<div class="del-spacer"></div>`}
            </div>`;
        })
        .join("");
      this.shadowRoot.innerHTML = `
        <style>
          .list { overflow-y: auto; padding: 0 4px 0 16px; }
          .row { display: flex; gap: 12px; align-items: flex-start; padding: 8px 0;
                 border-bottom: 1px solid var(--divider-color); }
          .row:last-child { border-bottom: none; }
          .when { flex: 0 0 auto; min-width: 44px; font-size: 12px;
                  color: var(--secondary-text-color); line-height: 18px; }
          .time { color: var(--primary-text-color); font-weight: 500; }
          .body { flex: 1 1 auto; min-width: 0; }
          .title { font-size: 12px; color: var(--secondary-text-color); line-height: 18px; }
          .msg { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 20px; }
          .del { flex: 0 0 auto; margin-top: -6px; color: var(--secondary-text-color); }
          .del-spacer { flex: 0 0 48px; }
          .empty { padding: 16px; color: var(--secondary-text-color); }
          .count { padding: 8px 16px; font-size: 12px; color: var(--secondary-text-color); }
        </style>
        <ha-card>
          ${rows.length
            ? `<div class="list">${items}</div><div class="count">Усього: ${rows.length}</div>`
            : `<div class="empty">Сповіщень немає</div>`}
        </ha-card>`;
      this.shadowRoot.querySelectorAll("ha-icon-button.del").forEach((btn) => {
        btn.path = "M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z";
        btn.addEventListener("click", () => this._delete(Number(btn.dataset.slot)));
      });
      requestAnimationFrame(() => this._fitHeight());
    }

    // Limit the list to the first `visible` rows' height; the rest scrolls.
    _fitHeight() {
      const list = this.shadowRoot.querySelector(".list");
      if (!list) return;
      const rows = list.querySelectorAll(".row");
      const n = this._config.visible;
      list.style.maxHeight = "";
      if (rows.length <= n) return;
      const last = rows[n - 1];
      if (!last.offsetHeight) return requestAnimationFrame(() => this._fitHeight());
      const bottom = last.getBoundingClientRect().bottom - list.getBoundingClientRect().top + list.scrollTop;
      list.style.maxHeight = `${Math.ceil(bottom)}px`;
    }

    _delete(slot) {
      const row = JSON.parse(this._rowsJson)[slot - 1];
      const preview = String(row?.message || "").split("\n")[0].slice(0, 80);
      this.dispatchEvent(
        new CustomEvent("hass-action", {
          bubbles: true,
          composed: true,
          detail: {
            action: "tap",
            config: {
              tap_action: {
                action: "perform-action",
                perform_action: "script.delete_notification_slot",
                data: { slot },
                confirmation: { text: `Видалити для всіх отримувачів?\n${preview}` },
              },
            },
          },
        })
      );
    }
  }

  customElements.define("notify-log-card", NotifyLogCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "notify-log-card", name: "Notify log card" });
})();
