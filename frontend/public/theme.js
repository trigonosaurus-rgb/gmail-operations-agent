// Runs before the first paint, so a dark-theme visitor never sees a white flash.
// A separate file, not an inline script: the CSP allows scripts from 'self' only.
try {
  var saved = localStorage.getItem('theme')
  var dark = saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark', dark)
} catch {}
