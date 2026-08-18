"use client";

import { useMemo, useState } from "react";
import { claimLabels, events, type EventRecord } from "./event-data";

function formatDate(date: string) {
  const [year, month, day] = date.split("-");
  return `${year}.${month}.${day}`;
}

function createPlainText(event: EventRecord) {
  const sections = event.sections
    .map((section) => {
      const paragraphs = section.paragraphs
        .map((paragraph, index) => `${claimLabels[section.claimKinds[index]]}：${paragraph}`)
        .join("\n");
      const extra = section.key === "logic"
        ? `\n影响路径：${event.logicChain.join(" → ")}`
        : section.key === "watch"
          ? `\n后续重点跟踪：\n${event.watchItems.map((item, index) => `${index + 1}. ${item}`).join("\n")}\n证伪条件：${event.risk}`
          : "";

      return `【${section.kicker}】\n${section.headline}\n${paragraphs}${extra}`;
    })
    .join("\n\n");

  return `（一）事件基本情况\n\n${event.title}\n${formatDate(event.date)}｜${event.industry}｜热度 ${event.heat}/10\n\n【原始材料】\n${event.sourceReason}\n来源：${event.sourceTitle}｜${event.sourceOrg}\n\n【一句话结论】\n${event.oneLiner}\n\n${sections}\n\n本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。`;
}

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
    link.download = `${selected.date}_${selected.title}_事件解读.txt`;
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
          <span>财经事件文字解读工具</span>
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
        <article className="report-document" key={selected.id}>
          <header className="article-header">
            <p className="article-kicker">（一）事件基本情况</p>
            <h1>{selected.title}</h1>
            <p className="article-meta">{formatDate(selected.date)}　·　{selected.industry}　·　事件热度 {selected.heat}/10　·　数据来自迅兔事件材料</p>
          </header>

          <section className="source-section">
            <h2>原始材料</h2>
            <p>{selected.sourceReason}</p>
            <p className="source-line">
              来源：{selected.sourceTitle}，{selected.sourceOrg}
              {selected.sourceUrl && <>　<a href={selected.sourceUrl} target="_blank" rel="noreferrer">查看引用原文</a></>}
            </p>
          </section>

          <section className="brief-section">
            <h2>一句话结论</h2>
            <p>{selected.oneLiner}</p>
          </section>

          {selected.sections.map((section) => (
            <section className="analysis-section" key={section.key}>
              <p className="section-number">{section.number}</p>
              <h2>{section.kicker}</h2>
              <p className="section-question">{section.question}</p>
              <h3>{section.headline}</h3>

              {section.paragraphs.map((paragraph, index) => (
                <p className="analysis-paragraph" key={paragraph}>
                  <strong>{claimLabels[section.claimKinds[index]]}：</strong>{paragraph}
                </p>
              ))}

              {section.key === "logic" && (
                <p className="logic-line"><strong>影响路径：</strong>{selected.logicChain.join(" → ")}</p>
              )}

              {section.key === "watch" && (
                <div className="watch-content">
                  <h3>后续重点跟踪</h3>
                  <ol>{selected.watchItems.map((item) => <li key={item}>{item}</li>)}</ol>
                  <p><strong>证伪条件：</strong>{selected.risk}</p>
                </div>
              )}
            </section>
          ))}

          <footer className="disclaimer">本内容用于解释事件与经营变量之间的关系，不构成个股买卖建议。市场有风险，投资需谨慎。</footer>
        </article>
      </section>

      {toast && <div className="toast" role="status">{toast}</div>}
      {navOpen && <button className="sidebar-backdrop" aria-label="关闭事件列表" onClick={() => setNavOpen(false)} />}
    </main>
  );
}
