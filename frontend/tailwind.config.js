/** @type {import('tailwindcss').Config} */
// Second Voice design tokens. One accent per meaning:
//   voice (teal)  = speaking / the user's own voice      lock (violet) = privacy rules
//   clay (warm)   = brand + primary actions              amber          = needs attention
// All text colours meet WCAG AA on canvas and surface (muted ≈ 6.6:1 on white).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F5F3EE",
        surface: "#FFFFFF",
        paper: "#F5F3EE",
        ink: { DEFAULT: "#1A1A1F", soft: "#2B2A31" },
        muted: "#55535D",
        line: { DEFAULT: "#E6E1D8", strong: "#D3CCBF" },
        clay: { DEFAULT: "#B9502A", dark: "#93401F", soft: "#FBEAE1" },
        voice: { DEFAULT: "#0F766E", dark: "#0B5D57", soft: "#E2F3F0" },
        sage: { DEFAULT: "#0F766E", soft: "#E2F3F0" },
        lock: { DEFAULT: "#5B4B8A", dark: "#46396D", soft: "#EFEBF9" },
        amber: { DEFAULT: "#8A5A00", soft: "#FFF3D6", line: "#F1D58F" },
        danger: { DEFAULT: "#B42318", soft: "#FDECEA" },
      },
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(26,26,31,.05), 0 10px 28px -14px rgba(26,26,31,.16)",
        lift: "0 2px 6px rgba(26,26,31,.06), 0 22px 44px -18px rgba(26,26,31,.28)",
        inset: "inset 0 0 0 1px rgba(26,26,31,.06)",
      },
      borderRadius: { "4xl": "28px" },
      keyframes: {
        speak: { "0%,100%": { boxShadow: "0 0 0 0 rgba(15,118,110,.35)" }, "50%": { boxShadow: "0 0 0 10px rgba(15,118,110,0)" } },
        fadein: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        pop: { "0%": { opacity: "0", transform: "scale(.97)" }, "100%": { opacity: "1", transform: "none" } },
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        bar: { "0%,100%": { transform: "scaleY(.35)" }, "50%": { transform: "scaleY(1)" } },
        dot: { "0%,80%,100%": { opacity: ".25" }, "40%": { opacity: "1" } },
      },
      animation: {
        speak: "speak 1.4s ease-in-out infinite",
        fadein: "fadein .28s cubic-bezier(.2,.8,.2,1) both",
        pop: "pop .22s cubic-bezier(.2,.8,.2,1) both",
        shimmer: "shimmer 1.4s linear infinite",
        bar: "bar .9s ease-in-out infinite",
        dot: "dot 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
