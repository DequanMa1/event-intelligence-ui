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
  assert.match(html, /核心产品与相关产业/);
  assert.match(html, /七级产品 → 五级产业 · 仅A股/);
  assert.match(html, /核心产品、两个相关产业与利好利空判断/);
  assert.match(html, /第三部分 · 投资机会/);
  assert.match(html, /A股3—5星事件投资组合/);
  assert.match(html, /仅限A股 · 3—5星 · 分组研判/);
  assert.match(html, /A股3—5星组合与逐股研究判断/);
  assert.doesNotMatch(html, /年报验证|证券代码精确匹配|公司简称匹配|缺少 reason|语料说明/);
});

test("ships valid impact-chain data for every visible demo event", async () => {
  const demoMainIds = ["27308", "27202", "26314", "26562"];
  const impactTexts = new Set();
  const investmentOpenings = new Set();
  let matchedProfileTotal = 0;
  const excludedReportPattern = /日报|日刊|每日|每周|周报|周评|周刊|周度|周观点|双周报|月报|月度|季报|季度|晨报|晨会|晨讯|早报|定期报告/;
  for (const mainId of demoMainIds) {
    const fileUrl = new URL(`../public/data/impact-chains/${mainId}.json`, import.meta.url);
    const payload = JSON.parse(await readFile(fileUrl, "utf8"));
    assert.equal(payload.schemaVersion, 14);
    assert.equal(payload.event.mainId, mainId);
    assert.equal(payload.status, "ready");
    assert.ok(payload.selection.sourceStockCount > 0);
    assert.ok(payload.selection.mappedStockCount > 0);
    assert.ok(payload.productIndustryMap.coreProducts.length > 0);
    assert.equal(payload.productIndustryMap.relatedIndustries.length, 2);
    assert.deepEqual(payload.productIndustryMap.relatedIndustries, payload.industryPortfolio.relatedIndustries);
    assert.equal(payload.industryPortfolio.relatedIndustryCount, 2);
    assert.ok(payload.industryPortfolio.sourceStockCount > 0);
    assert.ok(payload.industryPortfolio.mappedStockCount > 0);
    assert.ok(payload.industryPortfolio.mappedStockCount <= payload.industryPortfolio.sourceStockCount);
    assert.ok(payload.industryPortfolio.level7ProductCount > 0);
    for (const stock of payload.selection.stocks) {
      assert.match(stock.stockCode, /^\d{6}\.(?:SH|SZ|BJ)$/);
      assert.equal(stock.filledStars, 4);
    }
    for (const product of payload.productIndustryMap.coreProducts) {
      assert.equal(product.matchedSourceLevel, 7);
      assert.ok(product.level7Product.code.length > 0);
      assert.ok(product.level7Product.name.length > 0);
      assert.ok(product.level5Industry.code.length > 0);
      assert.ok(product.level5Industry.name.length > 0);
    }
    const relatedIndustryCodes = payload.productIndustryMap.relatedIndustries.map((industry) => industry.code);
    assert.equal(new Set(relatedIndustryCodes).size, relatedIndustryCodes.length);
    assert.equal(relatedIndustryCodes.includes(payload.industryAnalysis.target.code), false);
    for (const [index, industry] of payload.productIndustryMap.relatedIndustries.entries()) {
      assert.equal(industry.rank, index + 1);
      assert.ok(industry.code.length > 0);
      assert.ok(industry.name.length > 0);
      assert.ok(industry.stockCount > 0);
      assert.ok(industry.level7ProductCount >= industry.products.length);
      assert.ok(industry.products.length > 0 && industry.products.length <= 4);
      for (const stock of industry.stocks) {
        assert.match(stock.stockCode, /^\d{6}\.(?:SH|SZ|BJ)$/);
        assert.ok(stock.filledStars >= 3 && stock.filledStars <= 5);
      }
      for (const product of industry.products) {
        assert.equal(product.matchedSourceLevel, 7);
        assert.ok(product.code.length > 0);
        assert.ok(product.name.length > 0);
        assert.ok(product.hierarchyPath.length > 0);
        assert.ok(product.stockCount > 0);
        for (const stock of product.stocks) {
          assert.match(stock.stockCode, /^\d{6}\.(?:SH|SZ|BJ)$/);
          assert.ok(stock.filledStars >= 3 && stock.filledStars <= 5);
        }
      }
    }
    assert.equal(payload.investmentOpportunities.status, "ready");
    assert.equal(payload.investmentOpportunities.analysisPromptVersion, "investment-opportunity-analyst-v4.md");
    assert.ok(payload.investmentOpportunities.totalStockCount > 0);
    assert.ok(payload.investmentOpportunities.groupCount > 0);
    assert.equal(payload.investmentOpportunities.groups.length, payload.investmentOpportunities.groupCount);
    assert.ok(payload.investmentOpportunities.groupCount <= 3);
    assert.equal(typeof payload.investmentOpportunities.excludedNonAShareCount, "number");
    assert.ok(payload.investmentOpportunities.totalStockCount <= payload.investmentOpportunities.sourceRowCount);
    assert.ok(payload.investmentOpportunities.totalStockCount <= payload.investmentOpportunities.eligibleSourceRowCount);
    const investmentStars = payload.investmentOpportunities.groups.map((group) => group.filledStars);
    assert.deepEqual(investmentStars, [...investmentStars].sort((a, b) => b - a));
    assert.equal(new Set(investmentStars).size, investmentStars.length);
    assert.equal(
      payload.investmentOpportunities.groups.reduce((sum, group) => sum + group.stockCount, 0),
      payload.investmentOpportunities.totalStockCount,
    );
    let eventMatchedProfileCount = 0;
    for (const group of payload.investmentOpportunities.groups) {
      assert.ok(group.filledStars >= 3 && group.filledStars <= 5);
      assert.equal(group.stocks.length, group.stockCount);
      for (const stock of group.stocks) {
        assert.equal(stock.filledStars, group.filledStars);
        assert.ok(stock.stockName.length > 0);
        assert.match(stock.stockCode, /^\d{6}\.(?:SH|SZ|BJ)$/);
        assert.ok(stock.analysis.includes(stock.stockName));
        assert.ok(stock.analysis.length >= 180);
        assert.ok(stock.analysis.length <= 600);
        assert.equal(stock.analysis.includes("\n"), false);
        assert.match(stock.analysis, /收入|业务|报表|经营/);
        investmentOpenings.add(stock.analysis.slice(0, 24));
        for (const phrase of [
          "年报",
          "公司简介",
          "关联理由",
          "事件关联表",
          "公司库",
          "资料显示",
          "材料显示",
          "数据显示",
          "公告显示",
          "根据资料",
          "根据材料",
          "现有证据",
          "证据层级",
          "缺少可匹配的公司资料",
          "未匹配到公司资料",
          "未匹配到业务资料",
          "从收入结构看",
          "年报口径",
          "输入信息",
          "处理过程",
          "核心矛盾",
          "后续重点看",
          "有望受益",
          "值得关注",
          "未来可期",
        ]) {
          assert.equal(stock.analysis.includes(phrase), false);
        }
        assert.equal(stock.reasonSourceAvailable, stock.reason.length > 0);
        assert.doesNotMatch(stock.reason, /\[[0-9a-f]{20,}(?:_[0-9]+)?\]/i);
        assert.doesNotMatch(stock.analysis, /\[[0-9a-f]{20,}(?:_[0-9]+)?\]/i);
        assert.equal(typeof stock.companyEvidence.matched, "boolean");
        assert.equal(stock.companyEvidence.sourceWorkbook, "2025年报公司简介和主营业务占比.xlsx");
        assert.ok(["stock_code", "stock_name", "none"].includes(stock.companyEvidence.matchMethod));
        assert.ok(Array.isArray(stock.companyEvidence.revenueSegments));
        if (stock.companyEvidence.matched) {
          eventMatchedProfileCount += 1;
          assert.ok(stock.companyEvidence.companyCode.length > 0);
          assert.ok(stock.companyEvidence.companyName.length > 0);
          assert.ok(stock.companyEvidence.companyProfile.length > 0);
          assert.ok(stock.companyEvidence.profileSummary.length > 0);
          assert.equal(typeof stock.companyEvidence.majorProducts, "string");
          assert.notEqual(stock.companyEvidence.matchMethod, "none");
          for (const segment of stock.companyEvidence.revenueSegments) {
            assert.ok(segment.name.length > 0);
            assert.equal(typeof segment.sharePct, "number");
            assert.equal(typeof segment.relatedToEvent, "boolean");
            assert.ok(["direct", "contained", "unrelated"].includes(segment.relationType));
            assert.equal(segment.relatedToEvent, segment.relationType === "direct");
          }
          assert.ok(["direct_segment", "broad_segment", "product_confirmed", "profile_supported", "business_mismatch", "unverified"].includes(stock.companyEvidence.businessRelation.status));
          assert.ok(Array.isArray(stock.companyEvidence.businessRelation.relevantProducts));
          assert.ok(Array.isArray(stock.companyEvidence.businessRelation.knownProducts));
        } else {
          assert.equal(stock.companyEvidence.matchMethod, "none");
          assert.equal(stock.companyEvidence.companyProfile, "");
          assert.equal(stock.companyEvidence.businessRelation.status, "unavailable");
        }
      }
    }
    if (mainId === "27308") {
      assert.deepEqual(
        payload.productIndustryMap.relatedIndustries.map((industry) => industry.name),
        ["半导体设备", "网络设备"],
      );
      assert.deepEqual(
        payload.productIndustryMap.relatedIndustries[0].products.map((product) => product.name),
        ["共封装光学(CPO)测试设备", "光子器件集成耦合设备", "硅光晶圆测试系统"],
      );
      assert.ok(payload.productIndustryMap.relatedIndustries[1].products.some((product) => product.name === "数据中心交换机"));
      const stocks = payload.investmentOpportunities.groups.flatMap((group) => group.stocks);
      const yangjie = stocks.find((stock) => stock.stockName === "扬杰科技");
      const luobo = stocks.find((stock) => stock.stockName === "罗博特科");
      const dongshan = stocks.find((stock) => stock.stockName === "东山精密");
      const fii = stocks.find((stock) => stock.stockName === "工业富联");
      assert.deepEqual(yangjie.companyEvidence.revenueSegments.filter((segment) => segment.relatedToEvent), []);
      assert.equal(yangjie.companyEvidence.businessRelation.status, "business_mismatch");
      assert.deepEqual(yangjie.companyEvidence.businessRelation.relevantProducts, []);
      assert.equal(luobo.companyEvidence.businessRelation.status, "broad_segment");
      assert.ok(luobo.companyEvidence.revenueSegments.some((segment) => segment.name === "光电子及半导体封测设备" && segment.relationType === "contained"));
      assert.deepEqual(
        dongshan.companyEvidence.revenueSegments.filter((segment) => segment.relatedToEvent).map((segment) => segment.name),
        ["光模块"],
      );
      assert.deepEqual(fii.companyEvidence.revenueSegments.filter((segment) => segment.relatedToEvent), []);
      assert.equal(fii.companyEvidence.businessRelation.status, "broad_segment");
      assert.ok(fii.companyEvidence.revenueSegments.some((segment) => segment.name === "3C电子产品" && segment.relationType === "contained"));
    }
    assert.equal(eventMatchedProfileCount, payload.investmentOpportunities.companyProfileMatchedCount);
    assert.equal(
      payload.investmentOpportunities.companyProfileMatchedCount + payload.investmentOpportunities.companyProfileUnmatchedCount,
      payload.investmentOpportunities.totalStockCount,
    );
    matchedProfileTotal += eventMatchedProfileCount;
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
  assert.ok(investmentOpenings.size >= 8);
  assert.ok(matchedProfileTotal > 0);
});

test("keeps the generated manifest consistent with per-event files", async () => {
  const manifestUrl = new URL("../public/data/impact-chains/index.json", import.meta.url);
  const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));
  const statusTotal = Object.values(manifest.statusCounts).reduce((sum, value) => sum + value, 0);

  assert.equal(manifest.schemaVersion, 14);
  assert.equal(manifest.eventCount, 813);
  assert.equal(manifest.events.length, manifest.eventCount);
  assert.equal(statusTotal, manifest.eventCount);
  assert.equal(new Set(manifest.events.map((event) => event.mainId)).size, manifest.eventCount);
  assert.equal(
    Object.values(manifest.industryAnalysisStatusCounts).reduce((sum, value) => sum + value, 0),
    manifest.eventCount,
  );
  assert.equal(manifest.source.companyProfiles, "2025年报公司简介和主营业务占比.xlsx");
  assert.equal(manifest.source.companyProfileCount, 5499);
  assert.equal(manifest.source.investmentPrompt, "investment-opportunity-analyst-v4.md");
  assert.equal(Object.hasOwn(manifest.source, "edges"), false);
  assert.ok(manifest.events.every((event) => event.relatedIndustryCount >= 0 && event.relatedIndustryCount <= 2));
  assert.ok(manifest.events.some((event) => event.relatedIndustryCount === 2));
  assert.ok(manifest.events.some((event) => event.investmentCompanyProfileMatchedCount > 0));
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

test("keeps the investment analyst prompt structured and internal", async () => {
  const promptUrl = new URL("../prompts/investment-opportunity-analyst-v4.md", import.meta.url);
  const prompt = await readFile(promptUrl, "utf8");

  for (const placeholder of ["event_title", "stock_name", "stock_code", "filled_stars", "reason", "company_profile", "major_products", "revenue_composition", "mapped_products", "revenue_segment_relations"]) {
    assert.ok(prompt.includes(`{{${placeholder}}}`));
  }
  for (const requirement of ["真正要回答的问题", "可自由选择的分析视角", "工具箱，不是必答题", "星级只是分析先验"]) {
    assert.match(prompt, new RegExp(requirement));
  }
  for (const requirement of ["客户端无来源表达", "输入信息只在后台发挥作用", "不得解释结论来自哪里"]) {
    assert.match(prompt, new RegExp(requirement));
  }
  for (const requirement of ["业务语义判断原则", "不能只比较文字是否相同", "宽口径包含", "不能按零处理", "实际产品和经营结构为准", "直接具体分析"]) {
    assert.match(prompt, new RegExp(requirement));
  }
  assert.match(prompt, /通常为260—500字/);
  assert.doesNotMatch(prompt, /必须完成以下判断/);

  const publicPromptUrl = new URL("../public/data/prompts/investment-opportunity-analyst-v4.md", import.meta.url);
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
  assert.match(page, /核心产品和两个相关五级产业/);
  assert.doesNotMatch(page, /上游、核心产品和下游/);
  assert.doesNotMatch(page, /双向补全关系/);
});
