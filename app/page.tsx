"use client";

import { useMemo, useState } from "react";
import { claimLabels, events, type EventRecord } from "./event-data";

const certaintyClass: Record<EventRecord["certainty"], string> = {
  "已公告": "confirmed",
  "已验证": "verified",
  "市场消息": "unconfirmed",
};

function formatDate(date: string) {
  const [year, month, day] = date.split("-");
  return `${year}.${month}.${day}`;
}

function createPlainText(event: EventRecord) {
  const sections = event.sections
    .map((section) => `【${section.kicker}】\n${section.headline}\n${section.paragraphs.join("\n")}`)
    .join("\n\n");

  return `（一）事件基本情况\n\n${event.title}\n${formatDate(event.date)}｜热度 ${event.heat}/10｜${event.certainty}\n\n一句话看懂：${event.oneLiner}\n\n${sections}\n\n【关键验证点】\n${event.watchItems.map((item, index) => `${index + 1}. ${item}`).join("\n")}\n\n【证伪条件】\n${event.risk}`;
}

export default function Home() {
  const [selectedId, setSelectedId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"全部" | "高热度" | "已确认">("全部");
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [toast, setToast] = useState("");
  const [navOpen, setNavOpen] = useState(false);

  const selected = events.find((event) => event.id === selectedId) ?? events[0];
  const filteredEvents = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return events.filter((event) => {
      const matchesQuery = !keyword || `${event.title}${event.industry}`.toLowerCase().includes(keyword);
      const matchesFilter = filter === "全部" || (filter === "高热度" && event.heat >= 8) || (filter === "已确认" && event.certainty !== "市场消息");
      return matchesQuery && matchesFilter;
    });
  }, [filter, query]);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2200);
  };

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(createPlainText(selected));
      notify("报告全文已复制");
    } catch {
      notify("浏览器未允许复制，请使用导出");
    }
  };

  const exportReport = () => {
    const blob = new Blob([createPlainText(selected)], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${selected.date}_${selected.title}_事件基本情况.txt`;
    link.click();
    URL.revokeObjectURL(link.href);
    notify("TXT 报告已导出");
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
        <a className="wordmark" href="#top" aria-label="研报台首页"><span>研</span><b>研报台</b><small>EVENT INTELLIGENCE</small></a>
        <nav className="part-nav" aria-label="报告章节">
          <button className="active"><i>01</i> 事件基本情况</button>
          <button disabled title="后续阶段"><i>02</i> 影响产业链 <em>稍后</em></button>
          <button disabled title="后续阶段"><i>03</i> 投资机会 <em>稍后</em></button>
        </nav>
        <div className="top-actions">
          <span className="model-state"><i /> Agent 在线</span>
          <button className="text-button" onClick={() => notify("本页已是最新数据快照")}>数据快照</button>
        </div>
      </header>

      <aside className={`event-sidebar ${navOpen ? "open" : ""}`} aria-label="事件列表">
        <div className="sidebar-heading">
          <div>
            <p>迅兔事件池</p>
            <h1>事件工作台</h1>
          </div>
          <span><b>814</b> 条已接入</span>
        </div>

        <label className="search-box">
          <span>⌕</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索事件或行业" aria-label="搜索事件或行业" />
          {query && <button onClick={() => setQuery("")} aria-label="清空搜索">×</button>}
        </label>

        <div className="filter-tabs" role="group" aria-label="筛选事件">
          {(["全部", "高热度", "已确认"] as const).map((item) => (
            <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>
          ))}
        </div>

        <div className="event-count"><span>2026.06.25</span><span>{filteredEvents.length} 个示例事件</span></div>
        <div className="event-list">
          {filteredEvents.map((event) => (
            <button key={event.id} className={`event-card ${selected.id === event.id ? "active" : ""}`} onClick={() => chooseEvent(event.id)}>
              <div className="event-card-top">
                <span className={`certainty-dot ${certaintyClass[event.certainty]}`} />
                <span>{event.certainty}</span>
                <span className="event-industry">{event.industry}</span>
              </div>
              <h2>{event.title}</h2>
              <div className="event-meta"><span>热度 <b>{event.heat}</b>/10</span><span>{event.stage}</span></div>
            </button>
          ))}
          {filteredEvents.length === 0 && <div className="empty-state">没有匹配的示例事件</div>}
        </div>
        <div className="queue-note"><span>↳</span><p><b>批量接入已预留</b><br />当前展示 6 个真实数据样例；数据层可继续接入全部 814 条事件。</p></div>
      </aside>

      <section className={`report-column ${evidenceOpen ? "with-evidence" : ""}`} id="top">
        <div className="report-toolbar">
          <div className="breadcrumb"><span>研究报告</span><b>/</b><strong>（一）事件基本情况</strong></div>
          <div className="report-actions">
            <button onClick={copyReport}>复制全文</button>
            <button onClick={exportReport}>导出 TXT</button>
            <button className={evidenceOpen ? "active" : ""} onClick={() => setEvidenceOpen((value) => !value)}>原始材料</button>
          </div>
        </div>

        <article className="report-document" key={selected.id}>
          <header className="report-hero">
            <div className="hero-meta">
              <span className="part-label">PART 01</span>
              <span>{formatDate(selected.date)}</span>
              <span>{selected.type}</span>
              <span className={`certainty-tag ${certaintyClass[selected.certainty]}`}>{selected.certainty === "市场消息" ? "待确认" : selected.certainty}</span>
            </div>
            <h2>{selected.title}</h2>
            <div className="hero-footer">
              <div className="heat-meter" aria-label={`事件热度 ${selected.heat}/10`}>
                <span>事件热度</span>
                <div>{Array.from({ length: 10 }, (_, index) => <i key={index} className={index < selected.heat ? "filled" : ""} />)}</div>
                <b>{selected.heat}.0</b>
              </div>
              <div className="quality-stamp"><span>✓</span><p><b>事实边界检查通过</b><small>事实 / 预期 / 判断已区分</small></p></div>
            </div>
          </header>

          <section className="one-line-summary">
            <span>一句话看懂</span>
            <p>{selected.oneLiner}</p>
          </section>

          <div className="reading-guide" aria-label="阅读路径">
            <span>发生了什么</span><b>→</b><span>新在哪里</span><b>→</b><span>如何影响盈利</span><b>→</b><span>怎样验证</span>
          </div>

          {selected.sections.map((section) => (
            <section className="analysis-block" key={section.key} id={`${selected.id}-${section.key}`}>
              <div className="block-number">{section.number}</div>
              <div className="block-content">
                <div className="block-heading">
                  <div><p>{section.kicker}</p><span>{section.question}</span></div>
                  <div className="claim-legend">
                    {[...new Set(section.claimKinds)].map((kind) => <span key={kind} className={kind}>{claimLabels[kind]}</span>)}
                  </div>
                </div>
                <h3>{section.headline}</h3>
                {section.paragraphs.map((paragraph, index) => (
                  <p className="body-copy" key={paragraph}><span className={`claim-mark ${section.claimKinds[index]}`} aria-hidden="true" />{paragraph}</p>
                ))}

                {section.key === "logic" && (
                  <div className="logic-chain" aria-label="盈利影响链条">
                    {selected.logicChain.map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, "0")}</span><b>{item}</b>{index < selected.logicChain.length - 1 && <i>→</i>}</div>)}
                  </div>
                )}

                {section.key === "watch" && (
                  <div className="watch-panel">
                    <div className="watch-list"><p>未来验证清单</p>{selected.watchItems.map((item, index) => <div key={item}><span>{index + 1}</span><b>{item}</b></div>)}</div>
                    <div className="risk-box"><span>证伪条件</span><p>{selected.risk}</p></div>
                  </div>
                )}
              </div>
            </section>
          ))}

          <footer className="report-end">
            <div><span>AI 研究草稿</span><p>本页用于说明事件与盈利变量之间的关系，不构成个股买卖建议。</p></div>
            <button onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>返回顶部 ↑</button>
          </footer>
        </article>
      </section>

      {evidenceOpen && (
        <aside className="evidence-panel" aria-label="原始材料与生成依据">
          <div className="evidence-title"><div><p>EVIDENCE</p><h2>生成依据</h2></div><button onClick={() => setEvidenceOpen(false)} aria-label="关闭原始材料">×</button></div>

          <section className="source-card">
            <div className="source-heading"><span>01</span><div><b>迅兔原始描述</b><small>{formatDate(selected.date)} · sourceReason</small></div></div>
            <blockquote>{selected.sourceReason}</blockquote>
          </section>

          <section className="evidence-section">
            <p className="evidence-kicker">事实状态</p>
            <div className="status-table">
              <div><span>事件阶段</span><b>{selected.stage}</b></div>
              <div><span>信息性质</span><b>{selected.certainty}</b></div>
              <div><span>事实锚点</span><b className="pass">已提取</b></div>
              <div><span>缺失信息</span><b>自动保留</b></div>
            </div>
          </section>

          <section className="evidence-section">
            <p className="evidence-kicker">引用研究</p>
            <div className="reference-item">
              <span>R1</span>
              <div><b>{selected.sourceTitle}</b><small>{selected.sourceOrg}</small>{selected.sourceUrl && <a href={selected.sourceUrl} target="_blank" rel="noreferrer">查看原文 ↗</a>}</div>
            </div>
          </section>

          <section className="evidence-section model-contract">
            <p className="evidence-kicker">Agent 输出协议</p>
            <div><span>结构</span><b>4 段固定字段</b></div>
            <div><span>篇幅</span><b>600—1000 字</b></div>
            <div><span>边界</span><b>禁止补全缺失数据</b></div>
            <div><span>版本</span><b>event_basic_v1</b></div>
          </section>
        </aside>
      )}

      {toast && <div className="toast" role="status">✓ {toast}</div>}
      {navOpen && <button className="sidebar-backdrop" aria-label="关闭事件列表" onClick={() => setNavOpen(false)} />}
    </main>
  );
}
