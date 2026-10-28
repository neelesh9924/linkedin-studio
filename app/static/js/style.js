// Post style: the three sliders (Hook, Tone, Emojis), the same in Settings › Post style and in a post's Style panel.
// Their ranges and what each step is called come from the studio (/api/style, app/style.py), the same words the
// writer is given, so the page and the runs never drift apart.
import { h } from "./core.js";

const TITLES = { hook: "Hook", tone: "Tone", emojis: "Emojis" };
export const ALWAYS = "Always professional: no slang, clickbait or hype words.";

// The sliders for `values` (`info` is /api/style's answer: the ranges, the step names and the owner's default), ids starting with `id`. Each says its step in words beside its name, and to a screen reader
// (aria-valuetext); `onInput` gets all three after every move. `set` moves them all at once (Studio default).
export function styleSliders(info, values, id, onInput = () => {}) {
  const now = { ...values };
  const inputs = {};
  const rows = Object.entries(info.sliders).map(([name, [low, high]]) => {
    const words = info.labels[name];
    const input = h("input", { class: "slider", type: "range", id: `${id}-${name}`, min: low, max: high, step: 1, value: now[name],
      "aria-valuetext": words[now[name]], "data-keep": `${id}-${name}` });
    const said = h("output", { class: "slider-now", for: `${id}-${name}`, "aria-hidden": "true" }, words[now[name]]);
    const show = () => {
      said.textContent = words[now[name]];
      input.setAttribute("aria-valuetext", words[now[name]]);
    };
    input.addEventListener("input", () => {
      now[name] = Number(input.value);
      show();
      onInput({ ...now });
    });
    inputs[name] = { input, show };
    return h("div", { class: "slider-row" },
      h("div", { class: "slider-head" }, h("label", { class: "slider-name", for: `${id}-${name}` }, TITLES[name]), said),
      h("span", { class: "slider-end", "aria-hidden": "true" }, words[low]), input,
      h("span", { class: "slider-end", "aria-hidden": "true" }, words[high]));
  });
  return {
    element: h("div", { class: "sliders" }, rows),
    values: () => ({ ...now }),
    set(next) {
      for (const [name, { input, show }] of Object.entries(inputs)) {
        now[name] = next[name];
        input.value = next[name];
        show();
      }
      onInput({ ...now });
    },
  };
}
