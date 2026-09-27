// homeControll fixes for HA's built-in calendar card (hui-calendar-card),
// used on the Librus "Календар" tab (librus/build_dashboard.py).
//
// 1. The card switches to its phone header (_narrow, card < 870 px) only from
//    a ResizeObserver it attaches when connected - but on a fresh page load
//    ha-card is not rendered yet, so nothing is observed and a phone gets the
//    desktop header: the date range squeezed into a 4-line column in a huge
//    font. Attach it once ha-card exists.
// 2. `fill_screen: true` in the card config: the card ends at the bottom of
//    the screen, so a phone scrolls only the event list instead of the page
//    plus a fixed-height card (events below the card's fold went unnoticed).
customElements.whenDefined("hui-calendar-card").then(() => {
  const Card = customElements.get("hui-calendar-card");
  const updated = Card.prototype.updated;

  function fit(card) {
    const haCard = card.shadowRoot?.querySelector("ha-card");
    if (!haCard || !card.isConnected) return;
    const top = haCard.getBoundingClientRect().top + window.scrollY;
    haCard.style.height = `${Math.max(420, window.innerHeight - top - 16)}px`;
  }

  Card.prototype.updated = function (changed) {
    updated?.call(this, changed);
    if (this.__hcFixed || !this.shadowRoot?.querySelector("ha-card")) return;
    this.__hcFixed = true;
    this._attachObserver?.();
    this._measureCard?.();
    if (this._config?.fill_screen) {
      requestAnimationFrame(() => fit(this));
      window.addEventListener("resize", () => fit(this));
    }
  };
});
