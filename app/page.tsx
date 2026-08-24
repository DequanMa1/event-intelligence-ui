"use client";

import { useEffect, useMemo, useState } from "react";
import { events, type EventRecord } from "./event-data";

type ImpactStock = {
  stockCode: string;
  stockName: string;
  rating: string;
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
  mappingType: "company_product" | "semantic_bridge";
  bridgeBasis: string;
  stockCount: number;
  stocks: Array<Pick<ImpactStock, "stockCode" | "stockName" | "rating">>;
  upstreamCount: number;
  downstreamCount: number;
};

type ImpactRelatedProduct = {
  code: string;
  name: string;
  anchorCount: number;
  stockCount: number;
  linkedCoreProductNames: string[];
};

type IndustryAnalysisTarget = {
  code: string;
  name: string;
};

type ImpactIndustryAnalysis = {
  status: "ready" | "unavailable";
  target: IndustryAnalysisTarget | null;
  text: string | null;
  reason: string;
};

type ImpactChainRecord = {
  status: "ready" | "core_products_only" | "no_four_star_stocks" | "no_company_product_mapping" | "no_relevant_core_products";
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
    semanticBridgeCount: number;
    upstreamCandidateCount: number;
    downstreamCandidateCount: number;
    shownUpstreamCount: number;
    shownDownstreamCount: number;
  };
  chain: {
    upstream: ImpactRelatedProduct[];
    core: ImpactCoreProduct[];
    downstream: ImpactRelatedProduct[];
  };
  industryAnalysis: ImpactIndustryAnalysis;
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
  if (status === "no_four_star_stocks") return "该新闻没有恰好4个实心星的标的";
  if (status === "no_company_product_mapping") return "4星标的尚未穿透到本地公司产品图谱";
  if (status === "no_relevant_core_products") return "尚未筛出与新闻主题一致的核心产品";
  if (status === "core_products_only") return "已找到核心产品，但图谱暂无直接上下游关系";
  return "";
}

function createImpactPlainText(impact: ImpactChainRecord | null) {
  if (!impact) return "（二）影响产业链\n\n产业链数据暂未加载。";
  if (!impact.chain.core.length) return `（二）影响产业链\n\n${impactStatusText(impact.status)}`;

  const names = (values: Array<{ name: string }>) => values.map((item) => item.name).join("、") || "暂无直接关系";
  const industryAnalysis = impact.industryAnalysis.status === "ready" && impact.industryAnalysis.target && impact.industryAnalysis.text
    ? [
        "",
        `事件影响解读：${impact.industryAnalysis.target.name}`,
        impact.industryAnalysis.text,
      ]
    : [];
  return [
    "（二）影响产业链",
    "",
    `筛选口径：origin_star_num 中恰好4个实心星；图谱穿透 ${impact.selection.mappedStockCount}/${impact.selection.sourceStockCount} 只标的。`,
    `上游：${names(impact.chain.upstream)}`,
    `核心产品：${names(impact.chain.core)}`,
    `下游：${names(impact.chain.downstream)}`,
    ...industryAnalysis,
  ].join("\n");
}

function RelatedProductColumn({
  eyebrow,
  title,
  products,
  expanded,
}: {
  eyebrow: string;
  title: string;
  products: ImpactRelatedProduct[];
  expanded: boolean;
}) {
  const visible = expanded ? products : products.slice(0, 6);
  return (
    <section className="chain-column related-column">
      <header>
        <span>{eyebrow}</span>
        <h3>{title}</h3>
        <small>{products.length} 个直接节点</small>
      </header>
      {visible.length > 0 ? (
        <ol className="chain-node-list">
          {visible.map((product) => (
            <li key={product.code} className="chain-node related-node" title={`连接：${product.linkedCoreProductNames.join("、")}`}>
              <strong>{product.name}</strong>
              <span>连接 {product.anchorCount} 个核心产品</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="chain-column-empty">暂无直接{title}关系</p>
      )}
    </section>
  );
}

function CoreProductColumn({ products, expanded }: { products: ImpactCoreProduct[]; expanded: boolean }) {
  const visible = expanded ? products : products.slice(0, 8);
  return (
    <section className="chain-column core-column">
      <header>
        <span>4星标的落点</span>
        <h3>核心产品</h3>
        <small>{products.length} 个主题产品</small>
      </header>
      <ol className="chain-node-list">
        {visible.map((product) => (
          <li key={product.code} className={`chain-node core-node ${product.mappingType === "semantic_bridge" ? "bridge" : ""}`} title={product.hierarchyPath || "由同名主题/上位产品桥接至关系图谱"}>
            <div className="core-node-title">
              <strong>{product.name}</strong>
              {product.mappingType === "semantic_bridge" && <em>关系桥接</em>}
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
  if (analysis.status !== "ready" || !analysis.target || !analysis.text) {
    return null;
  }

  const target = analysis.target;
  return (
    <section className="ai-industry-panel" aria-labelledby="ai-industry-title">
      <header className="ai-industry-heading">
        <div>
          <span>事件影响解读</span>
          <h3 id="ai-industry-title">为什么影响<strong>{target.name}</strong></h3>
        </div>
      </header>

      <div className="ai-response">
        <p>{analysis.text}</p>
      </div>
    </section>
  );
}

function createPlainText(event: EventRecord, impact: ImpactChainRecord | null) {
  const sections = event.sections
    .map((section) => `【${section.number} ${section.kicker}】\n${section.body}`)
    .join("\n\n");

  return `事件研究报告\n\n（一）事件基本情况\n\n${event.title}\n${formatDate(event.date)}｜${event.industry}｜热度 ${event.frequencyLevel}\n\n【新闻原文】\n${getNewsOriginal(event.sourceReason)}\n\n${sections}\n\n${createImpactPlainText(impact)}\n\n（三）投资机会｜待接入\n\n本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。`;
}

const reportParts = [
  { number: "一", title: "事件基本情况", description: "AI事件事实与关联研报摘要", state: "已接入" },
  { number: "二", title: "影响产业链", description: "4星标的、产业链映射与事件影响解读", state: "已接入" },
  { number: "三", title: "投资机会", description: "公司映射、指标与风险", state: "待接入" },
] as const;

export default function Home() {
  const [selectedId, setSelectedId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"全部" | "热度 8—10">("全部");
  const [navOpen, setNavOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [activePart, setActivePart] = useState<"一" | "二">("一");
  const [impactResult, setImpactResult] = useState<{
    mainId: string;
    state: "ready" | "error";
    data: ImpactChainRecord | null;
  } | null>(null);
  const [chainExpanded, setChainExpanded] = useState(false);

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

    fetch(`/data/impact-chains/${selected.apiMainId}.json`, { signal: controller.signal })
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

  const canExpandChain = Boolean(
    impactChain
      && (impactChain.chain.upstream.length > 6
        || impactChain.chain.core.length > 8
        || impactChain.chain.downstream.length > 6),
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
    setChainExpanded(false);
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const chooseReportPart = (number: "一" | "二" | "三") => {
    if (number === "三") {
      notify("投资机会将在后续接入");
      return;
    }
    setActivePart(number);
    const target = number === "一" ? "top" : `${selected.id}-impact-chain`;
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
                className={`report-part ${part.number === activePart ? "active" : part.number === "三" ? "pending" : "ready"}`}
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
                  <h2 id={`${selected.id}-impact-title`}>4星标的产业链传导</h2>
                  <p>以新闻中恰好4个实心星的标的为锚点，穿透到主题相关产品，并展示直接一跳上游与下游。</p>
                </div>
                <span className="impact-method">公司产品映射 · 双向补全关系</span>
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
                    <div><span>4星标的</span><strong>{impactChain.selection.sourceStockCount}</strong><small>恰好4个实心星</small></div>
                    <div><span>图谱穿透</span><strong>{impactChain.selection.mappedStockCount}/{impactChain.selection.sourceStockCount}</strong><small>公司—产品可追溯</small></div>
                    <div><span>核心产品</span><strong>{impactChain.totals.selectedCompanyCoreProductCount}</strong><small>主题相关落点</small></div>
                    <div><span>上下游节点</span><strong>{impactChain.chain.upstream.length + impactChain.chain.downstream.length}</strong><small>直接一跳关系</small></div>
                  </div>

                  {impactChain.chain.core.length > 0 ? (
                    <>
                      <div className="chain-flow" aria-label="上游、核心产品和下游的产业链关系">
                        <RelatedProductColumn eyebrow="供给与支撑" title="上游" products={impactChain.chain.upstream} expanded={chainExpanded} />
                        <CoreProductColumn products={impactChain.chain.core} expanded={chainExpanded} />
                        <RelatedProductColumn eyebrow="需求与应用" title="下游" products={impactChain.chain.downstream} expanded={chainExpanded} />
                      </div>
                      {canExpandChain && (
                        <button className="chain-expand" onClick={() => setChainExpanded((value) => !value)}>
                          {chainExpanded ? "收起产业链" : "展开更多节点"}
                        </button>
                      )}
                    </>
                  ) : (
                    <div className="impact-empty">
                      <strong>{impactStatusText(impactChain.status)}</strong>
                      <p>该状态会保留在数据中，避免用事件标签冒充个股产品关系。</p>
                    </div>
                  )}

                  <IndustryAnalysisPanel analysis={impactChain.industryAnalysis} />

                  <details className="impact-audit">
                    <summary>4星标的与映射说明</summary>
                    <div className="impact-stock-list">
                      {impactChain.selection.stocks.map((stock) => (
                        <span key={`${stock.stockCode}-${stock.stockName}`} className={stock.mapped ? "mapped" : "unmapped"}>
                          <b>{stock.stockName}</b>
                          <small>{stock.stockCode} · {stock.rating} · {stock.mapped ? `${stock.anchorProductCount}个产品` : "未穿透"}</small>
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

            <footer className="disclaimer">本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。市场有风险，投资需谨慎。</footer>
          </article>
        </div>
      </section>

      {toast && <div className="toast" role="status">{toast}</div>}
      {navOpen && <button className="sidebar-backdrop" aria-label="关闭事件列表" onClick={() => setNavOpen(false)} />}
    </main>
  );
}
