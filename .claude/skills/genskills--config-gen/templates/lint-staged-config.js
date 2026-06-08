module.exports = {
  '*.{ts,tsx}': [
    'eslint --fix --max-warnings 0',
    'prettier --write',
    () => 'tsc --noEmit'  // Run typecheck on entire project, not per-file
  ],
  '*.{js,jsx,mjs,cjs}': [
    'eslint --fix --max-warnings 0',
    'prettier --write'
  ],
  '*.{css,scss}': [
    'stylelint --fix',
    'prettier --write'
  ],
  '*.{json,md,yml,yaml}': [
    'prettier --write'
  ],
  '*.{png,jpeg,jpg,gif,svg}': [
    'imagemin-lint-staged'  // Only if image optimization is configured
  ]
}
