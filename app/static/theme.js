// Runs in <head> before the first paint so the right theme shows at once.
// Choice ("auto" | "light" | "dark") lives in localStorage; "auto" follows Windows.
(function () {
  var root = document.documentElement;
  function choice() {
    try { return localStorage.getItem("studio-theme") || "auto"; } catch (e) { return "auto"; }
  }
  function apply() {
    var c = choice();
    var dark = c === "dark" || (c === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "dark" : "light";
    root.dataset.themePref = c;  // not "themeChoice": the Settings buttons use data-theme-choice
  }
  window.studioTheme = {
    get: choice,
    set: function (c) {
      try { localStorage.setItem("studio-theme", c); } catch (e) { /* private mode: keep for this page */ }
      apply();
    },
  };
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
  apply();
})();
