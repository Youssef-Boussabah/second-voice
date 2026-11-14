/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#FBF7F1",
        ink: "#1F1B16",
        muted: "#5E554A",
        line: "#E4DACB",
        clay: { DEFAULT: "#B4532A", dark: "#8F3F1E", soft: "#F6E4D9" },
        sage: { DEFAULT: "#3F6F5A", soft: "#E3EFE8" },
        lock: { DEFAULT: "#5B4B8A", soft: "#ECE8F6" },
      },
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "system-ui", "sans-serif"],
      },
      keyframes: {
        speak: { "0%,100%": { boxShadow: "0 0 0 0 rgba(63,111,90,.45)" }, "50%": { boxShadow: "0 0 0 14px rgba(63,111,90,0)" } },
        fadein: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { speak: "speak 1.2s ease-in-out infinite", fadein: "fadein .25s ease-out" },
    },
  },
  plugins: [],
};
