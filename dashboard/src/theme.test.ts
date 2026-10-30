import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { money, waited } from "./format";

const css = readFileSync(join(__dirname, "theme.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const pairs = body
    .split(";")
    .map((line) => line.split(":").map((part) => part.trim()))
    .filter((pair) => pair[0]?.startsWith("--") && pair[1]?.startsWith("#"));
  return Object.fromEntries(
    pairs.map((pair) => [pair[0], (pair[1] ?? "").toLowerCase()]),
  );
}

function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const light = Math.max(luminance(a), luminance(b));
  const dark = Math.min(luminance(a), luminance(b));
  return (light + 0.05) / (dark + 0.05);
}

const dark = block(":root");
const light = { ...dark, ...block('[data-theme="light"]') };

it("gives every chip AA contrast in both themes", () => {
  const chips = Object.keys(dark).filter((k) => k.endsWith("-bg"));
  expect(chips.length).toBeGreaterThanOrEqual(8);
  for (const theme of [dark, light]) {
    for (const bg of chips) {
      const fg = bg.replace(/-bg$/, "-fg");
      expect(
        contrast(theme[bg] ?? "", theme[fg] ?? ""),
        bg,
      ).toBeGreaterThanOrEqual(4.5);
    }
  }
});

it("gives text AA contrast on its surfaces in both themes", () => {
  for (const theme of [dark, light]) {
    for (const surface of ["--page", "--panel", "--raised", "--card"]) {
      for (const text of ["--ink", "--ink-muted", "--ultraviolet-text"]) {
        expect(
          contrast(theme[surface] ?? "", theme[text] ?? ""),
          `${text} on ${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  }
});

it("has no one-edge borders", () => {
  expect(css).not.toMatch(/border-(top|left|right|bottom)/);
});

it("formats money and waits", () => {
  expect(money(1250)).toBe("$1,250.00");
  const now = new Date("2026-10-30T10:00:00Z");
  expect(waited("2026-10-30T09:15:00Z", now)).toBe("45 min");
  expect(waited("2026-10-30T07:55:00Z", now)).toBe("2 h 5 min");
});

it("stops the mic pulse and level bar under reduced motion", () => {
  const start = css.indexOf("@media (prefers-reduced-motion: reduce)");
  const block = css.slice(start, css.indexOf("@media (max-width", start));
  expect(block).toContain(".mic-listening");
  expect(block).toContain(".level");
  expect(block).toContain("animation: none");
});
