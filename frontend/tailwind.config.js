/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Plus Jakarta Sans"',
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "sans-serif",
        ],
        display: ["'Outfit'", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
      },
      colors: {
        surface: {
          950: "#060a0f",
          900: "#0b0f18",
          800: "#111827",
          750: "#141d2e",
          700: "#1a2438",
          600: "#22304a",
          500: "#2a3c5c",
        },
        accent: {
          DEFAULT: "#2ee6a8",
          dim: "#1a9170",
          glow: "#5fffcb",
          muted: "#1de09e33",
        },
        neural: {
          DEFAULT: "#818cf8",
          dim: "#4f46e5",
          glow: "#a5b4fc",
          muted: "#818cf820",
        },
        pulse: {
          DEFAULT: "#f59e0b",
          glow: "#fbbf24",
          muted: "#f59e0b20",
        },
        danger: {
          DEFAULT: "#f87171",
          glow: "#fca5a5",
        },
      },
      boxShadow: {
        panel: "0 24px 80px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.04)",
        inset: "inset 0 1px 0 rgba(255,255,255,0.06)",
        glow: "0 0 24px rgba(46,230,168,0.25), 0 0 48px rgba(46,230,168,0.10)",
        "glow-neural": "0 0 24px rgba(129,140,248,0.25), 0 0 48px rgba(129,140,248,0.10)",
        "glow-sm": "0 0 12px rgba(46,230,168,0.30)",
        card: "0 4px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.05)",
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "neural-grid":
          "linear-gradient(rgba(46,230,168,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(46,230,168,0.03) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "40px 40px",
      },
      keyframes: {
        aurora: {
          "0%, 100%": { opacity: "0.6", transform: "scale(1) translate(0%, 0%)" },
          "33%": { opacity: "0.9", transform: "scale(1.05) translate(2%, -2%)" },
          "66%": { opacity: "0.7", transform: "scale(0.97) translate(-1%, 1%)" },
        },
        "aurora-2": {
          "0%, 100%": { opacity: "0.4", transform: "scale(1) translate(0%, 0%)" },
          "50%": { opacity: "0.8", transform: "scale(1.08) translate(-3%, 2%)" },
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 8px rgba(46,230,168,0.3)" },
          "50%": { boxShadow: "0 0 20px rgba(46,230,168,0.7), 0 0 40px rgba(46,230,168,0.3)" },
        },
        "live-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.7)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "slide-in-left": {
          "0%": { opacity: "0", transform: "translateX(-12px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "slide-in-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "scan": {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
        "thinking-dot": {
          "0%, 80%, 100%": { transform: "scale(0)", opacity: "0.3" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
        "bar-rise": {
          "0%": { transform: "scaleY(0.3)" },
          "50%": { transform: "scaleY(1)" },
          "100%": { transform: "scaleY(0.3)" },
        },
      },
      animation: {
        aurora: "aurora 12s ease-in-out infinite",
        "aurora-2": "aurora-2 18s ease-in-out infinite",
        "glow-pulse": "glow-pulse 2.5s ease-in-out infinite",
        "live-dot": "live-dot 1.8s ease-in-out infinite",
        shimmer: "shimmer 2.2s linear infinite",
        "slide-in-left": "slide-in-left 0.3s ease-out",
        "slide-in-up": "slide-in-up 0.25s ease-out",
        "fade-in": "fade-in 0.4s ease-out",
        "thinking-dot": "thinking-dot 1.4s ease-in-out infinite",
        "bar-rise": "bar-rise 1.2s ease-in-out infinite",
      },
      transitionTimingFunction: {
        "in-expo": "cubic-bezier(0.95, 0.05, 0.795, 0.035)",
        "out-expo": "cubic-bezier(0.19, 1, 0.22, 1)",
      },
    },
  },
  plugins: [],
};
