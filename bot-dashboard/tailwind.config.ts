import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#5b5fef",
          light: "#eef0ff",
          dark: "#4347c9",
        },
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f5f6fa",
          border: "#e8ecf3",
        },
        text: {
          primary: "#1a1d26",
          secondary: "#6b7280",
          muted: "#9ca3af",
        },
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
        cps: "#d70018",
      },
      boxShadow: {
        card: "0 1px 3px rgba(16,24,40,0.06), 0 1px 2px rgba(16,24,40,0.04)",
        cardHover: "0 4px 12px rgba(16,24,40,0.08)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
