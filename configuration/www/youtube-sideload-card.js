// custom:youtube-sideload-card — status of the sideloaded YouTube / YouTube Music
// on each iPhone (sensor.youtube_sideload_<slug>, published by iphone/autorefresh.sh)
// as a table. The phone icon shows the status (green ok, yellow under WARN_DAYS left,
// red expired or failed; the status text is its tooltip) and is the re-sign button
// (input_button.youtube_resign_<slug>). Under the table: the re-sign progress notes
// (sensor.youtube_resign_progress, see packages/youtube_sideload.yaml); a ✅ result is
// hidden 2 min after it arrived, anything else after a day.
// Source: ~/work/revanced/iphone/ha/youtube-sideload-card.js on the Mac.
//
//   type: custom:youtube-sideload-card
//   phones: [yurii, ekaterina, mila]
(() => {
  const WARN_DAYS = 5;
  const LABELS = {
    ok: "✅ OK",
    waiting: "⏳ Чекає на телефон",
    alert: "⚠️ Підключи до Mac",
    expired: "❌ Підпис закінчився",
    error: "❗ Помилка оновлення",
  };

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  const ago = (ts) => {
    const d = new Date(ts);
    if (!ts || isNaN(d)) return "—";
    const m = Math.floor((Date.now() - d) / 60000);
    if (m < 2) return "щойно";
    if (m < 60) return `${m} хв тому`;
    if (m < 1440) return `${Math.floor(m / 60)} год тому`;
    return `${Math.floor(m / 1440)} дн тому`;
  };

  const left = (ts) => {
    const d = new Date(ts);
    if (!ts || isNaN(d)) return "—";
    const h = Math.floor((d - Date.now()) / 3600000);
    if (h <= 0) return "закінчився";
    if (h < 24) return `${h} год`;
    return `${Math.floor(h / 24)} д ${h % 24} год`;
  };

  const statusColor = (state, expires) => {
    if (state === "expired" || state === "error") return "var(--error-color)";
    const ms = new Date(expires) - Date.now();
    if (!expires || isNaN(ms)) return "var(--disabled-text-color)";
    if (ms <= 0) return "var(--error-color)";
    if (ms < WARN_DAYS * 86400000) return "var(--warning-color)";
    return "var(--success-color)";
  };

  class YoutubeSideloadCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.phones) || !config.phones.length) throw new Error("phones: [slug, ...] is required");
      this._config = config;
      this._key = undefined;
    }

    set hass(hass) {
      this._hass = hass;
      const ids = [
        ...this._config.phones.map((p) => `sensor.youtube_sideload_${p}`),
        "sensor.youtube_sideload_last_run",
        "sensor.youtube_resign_progress",
      ];
      // Re-render on state changes and at least once a minute, for the "ago" texts
      const key = JSON.stringify(ids.map((id) => hass.states[id])) + Math.floor(Date.now() / 60000);
      if (key === this._key) return;
      this._key = key;
      this._render();
    }

    getCardSize() {
      return this._config.phones.length + 2;
    }

    _render() {
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      const states = this._hass.states;
      const rows = this._config.phones
        .map((slug) => {
          const s = states[`sensor.youtube_sideload_${slug}`];
          const a = s?.attributes || {};
          const seen = a.last_seen ? `${ago(a.last_seen)}${a.transport ? ` (${esc(a.transport)})` : ""}` : "—";
          return `
            <tr>
              <td class="name">
                <ha-icon-button data-slug="${esc(slug)}" style="color: ${statusColor(s?.state, a.expires)}"
                  label="${esc(LABELS[s?.state] || "❔ Немає даних")} · натисни, щоб перепідписати">
                  <ha-icon icon="${esc(a.icon || "mdi:cellphone")}"></ha-icon>
                </ha-icon-button>
                ${esc((a.friendly_name || slug).replace(/^iPhone \((.*)\)$/, "$1"))}
              </td>
              <td>${left(a.expires)}</td>
              <td>${esc(a.youtube_version || "—")}</td>
              <td>${esc(a.music_version || "—")}</td>
              <td>${seen}</td>
            </tr>`;
        })
        .join("");
      const notes = Object.values(states["sensor.youtube_resign_progress"]?.attributes.notes || {})
        .filter((n) => {
          const age = Date.now() - new Date(n.at);
          return age < 86400000 && !(String(n.message).startsWith("✅") && age > 120000);
        })
        .map((n) => {
          const who = String(n.title || "").replace("📱", "").replace("YouTube:", "").replace("YouTube", "").trim() || "YouTube";
          return `<div><b>${esc(who)}</b>: ${esc(n.message)} <small>(${ago(n.at)})</small></div>`;
        })
        .join("");
      const lastRun = states["sensor.youtube_sideload_last_run"]?.state;
      const lastRunText = lastRun && !["unknown", "unavailable"].includes(lastRun) ? ago(lastRun) : "немає даних";
      this.shadowRoot.innerHTML = `
        <style>
          .wrap { overflow-x: auto; padding: 8px 8px 0 8px; }
          table { border-collapse: collapse; width: 100%; }
          th, td { text-align: left; padding: 6px 12px 6px 0; white-space: nowrap; }
          th { font-weight: 500; color: var(--secondary-text-color); font-size: 13px;
               border-bottom: 1px solid var(--divider-color); }
          tr + tr td { border-top: 1px solid var(--divider-color); }
          td.name { font-weight: 500; }
          th:first-child { padding-left: 8px; }
          td.name { padding-top: 0; padding-bottom: 0; }
          td.name ha-icon-button { vertical-align: middle; margin-right: 2px; }
          .notes { padding: 8px 16px 0; line-height: 20px; }
          .note { padding: 8px 16px 12px; font-size: 12px; color: var(--secondary-text-color); line-height: 18px; }
        </style>
        <ha-card>
          <div class="wrap">
            <table>
              <thead><tr><th>Телефон</th><th>Лишилось</th><th>YouTube</th><th>YT Music</th><th>Востаннє в мережі</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
          ${notes ? `<div class="notes">${notes}</div>` : ""}
          <div class="note">
            Останній запуск скрипта: ${lastRunText} · оновлення підпису за 2 дні до кінця<br>
            Щоб перепідписати вручну: розблокуй телефон і натисни його іконку, хід і результат з'являться тут
          </div>
        </ha-card>`;
      this.shadowRoot.querySelectorAll("ha-icon-button").forEach((btn) => {
        btn.addEventListener("click", () => this._resign(btn.dataset.slug));
      });
    }

    _resign(slug) {
      this._hass.callService("input_button", "press", { entity_id: `input_button.youtube_resign_${slug}` });
    }
  }

  customElements.define("youtube-sideload-card", YoutubeSideloadCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "youtube-sideload-card", name: "YouTube sideload card" });
})();
