"""Revenue evidence and structural interpretation for the offline site preview.

This is deterministic evidence-based copy, not an LLM call. The model-facing
editorial contract lives in prompts/investment-opportunity-analyst-v14.md.
"""
from __future__ import annotations

import math
import re
from typing import Any


OTHER_NAMES = {"其他", "其他业务", "其他产品", "其他主营业务", "主营业务"}


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.lower())


def pct(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"


def refined_revenue_matches(segments: list[dict[str, Any]], product: str):
    """Resolve physical product aliases before broad industry-tag matching.

    Parent categories remain contained. An equipment match must not be confused
    with the optical components manufactured by that equipment, for example.
    Returns None when this small ontology does not establish a relation.
    """
    value = norm(product)
    rules = (
        (("uco", "废弃食用油", "废弃油脂", "再生油脂", "工业级混合油"),
         ("油脂产品加工", "工业级混合油", "再生油脂", "废弃油脂")),
        (("光子器件集成耦合设备", "耦合设备", "光电子封测设备"),
         ("光电子及半导体封测设备", "光电子设备", "光通信设备制造设备")),
        (("igbt", "mosfet", "二极管", "整流桥"),
         ("半导体功率器件", "功率半导体", "功率器件")),
        (("光模块", "光收发模块", "光收发器", "光通讯收发", "光通信收发"),
         ("光模块", "光通讯收发模块", "光通信收发模块", "光收发模块")),
        (("印制电路板", "pcb", "fpc", "柔性线路板"),
         ("电子电路", "印制电路板", "线路板", "电路板")),
    )
    for product_terms, segment_terms in rules:
        if not any(term in value for term in product_terms):
            continue
        found = [s for s in segments if any(term in norm(s["name"]) for term in segment_terms)]
        if found:
            exact = [s for s in found if norm(s["name"]) == value]
            return exact, [s for s in found if s not in exact]
    return None


def revenue_structure(segments, direct, contained):
    """Retain all positive segments; never sum incomplete or overlapping mixes."""
    usable = []
    seen = set()
    duplicate = False
    for segment in segments:
        name = str(segment.get("name", "")).strip()
        share = float(segment.get("sharePct", 0))
        if not name or not math.isfinite(share) or not 0 < share <= 100:
            continue
        key = norm(name)
        if key in seen:
            duplicate = True
            continue
        seen.add(key)
        usable.append({**segment, "sharePct": share})
    usable.sort(key=lambda s: (-s["sharePct"], s["name"]))
    meaningful = [s for s in usable if s["name"] not in OTHER_NAMES]
    related_names = {s["name"] for s in [*direct, *contained]}
    related = [s for s in meaningful if s["name"] in related_names]
    focus = related[0] if related else None
    others = [s for s in meaningful if not focus or s["name"] != focus["name"]]
    return {
        "segments": meaningful,
        "focus": focus,
        "peer": others[0] if others else None,
        "total": sum(s["sharePct"] for s in usable),
        "comparable": not duplicate and 98 <= sum(s["sharePct"] for s in usable) <= 102,
        "exact": bool(focus and focus["name"] in {s["name"] for s in direct}),
    }


def functional_comparison(focus: str, peer: str, profile: str) -> str:
    """Explain supported business functions, not assumed commercial synergy."""
    both = focus + " " + peer
    if "油脂" in focus and "处理" in peer and "餐厨" in profile:
        return "餐厨废弃物处理负责收集后的无害化处置和资源回收，油脂加工把回收物进一步整理为可利用的能源原料，两项业务分别对应原料回收与加工利用。新闻所涉及的生物燃料原料，具体连接在这段资源化利用过程。"
    if "封测设备" in focus and "光伏" in peer and "自动化" in profile:
        return "这两类设备服务不同的制造对象：一类完成光电子器件的装配、耦合与检测，另一类用于光伏生产。公司的自动化装备和制造软件能力，落实到不同工序后形成两块业务，光通信技术变化对应的是前一类设备承担的制造任务。"
    if "光模块" in focus and ("电路" in peer or "线路板" in peer):
        return "电子电路承担器件承载和电信号连接，光模块负责光信号与电信号之间的转换，两者在电子设备中执行不同任务。围绕光互联的新闻，具体产品联系在光模块；电路业务则体现公司更大范围的电子制造基础。"
    if "功率器件" in focus and "芯片" in peer:
        return "芯片承担半导体内部的电功能，器件经过封装后成为能够装入电源、电机控制等系统的部件。器件收入占主导，反映公司的主要产品形态更靠近可使用的电子部件；芯片业务同时保留了更靠前的产品环节。"
    if "原料药" in both and "制剂" in both:
        return "原料药提供药物发挥作用的有效成分，制剂把成分制成适合使用的药品形态。两项业务处在药品生产的不同环节，具体药物或工艺变化应对应到实际承担该功能的产品。"
    if "软件" in both and ("硬件" in both or "设备" in both):
        return "硬件提供计算、采集或执行的实体载体，软件负责规则、流程和功能控制。两类业务的收入分布，体现公司既有产品更偏向设备交付还是软件功能，具体产业应用则要通过相应产品实现。"
    return ""


def describe_business_structure(*, company_product, target_name, company_evidence,
                                direct_segments, contained_segments):
    mix = revenue_structure(company_evidence.get("revenueSegments", []), direct_segments, contained_segments)
    segments, focus, peer = mix["segments"], mix["focus"], mix["peer"]
    if not segments:
        return ""
    top = segments[0]
    profile = company_evidence.get("companyProfile", "")
    if not mix["comparable"]:
        # Individual source percentages remain usable, cross-segment rankings do not.
        selected = focus or top
        return f"{selected['name']}在主营收入构成中占{pct(selected['sharePct'])}。" + (
            f"{company_product}属于这一业务方向，具体承担前述产业功能。" if focus else ""
        )
    if focus:
        name, share = focus["name"], focus["sharePct"]
        anchor = f"{name}占主营收入{pct(share)}"
        if share >= 80:
            sentence = anchor + "，公司经营重心高度集中在这一类产品，相关产业的产品功能与公司的主要经营活动紧密相连。"
        elif share > 50:
            sentence = anchor + "，超过一半，是公司目前的主营支柱。"
        elif share == 50:
            sentence = anchor + "，占公司主营收入的一半，是公司目前的重要业务板块。"
        elif peer and abs(share - peer["sharePct"]) <= 10 and share >= 20:
            sentence = anchor + f"，与占{pct(peer['sharePct'])}的{peer['name']}规模接近，公司同时围绕这两个业务板块开展经营。"
        elif share < 10:
            sentence = anchor + f"；占{pct(top['sharePct'])}的{top['name']}承担更大部分的经营活动，相关新闻连接的是公司较小的一项产品业务。"
        else:
            sentence = anchor + "，已经是有一定分量的业务板块。"
            if peer:
                sentence += f"{peer['name']}占{pct(peer['sharePct'])}，公司整体业务还包含另一类重要产品或服务。"
        if peer and share >= 50 and peer["sharePct"] >= 10:
            sentence += f"{peer['name']}占{pct(peer['sharePct'])}，也是理解公司业务组合的重要部分。"
        explanation = functional_comparison(name, peer["name"] if peer else "", profile)
        if explanation:
            sentence += explanation
        elif not mix["exact"]:
            sentence += f"{company_product}是{name}中的具体产品方向，其与{target_name}的联系体现在产品用途和实际承担的功能。"
        elif share < 50:
            sentence += f"{company_product}的产业作用应放在上述业务组合中理解，产品与{target_name}的联系具体而明确。"
        return sentence
    # No reliable parent relationship: describe the overall business, without
    # inventing that the selected product belongs to the largest revenue bucket.
    if len(segments) > 1 and segments[1]["sharePct"] >= 10:
        second = segments[1]
        return (f"公司主营收入主要来自{top['name']}（{pct(top['sharePct'])}）和"
                f"{second['name']}（{pct(second['sharePct'])}），这两项业务体现了整体经营的主要方向。"
                f"理解其在{target_name}中的位置，应具体到{company_product}承担的功能，不能把公司其他业务一并理解为同一种产品。")
    return (f"公司主营收入集中在{top['name']}，占{pct(top['sharePct'])}，其经营重心主要围绕这一类业务展开。"
            f"{company_product}与{target_name}的联系，具体体现在前述产品功能及使用场景。")
