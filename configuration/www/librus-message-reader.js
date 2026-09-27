// homeControll: Librus letter reader card (custom:librus-message-reader-card),
// placed right above the stock librus-messages-card on the Librus
// "Повідомлення" tab (librus/build_dashboard.py).
//
// A click on a letter in the stock list no longer expands it inline: the
// letter opens in this card instead - full text in an editable box (copy /
// edit freely, edits are not saved), attachments, and a "Переклад" button
// that adds the full Ukrainian translation below the text. The stock card is
// patched at run time (its _onMessageClick), not in the HACS file, so HACS
// updates don't wipe it; with no reader card on the page it behaves as stock.
//
// - The full text comes from the integration's get_message service = one
//   Librus request that also marks the letter read in Librus (same as the
//   stock card). Bodies are cached in localStorage per letter id, so
//   reopening a letter costs no request.
// - Translation runs in the browser: Google's free endpoint first, then
//   MyMemory (anonymous, ~5000 chars/day per IP, 500 chars per request -
//   translated paragraph by paragraph). Cached in localStorage as well.

const CACHE_PREFIX = "hc-librus-letter:";

function cacheGet(key) {
  try { return JSON.parse(localStorage.getItem(CACHE_PREFIX + key)); } catch { return null; }
}

function cacheSet(key, value) {
  try { localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value)); } catch { /* private mode */ }
}

// Librus dates are naive Polish time: "2026-09-24T14:26:42" -> "24.09.2026 14:26"
function fmtDate(s) {
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(s || "");
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : s || "";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function fetchJson(url, ms = 8000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

async function translateGoogle(text) {
  const url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=uk&dt=t&dj=1&q="
    + encodeURIComponent(text);
  const d = await fetchJson(url);
  const out = (d.sentences || []).map((s) => s.trans || "").join("");
  if (!out.trim()) throw new Error("empty");
  return out;
}

// MyMemory takes <= 500 chars: split a paragraph at sentence ends, then spaces.
function chunks(par, max = 450) {
  const out = [];
  let rest = par;
  while (rest.length > max) {
    let cut = Math.max(rest.lastIndexOf(". ", max), rest.lastIndexOf("! ", max), rest.lastIndexOf("? ", max));
    if (cut < max / 3) cut = rest.lastIndexOf(" ", max);
    if (cut < 1) cut = max;
    out.push(rest.slice(0, cut + 1));
    rest = rest.slice(cut + 1);
  }
  if (rest.trim()) out.push(rest);
  return out;
}

async function translateMyMemory(text) {
  const lines = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) { lines.push(line); continue; }
    const lead = line.match(/^\s*/)[0];
    const parts = [];
    for (const c of chunks(line.trim())) {
      const d = await fetchJson("https://api.mymemory.translated.net/get?langpair=pl|uk&q=" + encodeURIComponent(c));
      if (d.responseStatus !== 200 && d.responseStatus !== "200") throw new Error(d.responseDetails || "MyMemory error");
      const t = d.responseData?.translatedText || "";
      parts.push(t.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
    }
    lines.push(lead + parts.join(" "));
  }
  return lines.join("\n");
}

async function translate(text) {
  try { return await translateGoogle(text); } catch { /* fall through */ }
  return await translateMyMemory(text);
}

const READERS = new Set();

const CSS = `
  [hidden] { display: none !important; }
  :host { display: block; scroll-margin-top: calc(var(--header-height, 56px) + 16px); }
  ha-card { padding: 16px; }
  .hint { color: var(--secondary-text-color); display: flex; align-items: center; gap: 8px; }
  .head { display: flex; gap: 12px; align-items: flex-start; }
  .head .t { flex: 1; min-width: 0; }
  .topic { font-size: 1.1rem; font-weight: 600; line-height: 1.3; }
  .meta { font-size: .85rem; color: var(--secondary-text-color); margin-top: 4px; }
  .x { border: 0; background: none; color: inherit; font-size: 1.3rem; line-height: 1; cursor: pointer; padding: 4px 8px; }
  textarea { display: block; width: 100%; box-sizing: border-box; resize: vertical; min-height: 100px; overflow: hidden;
    font: inherit; font-size: .95rem; line-height: 1.5; padding: 10px 12px; border-radius: 8px; margin-top: 12px;
    border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); }
  .label { font-size: .8rem; font-weight: 600; color: var(--secondary-text-color);
    margin-top: 16px; text-transform: uppercase; letter-spacing: .04em; }
  .label + textarea { margin-top: 6px; }
  .att { display: flex; align-items: center; gap: 6px; font-size: .9rem; cursor: pointer;
    color: var(--primary-color); padding: 3px 0; }
  .att ha-icon { --mdc-icon-size: 18px; }
  .atts { margin-top: 8px; }
  .status { font-size: .85rem; color: var(--secondary-text-color); margin-top: 8px; }
  .status:empty { display: none; }
  .status.err { color: var(--error-color); }
  .foot { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: 12px; }
  .foot button { font: inherit; font-size: .95rem; font-weight: 500; border-radius: 20px; padding: 8px 18px;
    cursor: pointer; border: 1px solid var(--primary-color); background: none; color: var(--primary-color); }
  .foot button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .foot button:disabled { opacity: .5; cursor: default; }
`;

function grow(ta) {
  ta.style.height = "auto";
  ta.style.height = `${ta.scrollHeight + 2}px`;
}

class LibrusMessageReaderCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._build();
  }

  connectedCallback() {
    READERS.add(this);
    this._onResize = () => this.shadowRoot?.querySelectorAll("textarea").forEach(grow);
    window.addEventListener("resize", this._onResize);
  }

  disconnectedCallback() {
    READERS.delete(this);
    window.removeEventListener("resize", this._onResize);
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${CSS}</style><ha-card>
      <div class="hint"><ha-icon icon="mdi:email-open-outline"></ha-icon>Натисніть на лист у списку нижче - він відкриється тут</div>
      <div class="letter" hidden>
        <div class="head"><div class="t"><div class="topic"></div><div class="meta"></div></div>
          <button class="x" title="Закрити">✕</button></div>
        <textarea class="text" spellcheck="false"></textarea>
        <div class="atts"></div>
        <div class="status"></div>
        <div class="tr" hidden>
          <div class="label">Переклад українською</div>
          <textarea class="trtext" spellcheck="false"></textarea>
        </div>
        <div class="foot">
          <button class="copy">Копіювати</button>
          <button class="translate primary" disabled>Переклад</button>
        </div>
      </div></ha-card>`;
    this.$ = (sel) => root.querySelector(sel);
    this.$(".x").addEventListener("click", () => this._clear());
    this.$(".translate").addEventListener("click", () => this._translate());
    this.$(".copy").addEventListener("click", () => this._copy());
    for (const ta of root.querySelectorAll("textarea")) ta.addEventListener("input", () => grow(ta));
  }

  _clear() {
    this.msg = undefined;
    this.$(".letter").hidden = true;
    this.$(".hint").hidden = false;
  }

  _status(text, err = false) {
    const s = this.$(".status");
    s.textContent = text;
    s.classList.toggle("err", err);
  }

  _setArea(sel, text) {
    const ta = this.$(sel);
    ta.value = text;
    requestAnimationFrame(() => grow(ta));
  }

  // called by the patched stock card
  async show(msg, deviceId) {
    if (!this.shadowRoot) this._build();
    this.msg = msg;
    this.full = undefined;
    this.$(".hint").hidden = true;
    this.$(".letter").hidden = false;
    this.$(".topic").textContent = msg.topic || "";
    this.$(".meta").textContent = `${msg.sender || ""} · ${fmtDate(msg.date)}`;
    this.$(".atts").innerHTML = "";
    this.$(".tr").hidden = true;
    this.$(".translate").textContent = "Переклад";
    this.$(".translate").disabled = true;
    this._status("");
    this.scrollIntoView({ behavior: "smooth", block: "start" });
    let full = cacheGet(`msg:${msg.id}`);
    if (!full) {
      this._setArea(".text", msg.content || "");
      this._status("Завантаження повного тексту з Librus…");
      try {
        const r = await this._hass.callWS({
          type: "call_service", domain: "librus_synergia", service: "get_message",
          service_data: { device_id: deviceId, message_id: msg.id, mailbox: msg.mailbox || "inbox" },
          return_response: true,
        });
        full = r.response;
        cacheSet(`msg:${msg.id}`, full);
      } catch (e) {
        if (this.msg !== msg) return;
        this._status(`Не вдалося завантажити повний текст: ${e?.message || e}`, true);
        this.$(".translate").disabled = false;
        return;
      }
    }
    if (this.msg !== msg) return;  // another letter clicked meanwhile
    this.full = full;
    this._status("");
    this._setArea(".text", full.content || "");
    for (const a of full.attachments || []) {
      const el = document.createElement("div");
      el.className = "att";
      el.innerHTML = `<ha-icon icon="mdi:paperclip"></ha-icon>${esc(a.filename ?? a.id)}`;
      el.addEventListener("click", () => this._openAttachment(full, a));
      this.$(".atts").appendChild(el);
    }
    this.$(".translate").disabled = false;
    const tr = cacheGet(`tr:${msg.id}`);
    if (tr) this._showTranslation(tr);
  }

  async _openAttachment(full, att) {
    // same flow as patch 9 in librus/apply_local_patches.py: open the tab
    // synchronously (popup blockers), then point it at a signed URL
    const w = window.open("", "_blank");
    try {
      const r = await this._hass.callWS({ type: "auth/sign_path",
        path: `/api/librus_synergia/attachment/${full.id}/${att.id}`, expires: 600 });
      if (w) w.location.href = r.path; else window.location.href = r.path;
    } catch (e) {
      if (w) w.close();
      alert(`Librus: ${e?.message || e}`);
    }
  }

  _showTranslation(text) {
    this.$(".tr").hidden = false;
    this._setArea(".trtext", text);
    this.$(".translate").textContent = "Перекласти ще раз";
  }

  async _translate() {
    const btn = this.$(".translate");
    const text = this.$(".text").value.trim();
    const msg = this.msg;
    if (!text) return;
    btn.disabled = true;
    this._status("Перекладаю…");
    try {
      const out = await translate(text);
      if (this.msg !== msg) return;
      if (this.full && text === (this.full.content || "").trim()) cacheSet(`tr:${msg.id}`, out);
      this._status("");
      this._showTranslation(out);
    } catch (e) {
      this._status(`Переклад не вдався: ${e?.message || e}`, true);
    } finally {
      btn.disabled = false;
    }
  }

  async _copy() {
    const m = this.msg;
    let text = `${m.topic}\n${m.sender} · ${fmtDate(m.date)}\n\n${this.$(".text").value}`;
    if (!this.$(".tr").hidden) text += `\n\n--- Переклад ---\n${this.$(".trtext").value}`;
    try {
      await navigator.clipboard.writeText(text);
      this._status("Скопійовано");
    } catch {
      this.$(".text").select();
      this._status("Виділено - скопіюйте вручну (Ctrl+C)");
    }
  }
}

if (!customElements.get("librus-message-reader-card")) {
  customElements.define("librus-message-reader-card", LibrusMessageReaderCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "librus-message-reader-card", name: "Librus letter reader",
    description: "Opens a letter clicked in the Librus messages card, with copy and Ukrainian translation (homeControll)" });
}

// Route clicks in the stock messages card to a reader card on the same view.
customElements.whenDefined("librus-messages-card").then(() => {
  const Card = customElements.get("librus-messages-card");
  const orig = Card.prototype._onMessageClick;
  if (!orig || Card.prototype.__hcReader) return;
  Card.prototype.__hcReader = true;
  Card.prototype._onMessageClick = function (msg) {
    const reader = [...READERS].find((r) => r.isConnected && r.offsetParent !== null);
    if (!reader) return orig.call(this, msg);
    const found = this._resolveEntities?.();
    reader.show(msg, found && !("error" in found) ? found.deviceId : undefined);
  };
});
