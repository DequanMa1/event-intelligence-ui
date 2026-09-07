"""Revenue evidence and structural interpretation for the offline site preview.

This is deterministic evidence-based copy, not an LLM call. The model-facing
editorial contract lives in prompts/investment-opportunity-analyst-v15.md.
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
        return "餐厨处理要把收来的废弃物做无害化处置，并回收其中还能利用的油脂。油脂经过加工，可以作为生物燃料的原料。公司既做餐厨处理，也做油脂加工，原料回收与加工利用是两项实际业务，新闻提到的燃料原料就与此有关。"
    if "封测设备" in focus and "光伏" in peer and "自动化" in profile:
        return "两类设备做的事情不同：光电子器件需要装配、对准光路并检测性能，光伏设备则用来生产太阳能电池等产品。公司做的是生产过程中用的自动化装备和软件。理解这次光通信新闻，重点就在光电子器件如何装得准、测得好，而不是光伏设备的用途。"
    if "光模块" in focus and ("电路" in peer or "线路板" in peer):
        return "电子电路用来安装元器件、连接电信号，光模块则把电信号转换成光信号，通过光纤传输。这是两类不同的产品。此次光互联新闻涉及光模块，但公司更大的一块生意仍然是电子电路，理解这家公司时，这两个业务的大小需要分清。"
    if "功率器件" in focus and "芯片" in peer:
        return "芯片经过封装，才成为能装到电源或电机控制系统里的器件。公司的收入以器件为主，也有芯片业务，卖的产品既包括封装后的电子部件，也包括加工在前的芯片。"
    if "原料药" in both and "制剂" in both:
        return "原料药提供药物发挥作用的有效成分，制剂把成分制成适合使用的药品形态。两项业务处在药品生产的不同环节，具体药物或工艺变化应对应到实际承担该功能的产品。"
    if "软件" in both and ("硬件" in both or "设备" in both):
        return "硬件负责计算、采集数据或执行指令，软件决定这些设备按什么规则工作。设备和软件各占多少收入，可以帮助区分公司主要卖哪一类产品，不能把两项业务混在一起理解。"
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
            f"{company_product}属于这一业务方向，用来完成前面提到的工作。" if focus else ""
        )
    if focus:
        name, share = focus["name"], focus["sharePct"]
        anchor = f"{name}占主营收入{pct(share)}"
        if share >= 80:
            sentence = anchor + "，公司绝大部分收入来自这类业务。"
        elif share > 50:
            sentence = anchor + "，超过一半，是公司目前的主营支柱。"
        elif share == 50:
            sentence = anchor + "，正好占一半，是公司的一项主要业务。"
        elif peer and abs(share - peer["sharePct"]) <= 10 and share >= 20:
            sentence = anchor + f"，与占{pct(peer['sharePct'])}的{peer['name']}规模接近，两块业务都占了相当分量。"
        elif share < 10:
            sentence = anchor + f"；占{pct(top['sharePct'])}的{top['name']}才是公司收入的大头，相关产品目前只是其中较小的一项业务。"
        else:
            sentence = anchor + "，在公司收入中已经占有一定比例。"
            if peer:
                sentence += f"{peer['name']}占{pct(peer['sharePct'])}，也是公司主要经营的业务。"
        if peer and share >= 50 and peer["sharePct"] >= 10:
            sentence += f"{peer['name']}占{pct(peer['sharePct'])}，是另一块主要收入来源。"
        explanation = functional_comparison(name, peer["name"] if peer else "", profile)
        if explanation:
            sentence += explanation
        elif not mix["exact"]:
            sentence += f"{company_product}属于{name}这一类业务。"
        return sentence
    # No reliable parent relationship: describe the overall business, without
    # inventing that the selected product belongs to the largest revenue bucket.
    if len(segments) > 1 and segments[1]["sharePct"] >= 10:
        second = segments[1]
        return (f"公司主营收入主要来自{top['name']}（{pct(top['sharePct'])}）和"
                f"{second['name']}（{pct(second['sharePct'])}），收入主要由这两类业务支撑。"
                f"公司做{company_product}，同时还经营这些其他业务。")
    return (f"公司主营收入集中在{top['name']}，占{pct(top['sharePct'])}，这是目前主要的收入来源。"
            "")
