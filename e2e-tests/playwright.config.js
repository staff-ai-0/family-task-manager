module.exports = {
  testDir: './',
  testMatch: ['**/*.spec.js'],
  testIgnore: ['node_modules/**', 'debug-login.spec.js', 'screenshot.spec.js'],
  timeout: 30000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 1,
  reporter: [
    ['html'],
    ['list'],
    ['junit', { outputFile: 'test-results/results.xml' }],
  ],
  webServer: {
    command: 'npm run dev',
    port: 3003,
    timeout: 120000,
    reuseExistingServer: true,
  },
  use: {
    headless: true,
    viewport: { width: 1280, height: 720 },
    ignoreHTTPSErrors: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    baseURL: 'http://localhost:3003',
  },
};
