import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    allowedHosts: ["family.agent-ia.mx", "localhost", "127.0.0.1", "0.0.0.0"],
  },
});