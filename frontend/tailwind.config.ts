import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        saffron: {
          50: "#fff7ec",
          100: "#ffe9c8",
          200: "#ffd28b",
          300: "#ffb04d",
          400: "#ff8d22",
          500: "#f56e0d",
          600: "#d85206",
          700: "#b33d09",
          800: "#90310f",
          900: "#762a10",
        },
        ink: {
          50: "#f6f6f7",
          100: "#e7e7ea",
          200: "#cfcfd5",
          300: "#a8a8b2",
          400: "#7a7a86",
          500: "#5b5b66",
          600: "#454550",
          700: "#363641",
          800: "#262630",
          900: "#16161e",
          950: "#0c0c14",
        },
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        serif: ["ui-serif", "Georgia", "Cambria", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
