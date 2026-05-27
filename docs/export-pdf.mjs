/**
 * Exports manual-usuario.md to PDF using Playwright's bundled Chromium.
 * Usage: node docs/export-pdf.mjs
 */
import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dir = dirname(fileURLToPath(import.meta.url));
const mdPath = join(__dir, 'manual-usuario.md');
const outPath = join(__dir, 'manual-usuario.pdf');

// --- Minimal Markdown → HTML (tables, headings, code, bold, lists) ---
function mdToHtml(md) {
  let html = md
    // Escape for safety, then restore special patterns
    // Headings
    .replace(/^#{4} (.+)$/gm, '<h4>$1</h4>')
    .replace(/^#{3} (.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{2} (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Horizontal rule
    .replace(/^---$/gm, '<hr>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // Links (strip, keep text)
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

  // Tables
  const tableRe = /(\|.+\|\n)+/g;
  html = html.replace(tableRe, (block) => {
    const rows = block.trim().split('\n').filter(r => r.trim());
    const isSeparator = r => /^\|[\s|:-]+\|$/.test(r.trim());
    let out = '<table><tbody>';
    let firstDataRow = true;
    rows.forEach(row => {
      if (isSeparator(row)) return;
      const cells = row.split('|').slice(1, -1).map(c => c.trim());
      const tag = firstDataRow ? 'th' : 'td';
      out += '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
      firstDataRow = false;
    });
    out += '</tbody></table>';
    return out;
  });

  // Unordered list blocks
  html = html.replace(/(^[-*] .+\n?)+/gm, (block) => {
    const items = block.trim().split('\n').map(l => l.replace(/^[-*] /, '').trim());
    return '<ul>' + items.map(i => `<li>${i}</li>`).join('') + '</ul>';
  });

  // Ordered list blocks
  html = html.replace(/(^\d+\. .+\n?)+/gm, (block) => {
    const items = block.trim().split('\n').map(l => l.replace(/^\d+\. /, '').trim());
    return '<ol>' + items.map(i => `<li>${i}</li>`).join('') + '</ol>';
  });

  // Paragraphs: wrap remaining lines
  html = html
    .split('\n')
    .map(line => {
      if (!line.trim()) return '';
      if (/^<(h[1-6]|hr|ul|ol|li|table|blockquote|th|td|tr)/.test(line.trim())) return line;
      return `<p>${line}</p>`;
    })
    .join('\n');

  return html;
}

const md = readFileSync(mdPath, 'utf8');
const body = mdToHtml(md);

const pageHtml = `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 11pt;
    line-height: 1.65;
    color: #1a1a2e;
    padding: 0;
  }

  h1 {
    font-size: 22pt;
    font-weight: 700;
    color: #0f172a;
    margin: 24pt 0 8pt;
    page-break-after: avoid;
    border-bottom: 3px solid #3b82f6;
    padding-bottom: 6pt;
  }

  h2 {
    font-size: 15pt;
    font-weight: 700;
    color: #1e3a5f;
    margin: 20pt 0 6pt;
    page-break-after: avoid;
    border-left: 4px solid #3b82f6;
    padding-left: 10pt;
  }

  h3 {
    font-size: 12pt;
    font-weight: 600;
    color: #1e40af;
    margin: 14pt 0 4pt;
    page-break-after: avoid;
  }

  h4 {
    font-size: 11pt;
    font-weight: 600;
    color: #374151;
    margin: 10pt 0 3pt;
    page-break-after: avoid;
  }

  p { margin: 4pt 0 6pt; }

  strong { font-weight: 600; }

  code {
    font-family: 'Courier New', monospace;
    font-size: 9pt;
    background: #f1f5f9;
    padding: 1px 4px;
    border-radius: 3px;
    color: #be185d;
  }

  blockquote {
    border-left: 3px solid #94a3b8;
    padding: 6pt 10pt;
    margin: 8pt 0;
    background: #f8fafc;
    color: #475569;
    font-size: 10pt;
    border-radius: 0 4px 4px 0;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0 12pt;
    font-size: 10pt;
    page-break-inside: avoid;
  }

  th {
    background: #1e3a5f;
    color: #fff;
    font-weight: 600;
    padding: 6pt 8pt;
    text-align: left;
  }

  td {
    padding: 5pt 8pt;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: top;
  }

  tr:nth-child(even) td { background: #f8fafc; }

  ul, ol {
    padding-left: 18pt;
    margin: 4pt 0 8pt;
  }

  li { margin: 3pt 0; }

  hr {
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 16pt 0;
  }

  /* Cover-like first heading */
  body > h1:first-of-type {
    font-size: 26pt;
    text-align: center;
    border: none;
    padding: 30pt 0 10pt;
    color: #1e3a5f;
  }
</style>
</head>
<body>
${body}
</body>
</html>`;

// Find Playwright's bundled Chromium
const playwrightDir = join(
  dirname(fileURLToPath(import.meta.url)),
  '../e2e-tests/node_modules/playwright-core'
);

const browser = await chromium.launch({ executablePath: undefined });
const page = await browser.newPage();
await page.setContent(pageHtml, { waitUntil: 'networkidle' });
await page.pdf({
  path: outPath,
  format: 'A4',
  margin: { top: '20mm', right: '20mm', bottom: '20mm', left: '20mm' },
  printBackground: true,
});
await browser.close();

console.log(`PDF generado: ${outPath}`);
