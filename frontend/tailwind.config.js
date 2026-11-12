/** @type {import('tailwindcss').Config} */

module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Brand palette ────────────────────────────────────────────────
        // These used to be declared by OVERRIDING Tailwind's `blue` scale:
        //
        //     blue: { 600: "#eea73b", 700: "#4d669f", 800: "#3d5280" }
        //
        // so `bg-blue-600` rendered ORANGE. Only 600/700/800 were overridden,
        // while blue-50, blue-100, blue-500 and blue-900 stayed genuine
        // Tailwind blue — half the scale was brand colour, half was actually
        // blue, and nothing in the class name told you which.
        //
        // Named for what they are instead. The Tailwind `blue` scale is no
        // longer overridden and is genuinely blue at every shade.
        brand: {
          primary: "#1B52AE", //           deep blue   — primary actions
          "primary-dark": "#2258A7", //    darker blue — hover / active
          secondary: "#28ABDC", //         cyan        — secondary actions / accents
          "secondary-dark": "#2597C4", //  darker cyan — hover / active
        },

        // Retained: referenced as `primary` / `secondary` in existing markup.
        primary: "#1B52AE",
        secondary: "#28ABDC",
      },
    },
  },
};
