module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'scope-enum': [2, 'always', [
      // Auto-populated from monorepo package names or project directories
    ]],
    'scope-empty': [1, 'never'],
    'subject-case': [2, 'never', ['start-case', 'pascal-case', 'upper-case']],
    'body-max-line-length': [1, 'always', 200],
    'header-max-length': [2, 'always', 100]
  }
}
