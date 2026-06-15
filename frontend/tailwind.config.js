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
      },
    },
  },
  plugins: [],
}
