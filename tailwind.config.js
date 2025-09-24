/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './app/**/*.py'
  ],
  theme: {
    extend: {
      colors: {
        beige: {
          100: '#F5F5DC', // Um bege bem claro
          200: '#EFEBE0', // Um bege suave para texto
          300: '#D2B48C', // Tan/Bege para acentos
        },
      }
    },
  },
  plugins: [],
}