module.exports = {
  apps: [{
    name: '<name>',
    script: 'dist/index.js',
    instances: 'max',
    exec_mode: 'cluster',
    env: { NODE_ENV: 'development' },
    env_production: { NODE_ENV: 'production' },
    max_memory_restart: '500M',
    error_file: 'logs/error.log',
    out_file: 'logs/output.log',
    merge_logs: true,
  }],
};
