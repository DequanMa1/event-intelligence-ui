import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const htmlUrl = new URL("../out/index.html", import.meta.url);
  return new Response(await readFile(htmlUrl, "utf8"), {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
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
  assert.match(html, /4星标的、产业说明与利好利空判断/);
});

test("ships valid impact-chain data for every visible demo event", async () => {
  const demoMainIds = ["27308", "27202", "26314", "26562"];
  const impactTexts = new Set();
  const excludedReportPattern = /日报|日刊|每日|每周|周报|周评|周刊|周度|周观点|双周报|月报|月度|季报|季度|晨报|晨会|晨讯|早报|定期报告/;
  for (const mainId of demoMainIds) {
    const fileUrl = new URL(`../public/data/impact-chains/${mainId}.json`, import.meta.url);
    const payload = JSON.parse(await readFile(fileUrl, "utf8"));
    assert.equal(payload.schemaVersion, 7);
    assert.equal(payload.event.mainId, mainId);
    assert.equal(payload.status, "ready");
    assert.ok(payload.selection.sourceStockCount > 0);
    assert.ok(payload.selection.mappedStockCount > 0);
    assert.ok(payload.chain.core.length > 0);
    assert.ok(payload.chain.upstream.length > 0);
    assert.ok(payload.chain.downstream.length > 0);
    assert.equal(payload.industryAnalysis.status, "ready");
    assert.deepEqual(Object.keys(payload.industryAnalysis).sort(), ["impact", "overview", "reason", "researchSources", "status", "target"]);
    assert.deepEqual(Object.keys(payload.industryAnalysis.target).sort(), ["code", "name"]);
    assert.deepEqual(Object.keys(payload.industryAnalysis.impact).sort(), ["direction", "text"]);
    assert.ok(["偏利好", "偏利空", "利好与利空并存", "影响暂不明确"].includes(payload.industryAnalysis.impact.direction));
    assert.ok(payload.industryAnalysis.overview.length >= 20);
    assert.ok(payload.industryAnalysis.overview.length <= 180);
    assert.equal(payload.industryAnalysis.impact.text.includes("\n"), false);
    assert.ok(payload.industryAnalysis.impact.text.length >= 180);
    assert.ok(payload.industryAnalysis.impact.text.length <= 320);
    for (const phrase of ["本地图谱", "现有语料", "模拟", "关键词规则", "模型返回区", "接入真实大模型", "提示词", "用于验证", "A类", "B类", "C类", "更接近", "规则命中", "模型判断"]) {
      assert.equal(payload.industryAnalysis.impact.text.includes(phrase), false);
      assert.equal(JSON.stringify(payload.industryAnalysis).includes(phrase), false);
    }
    for (const phrase of ["从产业链位置", "企业通常通过", "赚钱最关键", "景气度主要由"]) {
      assert.equal(payload.industryAnalysis.impact.text.includes(phrase), false);
    }
    for (const phrase of ["相关变化直接作用于", "潜在需求只有转化为持续采购", "如果相关变化继续兑现", "后续仍需观察", "利好可能主要停留在预期层面"]) {
      assert.equal(payload.industryAnalysis.impact.text.includes(phrase), false);
    }
    assert.equal(payload.industryAnalysis.researchSources.length, 3);
    assert.equal(new Set(payload.industryAnalysis.researchSources.map((source) => source.reportId)).size, 3);
    assert.equal(new Set(payload.industryAnalysis.researchSources.map((source) => source.title)).size, 3);
    for (const source of payload.industryAnalysis.researchSources) {
      assert.ok(source.title.length > 0);
      assert.ok(source.institution.length > 0);
      assert.equal(excludedReportPattern.test(source.title), false);
      assert.ok(source.publishDate <= payload.event.date);
    }
    impactTexts.add(payload.industryAnalysis.impact.text);
  }
  assert.equal(impactTexts.size, demoMainIds.length);
});

test("keeps the generated manifest consistent with per-event files", async () => {
  const manifestUrl = new URL("../public/data/impact-chains/index.json", import.meta.url);
  const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));
  const statusTotal = Object.values(manifest.statusCounts).reduce((sum, value) => sum + value, 0);

  assert.equal(manifest.schemaVersion, 7);
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
  assert.match(prompt, /\{\{event_basic_info\}\}/);
  assert.match(prompt, /\{\{industry_research_corpus\}\}/);
  assert.match(prompt, /严格输出 JSON/);
  assert.match(prompt, /偏利好/);
  assert.match(prompt, /偏利空/);

  const publicPromptUrl = new URL("../public/data/prompts/industry-cognition-stage1-v1.md", import.meta.url);
  await assert.rejects(readFile(publicPromptUrl, "utf8"), { code: "ENOENT" });
});

test("presents industry analysis as two uninterrupted customer-facing paragraphs", async () => {
  const pageUrl = new URL("../app/page.tsx", import.meta.url);
  const page = await readFile(pageUrl, "utf8");

  assert.match(page, /该新闻主要影响的产业为\{target\.name\}。/);
  assert.match(page, /className="ai-analysis-paragraphs"/);
  assert.doesNotMatch(page, /01 · 这个产业是做什么的/);
  assert.doesNotMatch(page, /02 · 事件对产业的影响/);
  assert.doesNotMatch(page, />参考研报</);
});

