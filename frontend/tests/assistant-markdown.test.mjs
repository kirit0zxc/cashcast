import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server;
let MarkdownMessage;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom",
    optimizeDeps: { noDiscovery: true, entries: [] } });
  ({ MarkdownMessage } = await server.ssrLoadModule("/src/features/assistant/MarkdownMessage.tsx"));
});
after(async () => { await server?.close(); });
const render = text => renderToStaticMarkup(createElement(MarkdownMessage, { text }));

test("assistant markdown renders actual headings, lists, tables and code", () => {
  const html = render("## Итог\n\n**Сумма** и *оценка*\n\n- один\n- два\n\n| Статья | ₽ |\n|---|---:|\n| Аренда | 123,45 |\n\n```text\n<пример>\n```\n\n> Ограничение");
  for (const tag of ["h2", "strong", "em", "ul", "li", "table", "thead", "tbody", "pre", "code", "blockquote"]) {
    assert.ok(html.includes(`<${tag}`), tag);
  }
  assert.ok(html.includes("123,45") && html.includes("&lt;пример&gt;"));
});

test("untrusted markdown cannot run HTML, load tracking images or create dangerous links", () => {
  const html = render('<script>alert(1)</script>\n\n<img src="https://tracker.test/pixel" onerror="alert(1)">\n\n![pixel](https://tracker.test/pixel)\n\n[bad](javascript:alert%281%29) [data](data:text/html,evil) [file](file:///private)\n\n[docs](https://example.com/docs)');
  assert.doesNotMatch(html, /<script|<img|onerror=|javascript:|data:text|file:\/|tracker\.test/);
  assert.match(html, /href="https:\/\/example.com\/docs"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.ok(html.includes("bad") && html.includes("data"));
});
