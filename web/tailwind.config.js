/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
  // Ant Design uses its own preflight, disable Tailwind's to avoid conflicts
  corePlugins: {
    preflight: false,
  },
}

