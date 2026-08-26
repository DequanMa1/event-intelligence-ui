"use client";

import { useEffect, useMemo, useState } from "react";
import { events, type EventRecord } from "./event-data";

type ImpactStock = {
  stockCode: string;
  stockName: string;
  rating: string;
  filledStars: number;
  mapped: boolean;
  anchorProductCount: number;
};

type ImpactCoreProduct = {
  code: string;
  name: string;
  hierarchyPath: string;
  level5Industry: { code: string; name: string };
  level6Industry: { code: string; name: string };
  level7Product: { code: string; name: string };
  matchedSourceLevel: 7;
  stockCount: number;
  stocks: Array<Pick<ImpactStock, "stockCode" | "stockName" | "rating" | "filledStars">>;
};

type RelatedIndustryProduct = {
  code: string;
  name: string;
  hierarchyPath: string;
  matchedSourceLevel: 7;
  stockCount: number;
  stocks: Array<Pick<ImpactStock, "stockCode" | "stockName" | "rating" | "filledStars">>;
};

type RelatedIndustry = {
  rank: number;
  code: string;
  name: string;
  description: string;
  stockCount: number;
  starWeight: number;
  level7ProductCount: number;
  stocks: Array<Pick<ImpactStock, "stockCode" | "stockName" | "rating" | "filledStars">>;
  products: RelatedIndustryProduct[];
};

type IndustryPortfolio = {
  rule: string;
  sourceStockCount: number;
  mappedStockCount: number;
  unmappedStockCount: number;
  level7ProductCount: number;
  candidateIndustryCount: number;
  relatedIndustryCount: number;
  stocks: ImpactStock[];
  relatedIndustries: RelatedIndustry[];
};

type IndustryAnalysisTarget = {
  code: string;
  name: string;
};

type IndustryResearchSource = {
  reportId: string;
  title: string;
  institution: string;
  publishDate: string;
};

type ImpactIndustryAnalysis = {
  status: "ready" | "research_pending" | "unavailable";
  target: IndustryAnalysisTarget | null;
  overview: string | null;
  impact: {
    direction: "偏利好" | "偏利空" | "利好与利空并存" | "影响暂不明确";
    text: string;
  } | null;
  researchSources: IndustryResearchSource[];
  reason: string;
};

type InvestmentStock = {
  sourceRowNumber: number;
  stockCode: string;
  stockName: string;
  rating: string;
  filledStars: number;
  reason: string;
  reasonSourceAvailable: boolean;
  relationLabel: "真相关" | "宽口径相关" | "小基数布局" | "蹭概念" | "错位";
  companyEvidence: {
    matched: boolean;
    matchMethod: "stock_code" | "stock_name" | "none";
    sourceWorkbook: string;
    companyCode: string;
    companyName: string;
    companyProfile: string;
    profileSummary: string;
    majorProducts: string;
    revenueComposition: string;
    revenueSegments: Array<{
      name: string;
      sharePct: number;
      relatedToEvent: boolean;
      relationType: "direct" | "contained" | "unrelated";
    }>;
    businessRelation: {
      status: "direct_segment" | "broad_segment" | "product_confirmed" | "profile_supported" | "business_mismatch" | "unverified" | "unavailable";
      relevantProducts: Array<{ name: string; category: string }>;
      knownProducts: string[];
      directSegmentCount: number;
      containedSegmentCount: number;
    };
  };
  analysis: string;
};

type InvestmentGroup = {
  filledStars: number;
  rating: string;
  name: string;
  relevance: string;
  stockCount: number;
  stocks: InvestmentStock[];
};

type InvestmentOpportunities = {
  status: "ready" | "no_a_share_stocks";
  sourceRowCount: number;
  eligibleSourceRowCount: number;
  totalStockCount: number;
  groupCount: number;
  invalidRatingCount: number;
  excludedLowStarCount: number;
  excludedNonAShareCount: number;
  missingReasonCount: number;
  companyProfileMatchedCount: number;
  companyProfileUnmatchedCount: number;
  sourceWorkbook: string;
  analysisPromptVersion: string;
  groups: InvestmentGroup[];
  caveats: string[];
};

type ImpactChainRecord = {
  status: "ready" | "no_four_star_stocks" | "no_company_product_mapping" | "no_relevant_core_products";
  event: { mainId: string; uid: string; title: string; date: string };
  selection: {
    sourceStockCount: number;
    mappedStockCount: number;
    unmappedStockCount: number;
    stocks: ImpactStock[];
    unmappedStocks: ImpactStock[];
  };
  totals: {
    candidateCoreProductCount: number;
    selectedCoreProductCount: number;
    selectedCompanyCoreProductCount: number;
    level7ProductCount: number;
    relatedIndustryCandidateCount: number;
    shownRelatedIndustryCount: number;
  };
  productIndustryMap: {
    coreProducts: ImpactCoreProduct[];
    relatedIndustries: RelatedIndustry[];
  };
  industryPortfolio: IndustryPortfolio;
  industryAnalysis: ImpactIndustryAnalysis;
  investmentOpportunities: InvestmentOpportunities;
  caveats: string[];
};

function formatDate(date: string) {
  const [year, month, day] = date.split("-");
  return `${year}.${month}.${day}`;
}

function getNewsOriginal(sourceReason: string) {
  const focusMarker = sourceReason.search(/(?:<br\s*\/?>\s*){2,}关注\s*[：:]?/i);
  const newsText = focusMarker >= 0 ? sourceReason.slice(0, focusMarker) : sourceReason;

  return newsText
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/\*\*/g, "")
    .replace(/\s*\n\s*/g, " ")
    .trim();
}

function impactStatusText(status: ImpactChainRecord["status"]) {
  if (status === "no_four_star_stocks") return "该新闻没有4星A股核心标的";
  if (status === "no_company_product_mapping") return "4星A股标的尚未穿透到真实七级产品";
  if (status === "no_relevant_core_products") return "尚未筛出与新闻主题一致的七级核心产品";
  return "";
}

function createImpactPlainText(impact: ImpactChainRecord | null) {
  if (!impact) return "（二）影响产业链\n\n产业链数据暂未加载。";
  if (!impact.productIndustryMap.coreProducts.length) return `（二）影响产业链\n\n${impactStatusText(impact.status)}`;

  const names = (values: Array<{ name?: string; stockName?: string }>) => values
    .map((item) => item.name ?? item.stockName ?? "")
    .filter(Boolean)
    .join("、") || "暂无";
  const relatedIndustries = impact.productIndustryMap.relatedIndustries.flatMap((industry, index) => [
    `相关产业${index + 1}：${industry.name}`,
    `七级产品：${names(industry.products)}`,
    `关联标的：${names(industry.stocks)}`,
  ]);
  const industryAnalysis = impact.industryAnalysis.status === "ready" && impact.industryAnalysis.target && impact.industryAnalysis.overview && impact.industryAnalysis.impact
    ? [
        "",
        `该新闻主要影响的产业为${impact.industryAnalysis.target.name}。${impact.industryAnalysis.overview}`,
        "",
        impact.industryAnalysis.impact.text,
      ]
    : [];
  return [
    "（二）影响产业链",
    "",
    `核心产品口径：4星A股标的；七级产品穿透 ${impact.selection.mappedStockCount}/${impact.selection.sourceStockCount} 只。`,
    `相关产业口径：3—5星A股标的；七级产品穿透 ${impact.industryPortfolio.mappedStockCount}/${impact.industryPortfolio.sourceStockCount} 只，再上卷至五级产业。`,
    `核心产品：${names(impact.productIndustryMap.coreProducts)}`,
    ...relatedIndustries,
    ...industryAnalysis,
  ].join("\n");
}

function RelatedIndustryColumn({
  industry,
  expanded,
}: {
  industry: RelatedIndustry;
  expanded: boolean;
}) {
  const visible = expanded ? industry.products : industry.products.slice(0, 4);
  return (
    <section className="mapping-column related-industry-column">
      <header>
        <span>相关产业 {String(industry.rank).padStart(2, "0")}</span>
        <h3>{industry.name}</h3>
        <small>{industry.stockCount}只标的 · {industry.level7ProductCount}个七级产品</small>
      </header>
      {industry.description && <p className="industry-description">{industry.description}</p>}
      {visible.length > 0 ? (
        <ol className="mapping-node-list">
          {visible.map((product) => (
            <li key={product.code} className="mapping-node industry-product-node" title={product.hierarchyPath}>
              <strong>{product.name}</strong>
              <div className="stock-tags">
                {product.stocks.slice(0, 4).map((stock) => <span key={`${product.code}-${stock.stockCode}`}>{stock.stockName}</span>)}
                {product.stocks.length > 4 && <span>+{product.stocks.length - 4}</span>}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mapping-column-empty">暂无可核验的七级产品</p>
      )}
    </section>
  );
}

function CoreProductColumn({ products, expanded }: { products: ImpactCoreProduct[]; expanded: boolean }) {
  const visible = expanded ? products : products.slice(0, 8);
  return (
    <section className="mapping-column core-column">
      <header>
        <span>4星A股核心落点</span>
        <h3>核心产品</h3>
        <small>{products.length} 个事件相关七级产品</small>
      </header>
      <ol className="mapping-node-list">
        {visible.map((product) => (
          <li key={product.code} className="mapping-node core-node" title={product.hierarchyPath}>
            <div className="core-node-title">
              <strong>{product.name}</strong>
              <em>{product.level5Industry.name}</em>
            </div>
            <div className="stock-tags">
              {product.stocks.slice(0, 4).map((stock) => <span key={`${product.code}-${stock.stockCode}`}>{stock.stockName}</span>)}
              {product.stocks.length > 4 && <span>+{product.stocks.length - 4}</span>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function IndustryAnalysisPanel({ analysis }: { analysis: ImpactIndustryAnalysis }) {
  if (analysis.status !== "ready" || !analysis.target || !analysis.overview || !analysis.impact) {
    return null;
  }

  const target = analysis.target;
  return (
    <section className="ai-industry-panel" aria-labelledby="ai-industry-title">
      <header className="ai-industry-heading">
        <h3 id="ai-industry-title">产业与事件影响</h3>
      </header>

      <div className="ai-analysis-paragraphs">
        <p><strong>该新闻主要影响的产业为{target.name}。</strong>{analysis.overview}</p>
        <p>{analysis.impact.text}</p>
      </div>
    </section>
  );
}

function createInvestmentPlainText(impact: ImpactChainRecord | null) {
  if (!impact) return "（三）投资机会\n\n投资机会数据暂未加载。";
  const opportunities = impact.investmentOpportunities;
  if (!opportunities.groups.length) return "（三）投资机会\n\n该新闻没有3至5星的A股标的。";

  const groups = opportunities.groups.flatMap((group) => [
    `【${group.filledStars}星｜${group.name}｜${group.stockCount}只】`,
    ...group.stocks.flatMap((stock) => {
      const evidence = stock.companyEvidence;
      const revenue = evidence.revenueSegments
        .slice(0, 6)
        .map((segment) => `${segment.name} ${segment.sharePct.toFixed(2).replace(/\.00$/, "")}%`)
        .join("、");
      return [
        `${stock.stockName}${stock.stockCode ? `（${stock.stockCode}）` : ""} · ${stock.rating} · ${stock.relationLabel}`,
        stock.analysis,
        evidence.matched ? `公司概况：${evidence.profileSummary || evidence.companyProfile}` : "公司概况：暂缺。",
        evidence.matched ? `主营业务结构：${revenue || "暂无可展示的分部占比"}` : "",
        "",
      ].filter(Boolean);
    }),
  ]);
  return [
    "（三）投资机会",
    "",
    `共 ${opportunities.totalStockCount} 只3至5星A股标的，按实心星从高到低分为 ${opportunities.groupCount} 组。`,
    "",
    ...groups,
  ].join("\n").trimEnd();
}

function InvestmentOpportunitiesPanel({ opportunities }: { opportunities: InvestmentOpportunities }) {
  if (!opportunities.groups.length) {
    return (
      <div className="impact-empty">
        <strong>该新闻没有3至5星的A股标的</strong>
        <p>海外、港股、未上市公司以及低于3星的标的均已排除。</p>
      </div>
    );
  }

  return (
    <>
      <div className="investment-summary" aria-label="投资机会组合概览">
        <div><span>A股标的</span><strong>{opportunities.totalStockCount}</strong><small>沪深北 · 3至5星</small></div>
        <div><span>星级组合</span><strong>{opportunities.groupCount}</strong><small>按实心星降序</small></div>
        <div><span>业务资料</span><strong>{opportunities.companyProfileMatchedCount}/{opportunities.totalStockCount}</strong><small>公司概况与业务结构</small></div>
        <div><span>海外排除</span><strong>{opportunities.excludedNonAShareCount}</strong><small>仅展示A股标的</small></div>
      </div>

      <div className="investment-groups">
        {opportunities.groups.map((group) => (
          <section className={`investment-group stars-${group.filledStars}`} key={group.filledStars} aria-labelledby={`investment-group-${group.filledStars}`}>
            <header>
              <div>
                <span className="investment-stars" aria-label={`${group.filledStars}个实心星`}>{group.rating}</span>
                <h3 id={`investment-group-${group.filledStars}`}>{group.name}</h3>
              </div>
              <div className="investment-group-meta">
                <strong>{group.relevance}</strong>
                <small>{group.stockCount} 只标的</small>
              </div>
            </header>
            <div className="investment-stock-cards">
              {group.stocks.map((stock) => (
                <article className="investment-stock" key={`${stock.stockCode}-${stock.stockName}-${stock.sourceRowNumber}`}>
                  <header>
                    <div>
                      <h4>{stock.stockName}</h4>
                      {stock.stockCode && <span>{stock.stockCode}</span>}
                    </div>
                    <div className="stock-assessment-meta">
                      <span className="relation-label" data-relation={stock.relationLabel}>{stock.relationLabel}</span>
                      <span className="stock-rating">{stock.rating}</span>
                    </div>
                  </header>
                  <div className="investment-analysis-block">
                    <span>研究判断</span>
                    <p className="investment-analysis">{stock.analysis}</p>
                  </div>

                  {stock.companyEvidence.matched ? (
                    <div className="company-evidence">
                      <section className="company-profile-block">
                        <header>
                          <span>公司概况</span>
                        </header>
                        <p>{stock.companyEvidence.profileSummary || stock.companyEvidence.companyProfile}</p>
                        {stock.companyEvidence.companyProfile !== stock.companyEvidence.profileSummary && (
                          <details>
                            <summary>查看完整公司概况</summary>
                            <p>{stock.companyEvidence.companyProfile}</p>
                          </details>
                        )}
                      </section>

                      <section className="revenue-mix-block">
                        <header>
                          <span>主营业务结构</span>
                        </header>
                        {stock.companyEvidence.revenueSegments.length > 0 ? (
                          <div className="revenue-segments">
                            {stock.companyEvidence.revenueSegments.slice(0, 6).map((segment) => {
                              const barWidth = Math.max(0, Math.min(100, segment.sharePct));
                              return (
                                <div
                                  className={segment.relationType === "direct" ? "revenue-segment related" : segment.relationType === "contained" ? "revenue-segment contained" : "revenue-segment"}
                                  key={`${segment.name}-${segment.sharePct}`}
                                >
                                  <div><span>{segment.name}</span><strong>{segment.sharePct.toFixed(2).replace(/\.00$/, "")}%</strong></div>
                                  <i aria-hidden="true"><b style={{ width: `${barWidth}%` }} /></i>
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <p className="evidence-note">暂无可展示的主营收入分部。</p>
                        )}
                        {stock.companyEvidence.revenueSegments.length > 6 && (
                          <details>
                            <summary>查看完整收入构成</summary>
                            <p>{stock.companyEvidence.revenueComposition}</p>
                          </details>
                        )}
                      </section>
                    </div>
                  ) : (
                    <p className="company-evidence-missing">相关业务收入权重尚未明确，因此不进一步外推利润弹性。</p>
                  )}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>

    </>
  );
}

function createPlainText(event: EventRecord, impact: ImpactChainRecord | null) {
  const sections = event.sections
    .map((section) => `【${section.number} ${section.kicker}】\n${section.body}`)
    .join("\n\n");

  return `事件研究报告\n\n（一）事件基本情况\n\n${event.title}\n${formatDate(event.date)}｜${event.industry}｜热度 ${event.frequencyLevel}\n\n【新闻原文】\n${getNewsOriginal(event.sourceReason)}\n\n${sections}\n\n${createImpactPlainText(impact)}\n\n${createInvestmentPlainText(impact)}\n\n本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。`;
}

const reportParts = [
  { number: "一", title: "事件基本情况", description: "AI事件事实与关联研报摘要", state: "已接入" },
  { number: "二", title: "影响产业链", description: "核心产品、两个相关产业与利好利空判断", state: "已接入" },
  { number: "三", title: "投资机会", description: "A股3—5星组合与逐股研究判断", state: "已接入" },
] as const;

export default function Home() {
  const [selectedId, setSelectedId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"全部" | "热度 8—10">("全部");
  const [navOpen, setNavOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [activePart, setActivePart] = useState<"一" | "二" | "三">("一");
  const [impactResult, setImpactResult] = useState<{
    mainId: string;
    state: "ready" | "error";
    data: ImpactChainRecord | null;
  } | null>(null);
  const [mappingExpanded, setMappingExpanded] = useState(false);

  const selected = events.find((event) => event.id === selectedId) ?? events[0];
  const filteredEvents = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return events
      .filter((event) => {
        const matchesQuery = !keyword || `${event.title}${event.industry}`.toLowerCase().includes(keyword);
        const matchesFilter = filter === "全部" || event.frequencyLevel >= 8;
        return matchesQuery && matchesFilter;
      })
      .sort((a, b) => b.frequencyLevel - a.frequencyLevel);
  }, [filter, query]);

  useEffect(() => {
    const controller = new AbortController();

    const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
    fetch(`${basePath}/data/impact-chains/${selected.apiMainId}.json`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<ImpactChainRecord>;
      })
      .then((payload) => {
        if (payload.event.mainId !== selected.apiMainId) throw new Error("产业链新闻键不一致");
        setImpactResult({ mainId: selected.apiMainId, state: "ready", data: payload });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setImpactResult({ mainId: selected.apiMainId, state: "error", data: null });
      });

    return () => controller.abort();
  }, [selected.apiMainId]);

  const impactChain = impactResult?.mainId === selected.apiMainId ? impactResult.data : null;
  const impactLoadState = impactResult?.mainId === selected.apiMainId ? impactResult.state : "loading";

  const canExpandMapping = Boolean(
    impactChain
      && (impactChain.productIndustryMap.coreProducts.length > 8
        || impactChain.productIndustryMap.relatedIndustries.some((industry) => industry.products.length > 4)),
  );

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2000);
  };

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(createPlainText(selected, impactChain));
      notify("全文已复制");
    } catch {
      notify("复制失败，请使用导出");
    }
  };

  const exportReport = () => {
    const blob = new Blob([createPlainText(selected, impactChain)], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${selected.date}_${selected.title}_事件研究.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
    notify("已导出为文本文件");
  };

  const chooseEvent = (id: string) => {
    setSelectedId(id);
    setActivePart("一");
    setMappingExpanded(false);
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const chooseReportPart = (number: "一" | "二" | "三") => {
    setActivePart(number);
    const target = number === "一"
      ? "top"
      : number === "二"
        ? `${selected.id}-impact-chain`
        : `${selected.id}-investment-opportunities`;
    document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setNavOpen((value) => !value)} aria-label="打开事件列表">☰</button>
        <a className="wordmark" href="#top" aria-label="事件选股首页">
          <b>事件选股</b>
          <span>财经事件研究工具</span>
        </a>
        <div className="top-actions">
          <button onClick={copyReport}>复制全文</button>
          <button onClick={exportReport}>导出文本</button>
        </div>
      </header>

      <aside className={`event-sidebar ${navOpen ? "open" : ""}`} aria-label="事件列表">
        <div className="sidebar-heading">
          <h1>事件列表</h1>
          <p>当前样例 {events.length} 条</p>
        </div>

        <label className="search-box">
          <span>搜索</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="新闻、行业或公司" aria-label="搜索新闻、行业或公司" />
          {query && <button onClick={() => setQuery("")} aria-label="清空搜索">清除</button>}
        </label>

        <div className="filter-tabs" role="group" aria-label="筛选事件">
          {(["全部", "热度 8—10"] as const).map((item) => (
            <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>
          ))}
        </div>

        <div className="event-list">
          {filteredEvents.map((event) => (
            <button key={event.id} className={`event-row ${selected.id === event.id ? "active" : ""}`} onClick={() => chooseEvent(event.id)}>
              <span className="event-row-meta">{formatDate(event.date)} · {event.industry} · 热度 {event.frequencyLevel}</span>
              <strong>{event.title}</strong>
            </button>
          ))}
          {filteredEvents.length === 0 && <div className="empty-state">没有找到相关事件</div>}
        </div>
      </aside>

      <section className="content-shell" id="top">
        <div className="report-frame">
          <nav className="report-parts" aria-label="研究报告章节">
            {reportParts.map((part) => (
              <button
                key={part.number}
                className={`report-part ${part.number === activePart ? "active" : "ready"}`}
                onClick={() => chooseReportPart(part.number)}
                aria-current={part.number === activePart ? "page" : undefined}
              >
                <span className="part-number">（{part.number}）</span>
                <span className="part-copy"><strong>{part.title}</strong><small>{part.description}</small></span>
                <span className="part-state">{part.state}</span>
              </button>
            ))}
          </nav>

          <article className="report-document" key={selected.id}>
            <header className="article-header">
              <p className="article-kicker">第一部分 · 事件基本情况</p>
              <h1>{selected.title}</h1>
              <p className="article-meta">{formatDate(selected.date)} · {selected.industry} · 事件热度 {selected.frequencyLevel}</p>
              <div className="original-news">
                <h2>新闻原文</h2>
                <p>{getNewsOriginal(selected.sourceReason)}</p>
              </div>
            </header>

            <div className="part-body">
              {selected.sections.map((section) => (
                <section className="analysis-section" key={section.key} id={`${selected.id}-${section.key}`}>
                  <header className="section-heading">
                    <span>{section.number}</span>
                    <div className="section-title-line">
                      <h2>{section.kicker}</h2>
                    </div>
                  </header>
                  <p className="section-paragraph">{section.body}</p>
                </section>
              ))}
            </div>

            <section className="impact-section" id={`${selected.id}-impact-chain`} aria-labelledby={`${selected.id}-impact-title`}>
              <header className="impact-heading">
                <div>
                  <p className="article-kicker">第二部分 · 影响产业链</p>
                  <h2 id={`${selected.id}-impact-title`}>核心产品与相关产业</h2>
                  <p>先由4星A股标的锚定核心产品，再将3—5星A股的事件相关七级产品上卷至五级产业，补充两个不与核心产业重复的相关产业。</p>
                </div>
                <span className="impact-method">七级产品 → 五级产业 · 仅A股</span>
              </header>

              {impactLoadState === "loading" && (
                <div className="impact-loading" role="status">
                  <span />
                  <p>正在装载该新闻的产业链关系…</p>
                </div>
              )}

              {impactLoadState === "error" && (
                <div className="impact-empty" role="alert">
                  <strong>产业链数据暂时无法读取</strong>
                  <p>请先重新运行产业链聚合脚本，再刷新页面。</p>
                </div>
              )}

              {impactLoadState === "ready" && impactChain && (
                <>
                  <div className="impact-stats" aria-label="产业链映射概览">
                    <div><span>4星核心标的</span><strong>{impactChain.selection.sourceStockCount}</strong><small>仅沪深北A股</small></div>
                    <div><span>3—5星A股</span><strong>{impactChain.industryPortfolio.mappedStockCount}/{impactChain.industryPortfolio.sourceStockCount}</strong><small>穿透到相关七级产品</small></div>
                    <div><span>核心产品</span><strong>{impactChain.totals.selectedCompanyCoreProductCount}</strong><small>主题相关落点</small></div>
                    <div><span>相关产业</span><strong>{impactChain.productIndustryMap.relatedIndustries.length}</strong><small>排除核心产业后的五级产业</small></div>
                  </div>

                  {impactChain.productIndustryMap.coreProducts.length > 0 ? (
                    <>
                      <div className="product-industry-grid" aria-label="核心产品和两个相关五级产业">
                        <CoreProductColumn products={impactChain.productIndustryMap.coreProducts} expanded={mappingExpanded} />
                        {impactChain.productIndustryMap.relatedIndustries.map((industry) => (
                          <RelatedIndustryColumn key={industry.code} industry={industry} expanded={mappingExpanded} />
                        ))}
                      </div>
                      {canExpandMapping && (
                        <button className="mapping-expand" onClick={() => setMappingExpanded((value) => !value)}>
                          {mappingExpanded ? "收起产品明细" : "展开更多产品"}
                        </button>
                      )}
                    </>
                  ) : (
                    <div className="impact-empty">
                      <strong>{impactStatusText(impactChain.status)}</strong>
                      <p>仅采用可追溯的七级产品关系，证据不足时不会用事件标签替代。</p>
                    </div>
                  )}

                  <IndustryAnalysisPanel analysis={impactChain.industryAnalysis} />

                  <details className="impact-audit">
                    <summary>3—5星A股与七级产品映射说明</summary>
                    <div className="impact-stock-list">
                      {impactChain.industryPortfolio.stocks.map((stock) => (
                        <span key={`${stock.stockCode}-${stock.stockName}`} className={stock.mapped ? "mapped" : "unmapped"}>
                          <b>{stock.stockName}</b>
                          <small>{stock.stockCode} · {stock.rating} · {stock.mapped ? `${stock.anchorProductCount}个七级产品` : "无事件相关七级产品"}</small>
                        </span>
                      ))}
                    </div>
                    <ul className="impact-caveats">
                      {impactChain.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
                    </ul>
                  </details>
                </>
              )}
            </section>

            <section className="investment-section" id={`${selected.id}-investment-opportunities`} aria-labelledby={`${selected.id}-investment-title`}>
              <header className="impact-heading">
                <div>
                  <p className="article-kicker">第三部分 · 投资机会</p>
                  <h2 id={`${selected.id}-investment-title`}>A股3—5星事件投资组合</h2>
                  <p>只保留沪深北交易所的3至5星A股标的，按相关强度从高到低分组，并给出逐股的业务联系、业绩传导与关键约束。</p>
                </div>
                <span className="impact-method">仅限A股 · 3—5星 · 分组研判</span>
              </header>

              {impactLoadState === "loading" && (
                <div className="impact-loading" role="status">
                  <span />
                  <p>正在装载该新闻的投资机会组合…</p>
                </div>
              )}

              {impactLoadState === "error" && (
                <div className="impact-empty" role="alert">
                  <strong>投资机会数据暂时无法读取</strong>
                  <p>请先重新运行事件聚合脚本，再刷新页面。</p>
                </div>
              )}

              {impactLoadState === "ready" && impactChain && (
                <InvestmentOpportunitiesPanel opportunities={impactChain.investmentOpportunities} />
              )}
            </section>

            <footer className="disclaimer">本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。市场有风险，投资需谨慎。</footer>
          </article>
        </div>
      </section>

      {toast && <div className="toast" role="status">{toast}</div>}
      {navOpen && <button className="sidebar-backdrop" aria-label="关闭事件列表" onClick={() => setNavOpen(false)} />}
    </main>
  );
}
