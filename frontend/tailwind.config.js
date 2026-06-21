/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        app: "#050506",
        panel: "#0d0d10",
        soft: "#151519",
        line: "#26262b",
        muted: "#9a9aa1",
        // accent neutro (no lugar do rosa): branco-gelo + cinza claro
        accent: "#f4f4f5",
        "accent-dim": "#d4d4d8",
      },
      boxShadow: {
        glow: "0 10px 34px -14px rgba(255,255,255,0.22)",
        card: "0 2px 14px -8px rgba(0,0,0,0.8)",
      },
      backgroundImage: {
        "fade-app":
          "linear-gradient(to top, #050506 8%, rgba(5,5,6,0.72) 46%, rgba(5,5,6,0) 100%)",
      },
    },
  },
  plugins: [],
}
