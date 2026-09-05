import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}", "../../packages/ui/src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      colors: {
        canvas: "#e8eef8",
        ink: "#0f172a",
        navy: "#1e3a5f",
        ivory: "#0f172a",
        azure: {
          DEFAULT: "#2563eb",
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          600: "#2563eb",
          700: "#1d4ed8",
        },
        brand: {
          DEFAULT: "#0f766e",
          50: "#f0fdfa",
          100: "#ccfbf1",
          200: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
        },
        gold: {
          DEFAULT: "#0f766e",
          200: "#14b8a6",
        },
        mint: "#0f766e",
      },
      boxShadow: {
        lift: "0 18px 44px rgba(30, 58, 95, 0.12)",
        glass: "0 1px 0 rgba(255,255,255,0.75) inset, 0 16px 40px rgba(30, 58, 95, 0.1)",
      },
    },
  },
  plugins: [],
};

export default config;
