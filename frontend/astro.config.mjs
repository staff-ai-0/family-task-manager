import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import node from '@astrojs/node';

// https://astro.build/config
export default defineConfig({
  output: 'server',
  adapter: node({
    mode: 'standalone',
  }),
  security: {
    // Disable origin check for CSRF — the app runs behind a reverse proxy
    // (e.g. https://fam-stage.a-ai4all.com -> localhost:3000) so the Origin
    // header never matches the internal host. Auth is handled via JWT tokens.
    checkOrigin: false,
  },
  vite: {
    plugins: [tailwindcss()],
  },
  server: {
    port: 3000,
    host: true,
    allowedHosts: ["family.agent-ia.mx", "localhost", "127.0.0.1", "0.0.0.0"],
  }
});
