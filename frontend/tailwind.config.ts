import type { Config } from "tailwindcss";

// ── oklch() color helper ──────────────────────────────────────────────────────
// CSS color variables in globals.css store raw OKLCH channel triplets (L C H)
// WITHOUT the oklch() wrapper, e.g. "--primary: 0.62 0.22 264".
//
// This factory wraps them so Tailwind v3 opacity modifiers work correctly:
//   bg-primary      → background-color: oklch(var(--primary))
//   bg-primary/10   → background-color: oklch(var(--primary) / 0.1)
//
// --border and --input have a companion --xxx-alpha variable that holds the
// default transparency (dark: 0.1 / 0.15). When no modifier is given, the
// function falls back to that alpha so borders render at the correct opacity.
// ─────────────────────────────────────────────────────────────────────────────
function oklchVar(variable: string, defaultAlpha = "1") {
  const alphaVar = variable.endsWith("border")
    ? "--border-alpha"
    : variable.endsWith("input")
    ? "--input-alpha"
    : null;

  return ({ opacityValue }: { opacityValue?: string } = {}) => {
    if (opacityValue !== undefined) {
      return `oklch(var(${variable}) / ${opacityValue})`;
    }
    if (alphaVar) {
      return `oklch(var(${variable}) / var(${alphaVar}, ${defaultAlpha}))`;
    }
    return `oklch(var(${variable}))`;
  };
}

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      fontFamily: {
        display: ["var(--font-sora)", "sans-serif"],
        sans:    ["var(--font-jakarta)", "sans-serif"],
      },
      colors: {
        // ── shadcn v4 colors ─────────────────────────────────────────────────
        // Variables hold raw "L C H" channels. The oklchVar() helper wraps them
        // so opacity modifiers (bg-primary/10 etc.) generate valid CSS:
        //   oklch(var(--primary) / 0.1) = oklch(0.62 0.22 264 / 0.1)
        border:     oklchVar("--border"),
        input:      oklchVar("--input"),
        ring:       oklchVar("--ring"),
        background: oklchVar("--background"),
        foreground: oklchVar("--foreground"),
        primary: {
          DEFAULT:    oklchVar("--primary"),
          foreground: oklchVar("--primary-foreground"),
        },
        secondary: {
          DEFAULT:    oklchVar("--secondary"),
          foreground: oklchVar("--secondary-foreground"),
        },
        destructive: {
          DEFAULT:    oklchVar("--destructive"),
          foreground: oklchVar("--destructive-foreground"),
        },
        muted: {
          DEFAULT:    oklchVar("--muted"),
          foreground: oklchVar("--muted-foreground"),
        },
        accent: {
          DEFAULT:    oklchVar("--accent"),
          foreground: oklchVar("--accent-foreground"),
        },
        popover: {
          DEFAULT:    oklchVar("--popover"),
          foreground: oklchVar("--popover-foreground"),
        },
        card: {
          DEFAULT:    oklchVar("--card"),
          foreground: oklchVar("--card-foreground"),
        },
        surface: {
          DEFAULT: oklchVar("--surface"),
          elevated: oklchVar("--surface-elevated"),
        },
        // Amber stays as hardcoded hex — used for hover/accent effects
        amber: {
          50:  "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to:   { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to:   { height: "0" },
        },
        shimmer: {
          from: { backgroundPosition: "0 0" },
          to:   { backgroundPosition: "-200% 0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        pulse: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.4" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up":   "accordion-up 0.2s ease-out",
        shimmer:   "shimmer 2s linear infinite",
        "fade-in": "fade-in 0.3s ease-out",
        pulse:     "pulse 2s cubic-bezier(0.4,0,0.6,1) infinite",
      },
    },
  },
  plugins: [
    require("tailwindcss-animate"),
    // ── shadcn data-state variants ──────────────────────────────────────────
    // shadcn v4 components use data-open: / data-closed: / data-disabled: etc.
    // as Tailwind variants. In Tailwind v3 these require explicit registration.
    // (In Tailwind v4 they'd come from shadcn/tailwind.css @custom-variant rules,
    // but those are v4-only and break v3 PostCSS processing entirely.)
    function ({ addVariant }: { addVariant: (name: string, definition: string | string[]) => void }) {
      addVariant("data-open",    ['&[data-state="open"]',   '&[data-open]']);
      addVariant("data-closed",  ['&[data-state="closed"]', '&[data-closed]']);
      addVariant("data-checked", ['&[data-state="checked"]']);
      addVariant("data-placeholder",  ["&[data-placeholder]"]);
      addVariant("data-disabled",     ["&[data-disabled]"]);
      addVariant("not-data-disabled", ["&:not([data-disabled])"]);
      addVariant("data-inset",        ["&[data-inset]"]);
      addVariant("data-align-trigger",["&[data-align-trigger]"]);
    },
  ],
};

export default config;
