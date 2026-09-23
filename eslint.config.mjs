// The page is plain browser JavaScript with no build step.  These rules catch the
// kind of bug that has bitten it before: a var reused inside one function.
//   npx eslint@9 app/static/app.js
export default [
  {
    files: ['app/static/app.js'],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'script',
      globals: {
        window: 'readonly', document: 'readonly', navigator: 'readonly', localStorage: 'readonly',
        sessionStorage: 'readonly',
        fetch: 'readonly', setTimeout: 'readonly', setInterval: 'readonly', clearTimeout: 'readonly',
        clearInterval: 'readonly',
        requestAnimationFrame: 'readonly', cancelAnimationFrame: 'readonly', confirm: 'readonly', prompt: 'readonly',
        Event: 'readonly', FormData: 'readonly', Path2D: 'readonly', MediaMetadata: 'readonly',
        ABCJS: 'readonly', console: 'readonly'
      }
    },
    rules: {
      'no-redeclare': 'error',
      'no-shadow': ['error', { builtinGlobals: false }],
      'no-undef': 'error',
      'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none' }],
      'block-scoped-var': 'error'
    }
  }
];
