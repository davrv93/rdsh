// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  use: {
    baseURL: process.env.OPTIMIZA_URL || 'http://localhost:8000',
    headless: true,
  },
  reporter: [['list']],
});
