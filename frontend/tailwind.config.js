/**
 * The palette is sampled from the official SightOps logo
 * (navy #051D35, #053B6E and blue #075CA7 dominate it). Amber is the accent the
 * product brief asks for and is reserved for warnings and the primary call to
 * action so it keeps its meaning.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#051D35",
          deep: "#03121F",
          mid: "#053B6E",
          soft: "#0A4B87"
        },
        brand: {
          DEFAULT: "#075CA7",
          light: "#3B8FD4",
          pale: "#E8F1FA"
        },
        slate: { DEFAULT: "#3E4D5C" },
        mist: { DEFAULT: "#D4DADF" },
        ink: { DEFAULT: "#0B1626" },
        amber: { DEFAULT: "#FF7A1A", dark: "#D95F00" },
        good: { DEFAULT: "#2E9E5B" },
        bad: { DEFAULT: "#D13B3B" }
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif"
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"]
      },
      boxShadow: {
        panel: "0 1px 2px rgba(5, 29, 53, 0.06), 0 8px 24px rgba(5, 29, 53, 0.08)"
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(2px)" },
          to: { opacity: "1", transform: "none" }
        }
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out"
      }
    }
  },
  plugins: []
};
