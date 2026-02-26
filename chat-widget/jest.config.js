module.exports = {
  testEnvironment: 'jsdom',
  testMatch: ['<rootDir>/tests/**/*.test.js'],
  testPathIgnorePatterns: ['integration/'],
  globals: { '__AI_CHAT_TEST': true },
  setupFiles: ['<rootDir>/tests/setup.js'],
};
