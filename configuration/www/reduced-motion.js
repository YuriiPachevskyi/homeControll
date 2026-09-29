// Report prefers-reduced-motion as on inside HA, so the frontend charts
// (ha-chart-base sets `animation: !reducedMotion`) render without the
// intro animation. Affects only this HA frontend, not the device settings.
(() => {
  const origMatchMedia = window.matchMedia.bind(window);
  window.matchMedia = (query) =>
    typeof query === "string" && query.includes("prefers-reduced-motion")
      ? origMatchMedia("all")
      : origMatchMedia(query);
})();
