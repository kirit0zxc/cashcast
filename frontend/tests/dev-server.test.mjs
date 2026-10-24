import { test } from "node:test";
import assert from "node:assert/strict";
import { env } from "node:process";
import { loadConfigFromFile } from "vite";

// Загружаем настоящий конфиг: разработка должна попадать в CashCast, а не в соседний проект.
async function withTarget(target, check) {
  const previous = env.CC_DEV_API_TARGET;
  try {
    if (target === undefined) delete env.CC_DEV_API_TARGET;
    else env.CC_DEV_API_TARGET = target;
    const result = await loadConfigFromFile({ command: "serve", mode: "test" }, "vite.config.ts");
    assert.ok(result);
    check(result.config.server);
  } finally {
    if (previous === undefined) delete env.CC_DEV_API_TARGET;
    else env.CC_DEV_API_TARGET = previous;
  }
}

test("dev server stays on loopback and the fixed CashCast port", async () => {
  await withTarget(undefined, (server) => {
    assert.equal(server.host, "127.0.0.1");
    assert.equal(server.port, 5174);
    assert.equal(server.strictPort, true);
    assert.equal(server.proxy["/api"].target, "http://127.0.0.1:8080");
    assert.equal(server.proxy["/api"].changeOrigin, true);
  });
});

test("dev proxy accepts an explicit CashCast stand without changing its origin", async () => {
  await withTarget("http://127.0.0.1:18087", (server) => {
    assert.equal(server.proxy["/api"].target, "http://127.0.0.1:18087");
    assert.equal(server.port, 5174);
    assert.equal(server.strictPort, true);
  });
});
