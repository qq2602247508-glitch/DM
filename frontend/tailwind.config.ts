import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#090b0f",
          900: "#0f1319",
          850: "#131923",
          800: "#171d25",
          750: "#1d2430",
          700: "#252d38",
          600: "#33404e",
        },
        ember: {
          200: "#eed3a4",
          300: "#e1b875",
          400: "#c8954c",
          500: "#a97132",
          600: "#8a5727",
        },
        parchment: {
          100: "#ece6d8",
          200: "#d8d0bd",
          300: "#b9b09b",
        },
      },
      boxShadow: {
        panel: "0 14px 40px rgba(0, 0, 0, 0.32)",
        inset: "inset 0 1px 0 rgba(236, 230, 216, 0.04)",
      },
      fontFamily: {
        display: ["Georgia", "Cambria", "Times New Roman", "serif"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
} satisfies Config;
