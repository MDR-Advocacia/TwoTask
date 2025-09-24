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
      },
      // ADIÇÃO: Definindo os keyframes para nossas animações
      keyframes: {
        'fade-in-down': {
          '0%': { opacity: '0', transform: 'translateY(-20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      // ADIÇÃO: Registrando as animações para que possamos usá-las com classes
      animation: {
        'fade-in-down': 'fade-in-down 0.8s ease-out forwards',
        'fade-in-up': 'fade-in-up 0.8s ease-out forwards',
      },
    },
  },
  plugins: [],
}