import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

export type RGB = [number, number, number];

export interface HeatTheme {
  id: string;
  name: string;
  /** low-score → high-score, light → dark. Each ramp validated as an ordinal
   * ramp on the dark panel surface via the dataviz palette checker. */
  stops: RGB[];
}

export const HEAT_THEMES: HeatTheme[] = [
  { id: "blue", name: "Blue", stops: [[183, 211, 246], [109, 167, 236], [42, 120, 214], [24, 79, 149]] },
  { id: "green", name: "Green", stops: [[168, 230, 207], [92, 201, 154], [27, 175, 122], [18, 122, 86]] },
  { id: "amber", name: "Amber", stops: [[246, 213, 138], [230, 168, 63], [201, 130, 42], [143, 87, 22]] },
  { id: "purple", name: "Purple", stops: [[207, 200, 245], [167, 155, 240], [125, 110, 222], [85, 68, 184]] },
];

const DEFAULT_THEME = HEAT_THEMES[0];
const STORAGE_KEY = "tfm.heatTheme";

export function themeById(id: string): HeatTheme {
  return HEAT_THEMES.find((t) => t.id === id) ?? DEFAULT_THEME;
}

/** Interpolate a score (0-100) into the theme's ramp, returning an `rgb(...)` string. */
export function scoreToColor(score: number, theme: HeatTheme): string {
  const stops = theme.stops;
  const t = (Math.max(0, Math.min(100, score)) / 100) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  const frac = t - i;
  const [r1, g1, b1] = stops[i];
  const [r2, g2, b2] = stops[i + 1];
  const r = Math.round(r1 + (r2 - r1) * frac);
  const g = Math.round(g1 + (g2 - g1) * frac);
  const b = Math.round(b1 + (b2 - b1) * frac);
  return `rgb(${r}, ${g}, ${b})`;
}

/** Pick readable text (near-black vs near-white) for a given cell background,
 * using WCAG relative luminance — so text stays legible on any theme/score. */
export function readableTextColor(score: number, theme: HeatTheme): string {
  const stops = theme.stops;
  const t = (Math.max(0, Math.min(100, score)) / 100) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  const frac = t - i;
  const rgb = stops[i].map((c, k) => c + (stops[i + 1][k] - c) * frac) as RGB;
  const lin = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  return luminance > 0.45 ? "#0b0e14" : "#f4f6fb";
}

export function cssGradient(theme: HeatTheme): string {
  return `linear-gradient(90deg, ${theme.stops.map((c) => `rgb(${c.join(",")})`).join(", ")})`;
}

interface HeatThemeContextValue {
  theme: HeatTheme;
  setThemeId: (id: string) => void;
}

const HeatThemeContext = createContext<HeatThemeContextValue>({
  theme: DEFAULT_THEME,
  setThemeId: () => {},
});

export function HeatThemeProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<string>(() => localStorage.getItem(STORAGE_KEY) ?? DEFAULT_THEME.id);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, id);
  }, [id]);

  const value: HeatThemeContextValue = { theme: themeById(id), setThemeId: setId };
  return createElement(HeatThemeContext.Provider, { value }, children);
}

export function useHeatTheme(): HeatThemeContextValue {
  return useContext(HeatThemeContext);
}
