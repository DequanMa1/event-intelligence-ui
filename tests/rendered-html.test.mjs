import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders the event research page and the impact-chain section", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>事件选股 · 财经事件智能解读工具<\/title>/);
  assert.match(html, /第二部分 · 影响产业链/);
  assert.match(html, /4星标的产业链传导/);
  assert.match(html, /公司产品映射 · 双向补全关系/);
  assert.match(html, /4星标的、上下游与产业经营逻辑/);
});

test("ships valid impact-chain data for every visible demo event", async () => {
  const demoMainIds = ["27308", "27202", "26314", "26562"];
  for (const mainId of demoMainIds) {
    const fileUrl = new URL(`../public/data/impact-chains/${mainId}.json`, import.meta.url);
    const payload = JSON.parse(await readFile(fileUrl, "utf8"));
    assert.equal(payload.schemaVersion, 3);
    assert.equal(payload.event.mainId, mainId);
    assert.equal(payload.status, "ready");
    assert.ok(payload.selection.sourceStockCount > 0);
    assert.ok(payload.selection.mappedStockCount > 0);
    assert.ok(payload.chain.core.length > 0);
    assert.ok(payload.chain.upstream.length > 0);
    assert.ok(payload.chain.downstream.length > 0);
    assert.equal(payload.industryAnalysis.status, "ready");
    assert.ok(payload.industryAnalysis.target.coreProductCount > 0);
    assert.ok(payload.industryAnalysis.target.description.length > 0);
    assert.equal(payload.industryAnalysis.target.code, payload.industryAnalysis.candidates[0].code);
    assert.equal("prompt" in payload.industryAnalysis, false);
    assert.equal(payload.industryAnalysis.simulation.isRealModelOutput, false);
    assert.equal(payload.industryAnalysis.simulation.text.includes("\n"), false);
    for (const phrase of ["本地图谱", "现有语料", "模拟结果", "关键词规则", "模型返回区", "接入真实大模型", "提示词", "用于验证"]) {
      assert.equal(payload.industryAnalysis.simulation.text.includes(phrase), false);
    }
  }
});

test("keeps the generated manifest consistent with per-event files", async () => {
  const manifestUrl = new URL("../public/data/impact-chains/index.json", import.meta.url);
  const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));
  const statusTotal = Object.values(manifest.statusCounts).reduce((sum, value) => sum + value, 0);

  assert.equal(manifest.schemaVersion, 3);
  assert.equal(manifest.eventCount, 813);
  assert.equal(manifest.events.length, manifest.eventCount);
  assert.equal(statusTotal, manifest.eventCount);
  assert.equal(new Set(manifest.events.map((event) => event.mainId)).size, manifest.eventCount);
  assert.equal(
    Object.values(manifest.industryAnalysisStatusCounts).reduce((sum, value) => sum + value, 0),
    manifest.eventCount,
  );
});

test("keeps the reusable prompt internal instead of publishing it to visitors", async () => {
  const promptUrl = new URL("../prompts/industry-cognition-stage1-v1.md", import.meta.url);
  const prompt = await readFile(promptUrl, "utf8");

  assert.match(prompt, /\{\{industry_name\}\}/);
  assert.match(prompt, /\{\{industry_description\}\}/);
  assert.match(prompt, /\{\{news_text\}\}/);
  assert.match(prompt, /只输出一整段通顺的话/);

  const publicPromptUrl = new URL("../public/data/prompts/industry-cognition-stage1-v1.md", import.meta.url);
  await assert.rejects(readFile(publicPromptUrl, "utf8"), { code: "ENOENT" });
});
