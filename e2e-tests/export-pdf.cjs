/**
 * Exports ../docs/manual-usuario.md to PDF using Playwright's bundled Chromium.
 * Run from e2e-tests/: node export-pdf.cjs
 */
const { chromium } = require('playwright');
const { readFileSync } = require('fs');
const path = require('path');

const mdPath = path.join(__dirname, '../docs/manual-usuario.md');
const outPath = path.join(__dirname, '../docs/manual-usuario.pdf');

function mdToHtml(md) {
  let html = md
    .replace(/^#{4} (.+)$/gm, '<h4>$1</h4>')
    .replace(/^#{3} (.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{2} (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/^---$/gm, '<hr>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

  // Tables
  html = html.replace(/(\|.+\|\n)+/g, (block) => {
    const rows = block.trim().split('\n').filter(r => r.trim());
    const isSep = r => /^\|[\s|:-]+\|$/.test(r.trim());
    let out = '<table><tbody>';
    let first = true;
    rows.forEach(row => {
      if (isSep(row)) return;
      const cells = row.split('|').slice(1, -1).map(c => c.trim());
      const tag = first ? 'th' : 'td';
      out += '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
      first = false;
    });
    return out + '</tbody></table>';
  });

  // Lists
  html = html.replace(/(^[-*] .+\n?)+/gm, block => {
    const items = block.trim().split('\n').map(l => l.replace(/^[-*] /, '').trim());
    return '<ul>' + items.map(i => `<li>${i}</li>`).join('') + '</ul>';
  });
  html = html.replace(/(^\d+\. .+\n?)+/gm, block => {
    const items = block.trim().split('\n').map(l => l.replace(/^\d+\. /, '').trim());
    return '<ol>' + items.map(i => `<li>${i}</li>`).join('') + '</ol>';
  });

  // Paragraphs
  const blockTags = /^<(h[1-6]|hr|ul|ol|li|table|blockquote|tbody|tr|th|td)/;
  html = html.split('\n').map(line => {
    if (!line.trim()) return '';
    if (blockTags.test(line.trim())) return line;
    return `<p>${line}</p>`;
  }).join('\n');

  return html;
}

const CSS = `
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  font-size: 10.5pt;
  line-height: 1.6;
  color: #1a1a2e;
}
h1 {
  font-size: 22pt; font-weight: 700; color: #0f172a;
  margin: 22pt 0 8pt;
  border-bottom: 3px solid #2563eb;
  padding-bottom: 6pt;
  page-break-after: avoid;
}
h2 {
  font-size: 14pt; font-weight: 700; color: #1e3a5f;
  margin: 18pt 0 5pt;
  border-left: 4px solid #2563eb;
  padding-left: 9pt;
  page-break-after: avoid;
}
h3 {
  font-size: 11.5pt; font-weight: 600; color: #1e40af;
  margin: 13pt 0 4pt;
  page-break-after: avoid;
}
h4 {
  font-size: 10.5pt; font-weight: 600; color: #374151;
  margin: 9pt 0 3pt;
  page-break-after: avoid;
}
p { margin: 3pt 0 5pt; }
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
  padding: 5pt 10pt;
  margin: 7pt 0;
  background: #f8fafc;
  color: #475569;
  font-size: 9.5pt;
  border-radius: 0 4px 4px 0;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 8pt 0 11pt;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
th {
  background: #1e3a5f;
  color: #fff;
  font-weight: 600;
  padding: 5pt 8pt;
  text-align: left;
}
td {
  padding: 4pt 8pt;
  border-bottom: 1px solid #e2e8f0;
  vertical-align: top;
}
tr:nth-child(even) td { background: #f8fafc; }
ul, ol { padding-left: 16pt; margin: 3pt 0 7pt; }
li { margin: 2pt 0; }
hr { border: none; border-top: 1px solid #cbd5e1; margin: 14pt 0; }
`;

async function run() {
  const md = readFileSync(mdPath, 'utf8');
  const body = mdToHtml(md);
  const pageHtml = `<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><style>${CSS}</style></head>
<body>${body}</body></html>`;

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setContent(pageHtml, { waitUntil: 'networkidle' });
  await page.pdf({
    path: outPath,
    format: 'A4',
    margin: { top: '18mm', right: '18mm', bottom: '18mm', left: '18mm' },
    printBackground: true,
  });
  await browser.close();
  console.log('PDF generado:', outPath);
}

run().catch(e => { console.error(e); process.exit(1); });
