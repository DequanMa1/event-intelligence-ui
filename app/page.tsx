"use client";

import { useMemo, useState } from "react";
import { events, type EventRecord } from "./event-data";

function formatDate(date: string) {
  const [year, month, day] = date.split("-");
  return `${year}.${month}.${day}`;
}

function createPlainText(event: EventRecord) {
  const sections = event.sections
    .map((section) => {
      const paragraphs = section.paragraphs
        .join("\n\n");
      const extra = section.key === "logic"
        ? `\n影响路径：${event.logicChain.join(" → ")}`
        : section.key === "watch"
          ? `\n后续重点跟踪：\n${event.watchItems.map((item, index) => `${index + 1}. ${item}`).join("\n")}\n证伪条件：${event.risk}`
          : "";

      return `【${section.kicker}】\n${section.headline}\n${paragraphs}${extra}`;
    })
    .join("\n\n");

  return `事件研究报告\n\n（一）事件基本情况\n\n${event.title}\n${formatDate(event.date)}｜${event.industry}｜热度 ${event.heat}/10\n\n【输入材料】\n${event.sourceReason}\n材料名称：${event.sourceTitle}\n\n【核心结论】\n${event.oneLiner}\n\n${sections}\n\n（二）影响产业链｜待接入\n（三）投资机会｜待接入\n\n本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。`;
}

const reportParts = [
  { number: "一", title: "事件基本情况", description: "事实、增量、逻辑与验证", state: "当前阅读" },
  { number: "二", title: "影响产业链", description: "环节、传导与受影响方向", state: "待接入" },
  { number: "三", title: "投资机会", description: "公司映射、指标与风险", state: "待接入" },
] as const;

export default function Home() {
  const [selectedId, setSelectedId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"全部" | "高热度">("全部");
  const [navOpen, setNavOpen] = useState(false);
  const [toast, setToast] = useState("");

  const selected = events.find((event) => event.id === selectedId) ?? events[0];
  const filteredEvents = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return events.filter((event) => {
      const matchesQuery = !keyword || `${event.title}${event.industry}`.toLowerCase().includes(keyword);
      const matchesFilter = filter === "全部" || event.heat >= 8;
      return matchesQuery && matchesFilter;
    });
  }, [filter, query]);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2000);
  };

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(createPlainText(selected));
      notify("全文已复制");
    } catch {
      notify("复制失败，请使用导出");
    }
  };

  const exportReport = () => {
    const blob = new Blob([createPlainText(selected)], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${selected.date}_${selected.title}_事件研究.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
    notify("已导出为文本文件");
  };

  const chooseEvent = (id: string) => {
    setSelectedId(id);
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
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
          {(["全部", "高热度"] as const).map((item) => (
            <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>
          ))}
        </div>

        <div className="event-list">
          {filteredEvents.map((event) => (
            <button key={event.id} className={`event-row ${selected.id === event.id ? "active" : ""}`} onClick={() => chooseEvent(event.id)}>
              <span className="event-row-meta">{formatDate(event.date)}　{event.industry}　热度 {event.heat}/10</span>
              <strong>{event.title}</strong>
            </button>
          ))}
          {filteredEvents.length === 0 && <div className="empty-state">没有找到相关事件</div>}
        </div>
      </aside>

      <section className="content-shell" id="top">
        <div className="report-frame">
          <nav className="report-parts" aria-label="研究报告章节">
            {reportParts.map((part, index) => (
              <button
                key={part.number}
                className={`report-part ${index === 0 ? "active" : "pending"}`}
                onClick={() => index === 0 ? window.scrollTo({ top: 0, behavior: "smooth" }) : notify(`${part.title}将在后续接入`)}
                aria-current={index === 0 ? "page" : undefined}
              >
                <span className="part-number">（{part.number}）</span>
                <span className="part-copy"><strong>{part.title}</strong><small>{part.description}</small></span>
                <span className="part-state">{part.state}</span>
              </button>
            ))}
          </nav>

          <article className="report-document" key={selected.id}>
            <header className="article-header">
              <p className="article-kicker">第一部分　事件基本情况</p>
              <h1>{selected.title}</h1>
              <p className="article-meta">{formatDate(selected.date)}　·　{selected.industry}　·　事件热度 {selected.heat}/10</p>
            </header>

            <section className="material-section">
              <p className="content-label">输入材料</p>
              <p>{selected.sourceReason}</p>
              <p className="source-line">材料名称：{selected.sourceTitle}</p>
            </section>

            <section className="conclusion-section">
              <p className="content-label">核心结论</p>
              <p>{selected.oneLiner}</p>
            </section>

            <nav className="section-index" aria-label="第一部分内容目录">
              {selected.sections.map((section) => (
                <a key={section.key} href={`#${selected.id}-${section.key}`}><span>{section.number}</span>{section.kicker}</a>
              ))}
            </nav>

            <div className="part-body">
              {selected.sections.map((section) => (
                <section className="analysis-section" key={section.key} id={`${selected.id}-${section.key}`}>
                  <div className="section-rail">
                    <span>{section.number}</span>
                    <i />
                  </div>
                  <div className="section-content">
                    <header className="section-header">
                      <p>{section.question}</p>
                      <h2>{section.kicker}</h2>
                      <h3>{section.headline}</h3>
                    </header>

                    <div className="narrative-copy">
                      {section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
                    </div>

                    {section.key === "logic" && (
                      <div className="logic-summary"><strong>影响路径</strong><p>{selected.logicChain.join(" → ")}</p></div>
                    )}

                    {section.key === "watch" && (
                      <div className="watch-content">
                        <div>
                          <h3>后续重点跟踪</h3>
                          <ol>{selected.watchItems.map((item) => <li key={item}>{item}</li>)}</ol>
                        </div>
                        <div className="falsification">
                          <h3>证伪条件</h3>
                          <p>{selected.risk}</p>
                        </div>
                      </div>
                    )}
                  </div>
                </section>
              ))}
            </div>

            <section className="next-parts" aria-label="后续报告章节">
              <div><span>（二）</span><strong>影响产业链</strong><small>预留模块</small></div>
              <div><span>（三）</span><strong>投资机会</strong><small>预留模块</small></div>
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
