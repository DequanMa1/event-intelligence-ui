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
  const [sourceOpen, setSourceOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [followed, setFollowed] = useState<Set<string>>(new Set());

  const selected = events.find((event) => event.id === selectedId) ?? events[0];
  const isFollowed = followed.has(selected.id);
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
    window.setTimeout(() => setToast(""), 2000);
  };

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(createPlainText(selected));
      notify("解读内容已复制");
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
    notify("事件解读已导出");
  };

  const chooseEvent = (id: string) => {
    setSelectedId(id);
    setSourceOpen(false);
    setNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toggleFollow = () => {
    setFollowed((current) => {
      const next = new Set(current);
      if (next.has(selected.id)) next.delete(selected.id);
      else next.add(selected.id);
      return next;
    });
    notify(isFollowed ? "已取消关注" : "已加入我的关注");
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setNavOpen((value) => !value)} aria-label="打开事件列表">☰</button>
        <a className="wordmark" href="#top" aria-label="事件选股首页"><span>事</span><div><b>事件选股</b><small>财经事件智能解读工具</small></div></a>
        <nav className="main-nav" aria-label="主导航">
          <button className="active">事件中心</button>
          <button onClick={() => notify(`已关注 ${followed.size} 个事件`)}>我的关注</button>
          <button onClick={() => notify("使用说明将在正式版开放")}>使用说明</button>
        </nav>
        <div className="top-actions">
          <span className="update-state"><i /> 数据已更新</span>
          <button className="pro-button" onClick={() => notify("当前为商业化界面演示")}>开通专业版</button>
        </div>
      </header>

      <aside className={`event-sidebar ${navOpen ? "open" : ""}`} aria-label="事件列表">
        <div className="sidebar-heading">
          <div><h1>今日财经事件</h1><p>从新闻里快速找到投资线索</p></div>
          <span>共 <b>814</b> 条</span>
        </div>

        <label className="search-box">
          <span>⌕</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索新闻、行业或公司" aria-label="搜索新闻、行业或公司" />
          {query && <button onClick={() => setQuery("")} aria-label="清空搜索">×</button>}
        </label>

        <div className="filter-tabs" role="group" aria-label="筛选事件">
          {(["全部", "高热度", "已确认"] as const).map((item) => (
            <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item}</button>
          ))}
        </div>

        <div className="event-count"><span>6月25日事件</span><span>{filteredEvents.length} 条结果</span></div>
        <div className="event-list">
          {filteredEvents.map((event) => (
            <button key={event.id} className={`event-card ${selected.id === event.id ? "active" : ""}`} onClick={() => chooseEvent(event.id)}>
              <div className="event-card-top">
                <span className={`event-status ${certaintyClass[event.certainty]}`}>{event.certainty === "市场消息" ? "待确认" : event.certainty}</span>
                <span>{event.industry}</span>
                <span className="heat-text">热度 <b>{event.heat}</b></span>
              </div>
              <h2>{event.title}</h2>
              <p>{event.oneLiner}</p>
              <div className="event-meta"><span>{formatDate(event.date)}</span><span>{event.stage}</span></div>
            </button>
          ))}
          {filteredEvents.length === 0 && <div className="empty-state">没有找到相关事件</div>}
        </div>
      </aside>

      <section className="content-shell" id="top">
        <div className="content-toolbar">
          <div className="breadcrumb"><span>事件中心</span><b>/</b><strong>事件解读</strong></div>
          <div className="toolbar-actions">
            <button onClick={copyReport}>复制内容</button>
            <button onClick={exportReport}>导出</button>
          </div>
        </div>

        <div className="content-grid">
          <article className="report-document" key={selected.id}>
            <header className="event-header">
              <div className="event-tags">
                <span className={`event-status ${certaintyClass[selected.certainty]}`}>{selected.certainty === "市场消息" ? "市场消息·待确认" : selected.certainty}</span>
                <span>{selected.industry}</span>
                <span>{selected.stage}</span>
              </div>
              <h2>{selected.title}</h2>
              <div className="event-subline">
                <span>{formatDate(selected.date)}</span>
                <span>事件热度 <b>{selected.heat}/10</b></span>
                <span>来源：迅兔事件数据</span>
              </div>
              <div className="header-actions">
                <button className={isFollowed ? "followed" : ""} onClick={toggleFollow}>{isFollowed ? "✓ 已关注" : "+ 加入关注"}</button>
                <button onClick={() => setSourceOpen((value) => !value)}>{sourceOpen ? "收起原始新闻" : "查看原始新闻"}</button>
              </div>
            </header>

            {sourceOpen && (
              <section className="source-drawer">
                <div><b>迅兔原始描述</b><span>字段：sourceReason</span></div>
                <p>{selected.sourceReason}</p>
              </section>
            )}

            <section className="summary-card">
              <div><span>AI</span><b>一句话看懂</b></div>
              <p>{selected.oneLiner}</p>
            </section>

            <div className="section-nav" aria-label="内容目录">
              {selected.sections.map((section) => <a key={section.key} href={`#${selected.id}-${section.key}`}>{section.number} {section.kicker}</a>)}
            </div>

            {selected.sections.map((section) => (
              <section className="analysis-section" key={section.key} id={`${selected.id}-${section.key}`}>
                <div className="section-title">
                  <div><span>{section.number}</span><h3>{section.kicker}</h3><p>{section.question}</p></div>
                  <div className="claim-legend">{[...new Set(section.claimKinds)].map((kind) => <span key={kind} className={kind}>{claimLabels[kind]}</span>)}</div>
                </div>
                <h4>{section.headline}</h4>
                {section.paragraphs.map((paragraph, index) => (
                  <p className="body-copy" key={paragraph}><span className={`claim-mark ${section.claimKinds[index]}`} />{paragraph}</p>
                ))}

                {section.key === "logic" && (
                  <div className="logic-box"><b>影响路径</b><p>{selected.logicChain.join(" → ")}</p></div>
                )}

                {section.key === "watch" && (
                  <div className="watch-area">
                    <div className="watch-list"><b>后续重点跟踪</b><ol>{selected.watchItems.map((item) => <li key={item}>{item}</li>)}</ol></div>
                    <div className="risk-box"><b>什么情况下逻辑不成立？</b><p>{selected.risk}</p></div>
                  </div>
                )}
              </section>
            ))}

            <footer className="disclaimer">AI 生成内容仅用于辅助理解财经事件，不构成任何证券买卖建议。市场有风险，投资需谨慎。</footer>
          </article>

          <aside className="info-sidebar" aria-label="事件信息">
            <section className="info-card">
              <h3>事件信息</h3>
              <dl>
                <div><dt>事件日期</dt><dd>{formatDate(selected.date)}</dd></div>
                <div><dt>所属行业</dt><dd>{selected.industry}</dd></div>
                <div><dt>事件热度</dt><dd className="hot">{selected.heat}/10</dd></div>
                <div><dt>信息状态</dt><dd>{selected.certainty}</dd></div>
                <div><dt>当前阶段</dt><dd>{selected.stage}</dd></div>
              </dl>
            </section>

            <section className="info-card source-info">
              <h3>数据来源</h3>
              <p>{selected.sourceTitle}</p>
              <span>{selected.sourceOrg}</span>
              {selected.sourceUrl && <a href={selected.sourceUrl} target="_blank" rel="noreferrer">查看引用原文</a>}
            </section>

            <section className="info-card pro-card">
              <span>PRO</span>
              <h3>专业版后续模块</h3>
              <ul><li>（二）影响产业链</li><li>（三）投资机会</li><li>相关公司与验证指标</li></ul>
              <button onClick={() => notify("后续模块尚未接入")}>了解专业版</button>
            </section>

            <section className="info-tip"><b>内容标记说明</b><p><span className="fact">事实</span> 材料中明确发生</p><p><span className="expectation">预期</span> 尚待后续确认</p><p><span className="judgment">判断</span> 基于材料的分析</p></section>
          </aside>
        </div>
      </section>

      {toast && <div className="toast" role="status">{toast}</div>}
      {navOpen && <button className="sidebar-backdrop" aria-label="关闭事件列表" onClick={() => setNavOpen(false)} />}
    </main>
  );
}
