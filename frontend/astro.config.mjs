import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import node from '@astrojs/node';

// Remark plugin: rewrite ```mermaid fenced code blocks into a raw
// <pre class="mermaid"> node BEFORE Shiki highlighting runs. The guide pages
// (/help, /ayuda) then render them client-side via mermaid.js in GuideShell.
// Without this, Astro/Shiki emits the diagram source as plain text.
function escapeHtml(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
function remarkMermaid() {
  return (tree) => {
    const walk = (node) => {
      if (!node || !Array.isArray(node.children)) return;
      node.children = node.children.map((child) => {
        if (child.type === 'code' && child.lang === 'mermaid') {
          return {
            type: 'html',
            value: `<pre class="mermaid">${escapeHtml(child.value)}</pre>`,
          };
        }
        walk(child);
        return child;
      });
    };
    walk(tree);
  };
}

// https://astro.build/config
export default defineConfig({
  output: 'server',
  // Canonical production origin — enables absolute URLs for SEO (canonical,
  // hreflang, Open Graph, sitemap). Mirrors lib/seo.ts SITE_URL.
  site: 'https://family.agent-ia.mx',
  markdown: {
    remarkPlugins: [remarkMermaid],
  },
  adapter: node({
    mode: 'standalone',
  }),
  devToolbar: {
    enabled: false,
  },
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
