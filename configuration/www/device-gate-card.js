// custom:device-gate-card — shows its cards only to selected users, and in
// the Companion app only on selected phones. Several phones share the yurii
// account, so the user condition alone is not enough: the current session's
// refresh token (auth/refresh_tokens, is_current) identifies the device.
//
//   type: custom:device-gate-card
//   users: [<user id>, ...]        # who may see the cards at all
//   app_tokens: [<token id>, ...]  # Companion app sessions allowed to see;
//                                  # browsers of the listed users always see
//   cards: [...]
//
// Hidden until the check succeeds (fails closed).
(() => {
  const APP_CLIENT = /^https:\/\/home-assistant\.io\//;
  let currentToken; // promise of the current refresh token, one per page

  const getCurrentToken = (hass) => {
    if (!currentToken) {
      currentToken = hass.connection
        .sendMessagePromise({ type: "auth/refresh_tokens" })
        .then((tokens) => tokens.find((t) => t.is_current) || null)
        .catch(() => {
          currentToken = undefined;
          return null;
        });
    }
    return currentToken;
  };

  class DeviceGateCard extends HTMLElement {
    setConfig(config) {
      if (!Array.isArray(config.cards)) throw new Error("cards is required");
      this._config = config;
      this._allowed = false;
      this._checked = false;
      this.style.display = "none";
      this._card = null;
    }

    set hass(hass) {
      this._hass = hass;
      if (this._card) this._card.hass = hass;
      if (!this._checked) {
        this._checked = true;
        this._check(hass);
      }
    }

    async _check(hass) {
      const { users = [], app_tokens = [] } = this._config;
      if (!hass.user || !users.includes(hass.user.id)) return;
      const token = await getCurrentToken(hass);
      if (!token) {
        this._checked = false; // retry on the next hass update
        return;
      }
      if (APP_CLIENT.test(token.client_id || "") && !app_tokens.includes(token.id)) return;
      await this._show();
    }

    async _show() {
      const helpers = await window.loadCardHelpers();
      this._card = helpers.createCardElement({
        type: "vertical-stack",
        cards: this._config.cards,
      });
      this._card.hass = this._hass;
      this.replaceChildren(this._card);
      this.style.display = "";
    }

    getCardSize() {
      return this._card && this._card.getCardSize ? this._card.getCardSize() : 0;
    }
  }

  customElements.define("device-gate-card", DeviceGateCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "device-gate-card",
    name: "Device gate",
    description: "Shows cards only to selected users / Companion app devices",
  });
})();
