from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


EVENT_COLUMNS = [
    "main_id",
    "uid",
    "calendar_day",
    "topic_name",
    "source_reason",
    "stock_code",
    "stock_name",
    "origin_star_num",
    "first_level",
    "second_level",
    "industry1",
    "industry2",
    "industry3",
]

PATH_COLUMNS = [
    "source_row_number",
    "event_stock_row_id",
    "main_id",
    "uid",
    "stock_code",
    "stock_name",
    "mapping_method",
    "is_real_industry_path",
    "matched_source_level",
    "matched_node_code",
    "matched_node_name",
    "5industry_code",
    "5industry_name",
    "6industry_code",
    "6industry_name",
    "7industry_code",
    "7industry_name",
    "hierarchy_path",
]

NODE_COLUMNS = [
    "5industry_code",
    "5industry_name",
    "5industry_remark",
]

EDGE_COLUMNS = [
    "当前产品代码",
    "当前产品名称",
    "关系",
    "关联产品代码",
    "关联产品名称",
    "原始是否已有",
    "产业链上游代码",
    "产业链下游代码",
    "数据状态",
]

CONTEXT_WEIGHTS = {
    "first_level": 5,
    "second_level": 6,
    "industry1": 1,
    "industry2": 2,
    "industry3": 3,
}

MAX_CORE_PRODUCTS = 18
MAX_RELATED_PRODUCTS = 14
STAR_PATTERN = re.compile(r"^[★☆]{1,5}(?:\s*\(\d+/\d+分\))?$")
TECH_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+-]{1,15}")
SPLIT_PATTERN = re.compile(r"[/／、,，;；|+&]|\s+-\s+")
GENERIC_CONTEXT_TERMS = {
    "上游",
    "中游",
    "下游",
    "材料",
    "产品",
    "设备",
    "厂商",
    "潜力企业",
    "国内厂商",
    "海外厂商",
}

NEWS_VARIABLE_SIGNALS = {
    "下游需求与订单": ("需求", "订单", "销量", "销售", "采购", "客户采用"),
    "产品价格": ("涨价", "提价", "价格上涨", "价格下跌", "降价", "价差"),
    "原材料与成本": ("原材料", "原料", "成本", "矿价", "油价", "铜价"),
    "供给与库存": ("缺货", "短缺", "供给", "减产", "停产", "库存"),
    "产能与开工": ("产能", "扩产", "开工率", "稼动率", "交付周期"),
    "技术与量产": ("技术突破", "技术路线", "量产", "良率", "商业化"),
    "政策与制度": ("政策", "强制", "监管", "补贴", "规划"),
    "出口与海外需求": ("出口", "海外", "关税", "贸易"),
}
VARIABLE_EXPLANATIONS = {
    "下游需求与订单": "下游需求和订单决定销量或项目量，持续增长通常有助于收入扩张和产能利用率提升",
    "产品价格": "产品价格决定单位收入，只有涨价能够被客户接受并且销量不明显下滑，利润才可能改善",
    "原材料与成本": "原材料和交付成本决定单位利润，成本上涨而售价不能同步调整时，盈利空间会被压缩",
    "供给与库存": "供给和库存反映供需松紧，库存下降、交期拉长往往意味着卖方议价能力增强",
    "产能与开工": "产能和开工率决定企业能否把订单转化为收入，利用率提高通常有利于摊薄固定成本",
    "技术与量产": "技术升级和量产进度决定产品竞争力，但商业价值仍取决于良率、成本和客户采用",
    "政策与制度": "政策和制度影响需求释放节奏，关键在于约束是否落地以及能否形成持续采购",
    "出口与海外需求": "出口和海外需求影响新增市场空间，同时也会受到贸易规则、认证和汇率变化影响",
    "市场竞争": "市场竞争决定企业能否维持价格和份额，产能集中释放可能导致价格压力上升",
}
CLIENT_BANNED_PHRASES = (
    "本地图谱",
    "现有语料",
    "模拟结果",
    "关键词规则",
    "模型返回区",
    "接入真实大模型",
    "提示词",
    "用于验证",
)
TREND_SIGNALS = (
    "技术路线改变",
    "技术突破",
    "强制掺混",
    "资本开支周期",
    "渗透率",
    "制度变化",
    "商业化",
    "进入量产",
    "规模化量产",
)
ACCELERATION_SIGNALS = (
    "涨价",
    "提价",
    "缺货",
    "订单增加",
    "订单已排",
    "库存下降",
    "开工率提高",
    "出口增长",
    "出口量环比",
    "交付周期",
    "量价齐升",
)
SHORT_DISTURBANCE_SIGNALS = ("单笔订单", "单家公司", "临时停产", "市场传闻", "短期波动")


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"[\t\r\n]+", " ", str(value).replace("\u3000", " ").strip())


def canonical_text(values: Iterable[Any]) -> str:
    cleaned = [clean_text(value) for value in values if clean_text(value)]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return sorted(counts, key=lambda item: (-counts[item], -len(item), item))[0]


def extract_news_text(value: Any) -> str:
    text = clean_text(value)
    focus_marker = re.search(r"(?:<br\s*/?>\s*){2,}关注\s*[：:]?", text, flags=re.IGNORECASE)
    if focus_marker:
        text = text[: focus_marker.start()]
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def natural_code_key(value: str) -> tuple[int, str]:
    return (0, value.zfill(20)) if value.isdigit() else (1, value)


def detect_csv_encoding(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            pd.read_csv(path, nrows=5, dtype=str, keep_default_na=False, encoding=encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法识别 CSV 编码: {path}")


def read_csv_columns(path: Path, columns: list[str]) -> tuple[pd.DataFrame, str]:
    encoding = detect_csv_encoding(path)
    header = pd.read_csv(path, nrows=0, encoding=encoding).columns.tolist()
    missing = [column for column in columns if column not in header]
    if missing:
        raise ValueError(f"{path.name} 缺少字段: {missing}")
    frame = pd.read_csv(
        path,
        usecols=columns,
        dtype=str,
        keep_default_na=False,
        encoding=encoding,
        low_memory=False,
    )
    for column in frame.columns:
        frame[column] = frame[column].map(clean_text)
    return frame, encoding


def filled_star_count(value: Any) -> int | None:
    text = clean_text(value).replace("**", "").strip()
    if not STAR_PATTERN.fullmatch(text):
        return None
    return text.count("★")


def split_context_value(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    text = re.sub(r"^(?:上游|中游|下游)\s*[-：:]\s*", "", text)
    values = {text}
    values.update(part.strip(" ()（）") for part in SPLIT_PATTERN.split(text))
    for inside in re.findall(r"[（(]([^）)]*)[）)]", text):
        values.update(part.strip() for part in SPLIT_PATTERN.split(inside))
    cleaned = {
        item
        for item in values
        if len(normalize_text(item)) >= 2 and clean_text(item) not in GENERIC_CONTEXT_TERMS
    }
    for item in list(cleaned):
        normalized = clean_text(item)
        if len(normalized) >= 3 and normalized.endswith(("方", "商")):
            cleaned.add(normalized[:-1])
    return sorted(cleaned)


def event_context_terms(event_rows: pd.DataFrame) -> dict[str, int]:
    terms: dict[str, int] = {}
    for field, weight in CONTEXT_WEIGHTS.items():
        for value in event_rows[field].drop_duplicates():
            for term in split_context_value(value):
                normalized = normalize_text(term)
                terms[normalized] = max(terms.get(normalized, 0), weight)

    for title in event_rows["topic_name"].drop_duplicates():
        for token in TECH_TOKEN_PATTERN.findall(title):
            normalized = normalize_text(token)
            if len(normalized) >= 2:
                terms[normalized] = max(terms.get(normalized, 0), 8)
    return terms


def score_path(
    product_name: str,
    hierarchy_path: str,
    terms: dict[str, int],
) -> tuple[int, int, list[str]]:
    target = normalize_text(f"{product_name} {hierarchy_path}")
    matches = [(term, weight) for term, weight in terms.items() if term and term in target]
    matches.sort(key=lambda item: (-item[1], -len(item[0]), item[0]))
    return (
        sum(weight for _, weight in matches),
        sum(weight for _, weight in matches if weight >= 5),
        [term for term, _ in matches],
    )


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def make_stock_record(row: pd.Series, product_count: int, mapped: bool) -> dict[str, Any]:
    return {
        "sourceRowNumber": int(row["source_row_number"]),
        "stockCode": row["stock_code"],
        "stockName": row["stock_name"],
        "rating": row["origin_star_num"],
        "filledStars": 4,
        "mapped": mapped,
        "anchorProductCount": product_count,
    }


def unique_ordered(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_event_draft(
    event_rows: pd.DataFrame,
    company_paths_by_source_row: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    first = event_rows.iloc[0]
    star_rows = event_rows[event_rows["filled_star_count"].eq(4)].copy()
    # Use all rows for topic context because the source's role/segment labels are
    # distributed across stocks; only the anchor-company selection is restricted to 4 stars.
    context_terms = event_context_terms(event_rows)

    candidates: dict[str, dict[str, Any]] = {}
    stocks: list[dict[str, Any]] = []
    for _, stock_row in star_rows.iterrows():
        source_row_number = stock_row["source_row_number"]
        stock_paths = company_paths_by_source_row.get(source_row_number, [])
        unique_product_codes = {path["matched_node_code"] for path in stock_paths}
        stocks.append(make_stock_record(stock_row, len(unique_product_codes), bool(stock_paths)))

        for path in stock_paths:
            code = path["matched_node_code"]
            score, strong_score, matched_terms = score_path(
                path["matched_node_name"],
                path["hierarchy_path"],
                context_terms,
            )
            candidate = candidates.setdefault(
                code,
                {
                    "code": code,
                    "name": path["matched_node_name"],
                    "hierarchyPath": path["hierarchy_path"],
                    "industryPath": [part.strip() for part in path["hierarchy_path"].split(">") if part.strip()],
                    "level5IndustryCode": path["5industry_code"],
                    "level5IndustryName": path["5industry_name"],
                    "level6IndustryCode": path["6industry_code"],
                    "level6IndustryName": path["6industry_name"],
                    "level7ProductCode": path["7industry_code"],
                    "level7ProductName": path["7industry_name"],
                    "matchedSourceLevel": int(path["matched_source_level"]),
                    "relevanceScore": score,
                    "strongRelevanceScore": strong_score,
                    "matchedTerms": matched_terms,
                    "stocks": {},
                },
            )
            candidate["relevanceScore"] = max(candidate["relevanceScore"], score)
            candidate["strongRelevanceScore"] = max(candidate["strongRelevanceScore"], strong_score)
            candidate["matchedTerms"] = unique_ordered([*candidate["matchedTerms"], *matched_terms])
            candidate["stocks"][source_row_number] = {
                "stockCode": stock_row["stock_code"],
                "stockName": stock_row["stock_name"],
                "rating": stock_row["origin_star_num"],
            }

    return {
        "mainId": first["main_id"],
        "uid": first["uid"],
        "title": first["topic_name"],
        "date": first["calendar_day"],
        "newsText": extract_news_text(first["source_reason"]),
        "stocks": stocks,
        "candidates": candidates,
    }


def choose_core_products(
    candidates: dict[str, dict[str, Any]],
    edge_degrees: dict[str, int],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates.values():
        candidate = {**candidate}
        candidate["stockCount"] = len(candidate["stocks"])
        candidate["edgeDegree"] = edge_degrees.get(candidate["code"], 0)
        candidate["mappingType"] = "company_product"
        candidate["bridgeBasis"] = ""
        ranked.append(candidate)

    ranked.sort(
        key=lambda item: (
            -item["strongRelevanceScore"],
            -item["relevanceScore"],
            -item["stockCount"],
            -item["edgeDegree"],
            item["name"],
            natural_code_key(item["code"]),
        )
    )
    topic_relevance = [item for item in ranked if item["strongRelevanceScore"] > 0]
    high_relevance = [item for item in ranked if item["relevanceScore"] >= 3]
    medium_relevance = [item for item in ranked if item["relevanceScore"] >= 2]
    pool = topic_relevance or high_relevance or medium_relevance or ranked
    return pool[:MAX_CORE_PRODUCTS]


def matching_graph_nodes(
    value: str,
    graph_name_index: dict[str, list[dict[str, str]]],
) -> list[tuple[int, dict[str, str]]]:
    normalized = normalize_text(value)
    matches: dict[str, tuple[int, dict[str, str]]] = {}
    maximum_length = min(16, len(normalized))
    for length in range(maximum_length, 2, -1):
        for start in range(0, len(normalized) - length + 1):
            token = normalized[start : start + length]
            for node in graph_name_index.get(token, []):
                existing = matches.get(node["code"])
                if existing is None or length > existing[0]:
                    matches[node["code"]] = (length, node)
    return list(matches.values())


def choose_semantic_bridge(
    draft: dict[str, Any],
    core_products: list[dict[str, Any]],
    graph_name_index: dict[str, list[dict[str, str]]],
    edge_degrees: dict[str, int],
    edge_directions: dict[str, set[str]],
) -> list[dict[str, Any]]:
    if not core_products:
        return []
    covered_directions = {
        direction
        for product in core_products
        for direction in edge_directions.get(product["code"], set())
    }
    if covered_directions == {"上游", "下游"}:
        return []

    core_codes = {product["code"] for product in core_products}
    mapped_stock_values = {
        source_row: stock
        for product in draft["candidates"].values()
        for source_row, stock in product["stocks"].items()
    }
    sources: list[tuple[str, str, dict[str, dict[str, str]]]] = [
        (draft["title"], "event_title", mapped_stock_values)
    ]
    sources.extend(
        (product["name"], f"company_product:{product['name']}", product["stocks"])
        for product in core_products
    )

    candidates: dict[str, dict[str, Any]] = {}
    for source_text, basis, stocks in sources:
        basis_priority = 0 if basis == "event_title" else 1
        for match_length, node in matching_graph_nodes(source_text, graph_name_index):
            if node["code"] in core_codes:
                continue
            missing_direction_gain = len(
                edge_directions.get(node["code"], set()) - covered_directions
            )
            if missing_direction_gain == 0:
                continue
            candidate = candidates.setdefault(
                node["code"],
                {
                    "code": node["code"],
                    "name": node["name"],
                    "hierarchyPath": "",
                    "industryPath": [],
                    "level5IndustryCode": "",
                    "level5IndustryName": "",
                    "level6IndustryCode": "",
                    "level6IndustryName": "",
                    "level7ProductCode": "",
                    "level7ProductName": "",
                    "matchedSourceLevel": 0,
                    "relevanceScore": 0,
                    "strongRelevanceScore": 0,
                    "matchedTerms": [],
                    "stocks": {},
                    "stockCount": 0,
                    "edgeDegree": edge_degrees.get(node["code"], 0),
                    "mappingType": "semantic_bridge",
                    "bridgeBasis": basis,
                    "basisPriority": basis_priority,
                    "matchLength": match_length,
                    "missingDirectionGain": missing_direction_gain,
                },
            )
            candidate["stocks"].update(stocks)
            candidate["stockCount"] = len(candidate["stocks"])
            candidate["basisPriority"] = min(candidate["basisPriority"], basis_priority)
            if basis_priority < candidate["basisPriority"] or match_length > candidate["matchLength"]:
                candidate["bridgeBasis"] = basis
            candidate["matchLength"] = max(candidate["matchLength"], match_length)
            candidate["missingDirectionGain"] = max(
                candidate["missingDirectionGain"], missing_direction_gain
            )

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -item["missingDirectionGain"],
            item["basisPriority"],
            -item["matchLength"],
            -item["stockCount"],
            -item["edgeDegree"],
            item["name"],
        ),
    )
    return ranked[:1]


def build_related_products(
    direction: str,
    core_products: list[dict[str, Any]],
    edge_index: dict[str, list[dict[str, str]]],
) -> tuple[list[dict[str, Any]], int]:
    core_codes = {product["code"] for product in core_products}
    related: dict[str, dict[str, Any]] = {}
    for core in core_products:
        for edge in edge_index.get(core["code"], []):
            if edge["关系"] != direction:
                continue
            related_code = edge["关联产品代码"]
            if related_code in core_codes:
                continue
            item = related.setdefault(
                related_code,
                {
                    "code": related_code,
                    "name": edge["关联产品名称"],
                    "linkedCoreProductCodes": set(),
                    "linkedCoreProductNames": set(),
                    "stockKeys": set(),
                    "originalEdgeCount": 0,
                    "completedEdgeCount": 0,
                },
            )
            item["linkedCoreProductCodes"].add(core["code"])
            item["linkedCoreProductNames"].add(core["name"])
            item["stockKeys"].update(core["stocks"])
            if edge["原始是否已有"].casefold() == "true":
                item["originalEdgeCount"] += 1
            else:
                item["completedEdgeCount"] += 1

    ranked = sorted(
        related.values(),
        key=lambda item: (
            -len(item["linkedCoreProductCodes"]),
            -len(item["stockKeys"]),
            -item["originalEdgeCount"],
            item["name"],
            natural_code_key(item["code"]),
        ),
    )
    output = []
    for item in ranked[:MAX_RELATED_PRODUCTS]:
        output.append(
            {
                "code": item["code"],
                "name": item["name"],
                "anchorCount": len(item["linkedCoreProductCodes"]),
                "stockCount": len(item["stockKeys"]),
                "linkedCoreProductCodes": sorted(item["linkedCoreProductCodes"], key=natural_code_key),
                "linkedCoreProductNames": sorted(item["linkedCoreProductNames"]),
                "evidence": {
                    "original": item["originalEdgeCount"],
                    "directionalCompletion": item["completedEdgeCount"],
                },
            }
        )
    return output, len(ranked)


def build_level5_catalog(nodes: pd.DataFrame) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    valid = nodes[nodes["5industry_code"].ne("")]
    for code, group in valid.groupby("5industry_code", sort=False):
        catalog[code] = {
            "code": code,
            "name": canonical_text(group["5industry_name"]),
            "description": canonical_text(group["5industry_remark"]),
        }
    return catalog


def compact_names(values: Iterable[str], limit: int = 5) -> str:
    names = unique_ordered(values)
    if not names:
        return "暂无直接节点"
    visible = names[:limit]
    suffix = f"等{len(names)}项" if len(names) > limit else ""
    return "、".join(visible) + suffix


def detect_news_variables(news_text: str) -> list[str]:
    return [
        label
        for label, signals in NEWS_VARIABLE_SIGNALS.items()
        if any(signal in news_text for signal in signals)
    ][:5]


def classify_news(news_text: str) -> dict[str, Any]:
    short_matches = [signal for signal in SHORT_DISTURBANCE_SIGNALS if signal in news_text]
    trend_matches = [signal for signal in TREND_SIGNALS if signal in news_text]
    acceleration_matches = [signal for signal in ACCELERATION_SIGNALS if signal in news_text]
    if short_matches:
        code, label, matches = "C", "短期事件扰动", short_matches
    elif trend_matches:
        code, label, matches = "A", "产业趋势变化", trend_matches
    elif acceleration_matches:
        code, label, matches = "B", "景气度加速/减速", acceleration_matches
    else:
        code, label, matches = "C", "短期事件扰动", []
    return {
        "code": code,
        "label": label,
        "matchedSignals": matches[:4],
        "basis": (
            f"主要依据是事件涉及{'、'.join(matches[:4])}"
            if matches
            else "新闻披露的信息尚不足以支持长期趋势或景气加速判断，暂按短期扰动处理"
        ),
    }


def build_simulated_analysis(
    target: dict[str, Any],
    upstream: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    news_title: str,
    news_text: str,
) -> dict[str, Any]:
    core_names = [item["name"] for item in target["matchedCoreProducts"]]
    variables = detect_news_variables(news_text)
    classification = classify_news(news_text)
    description = target["description"] or f"该产业主要覆盖{compact_names(core_names)}等产品与服务"
    description = description.rstrip("。！？；; ")
    analysis_variables = variables or ["下游需求与订单", "产品价格", "原材料与成本", "产能与开工", "市场竞争"]
    variable_text = "、".join(analysis_variables)
    variable_logic = "；".join(VARIABLE_EXPLANATIONS[item] for item in analysis_variables)
    if classification["code"] == "A":
        classification_text = "可能影响未来数个季度的技术路线、商业化进程或供需结构，持续性强于单次经营波动"
    elif classification["code"] == "B":
        classification_text = "长期产业方向没有根本改变，但订单、价格、库存或开工等近期经营指标正在发生变化"
    else:
        classification_text = "影响范围和持续时间仍需后续经营数据确认，暂不足以据此判断产业趋势已经改变"
    text = (
        f"{target['name']}本质上是围绕{compact_names(core_names)}形成的细分产业，{description}。"
        f"从产业链位置看，关键链条可以概括为{compact_names((item['name'] for item in upstream), 4)}"
        f" → {target['name']} → {compact_names((item['name'] for item in downstream), 4)}，"
        "企业通常通过销售相关产品、设备或服务获得收入，收入可先理解为销量或项目量乘以单价，"
        "利润则同时受上游投入成本、制造或交付成本、产能利用率和竞争强度影响，所以这个产业赚钱最关键看的是需求能否兑现并转化为可持续的单位利润。"
        f"景气度主要由{variable_text}决定：{variable_logic}。"
        f"近期事件“{news_title}”带来的关键变化集中在{variable_text}，如果相关变化能够持续兑现，"
        "将通过订单、价格、成本或产能利用率传导至企业收入和利润；如果后续缺少订单、价格和经营数据验证，实际影响可能弱于事件本身的市场关注度。"
        f"从影响性质看，这一事件更接近{classification['code']}类“{classification['label']}”，{classification_text}。"
    )
    output_text = re.sub(r"\s+", " ", text).strip()
    forbidden = [phrase for phrase in CLIENT_BANNED_PHRASES if phrase in output_text]
    if forbidden:
        raise ValueError(f"投资者可见产业解读包含内部过程用语: {forbidden}")
    return {
        "mode": "local_rule_simulation",
        "isRealModelOutput": False,
        "variables": variables,
        "classification": classification,
        "text": output_text,
    }


def build_industry_analysis(
    company_core_products: list[dict[str, Any]],
    level5_catalog: dict[str, dict[str, str]],
    upstream: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    news_title: str,
    news_text: str,
) -> dict[str, Any]:
    level7_products = [
        product
        for product in company_core_products
        if product["matchedSourceLevel"] == 7
        and product["level7ProductName"]
        and product["level5IndustryCode"]
        and product["level5IndustryName"]
    ]
    groups: dict[str, dict[str, Any]] = {}
    for product in level7_products:
        code = product["level5IndustryCode"]
        catalog_item = level5_catalog.get(code, {})
        group = groups.setdefault(
            code,
            {
                "code": code,
                "name": catalog_item.get("name") or product["level5IndustryName"],
                "description": catalog_item.get("description", ""),
                "matchedCoreProducts": [],
                "stockKeys": set(),
                "relevanceScore": 0,
            },
        )
        group["matchedCoreProducts"].append(
            {
                "code": product["level7ProductCode"] or product["code"],
                "name": product["level7ProductName"] or product["name"],
                "stockCount": len(product["stocks"]),
            }
        )
        group["stockKeys"].update(product["stocks"])
        group["relevanceScore"] += product["relevanceScore"]

    if not groups:
        return {
            "status": "unavailable",
            "stage": 1,
            "stageName": "五级产业认知",
            "mode": "simulation",
            "selectionRule": "将入选的七级核心产品按五级产业代码归并，优先选择核心产品数量最多者",
            "sourceLevel7ProductCount": len(level7_products),
            "target": None,
            "candidates": [],
            "simulation": None,
            "reason": "入选核心产品尚未形成可追溯的七级产品到五级产业路径",
        }

    candidates: list[dict[str, Any]] = []
    total_level7_products = len(level7_products)
    for group in groups.values():
        products = sorted(
            group["matchedCoreProducts"],
            key=lambda item: (-item["stockCount"], item["name"], natural_code_key(item["code"])),
        )
        candidates.append(
            {
                "code": group["code"],
                "name": group["name"],
                "description": group["description"],
                "coreProductCount": len(products),
                "stockCount": len(group["stockKeys"]),
                "shareOfLevel7Products": round(len(products) / total_level7_products, 4),
                "relevanceScore": group["relevanceScore"],
                "matchedCoreProducts": products,
            }
        )
    candidates.sort(
        key=lambda item: (
            -item["coreProductCount"],
            -item["stockCount"],
            -item["relevanceScore"],
            item["name"],
            natural_code_key(item["code"]),
        )
    )
    target = candidates[0]
    return {
        "status": "ready",
        "stage": 1,
        "stageName": "五级产业认知",
        "mode": "simulation",
        "selectionRule": (
            "将入选的七级核心产品按五级产业代码归并；先按核心产品数量降序，"
            "并列时依次按关联股票数、相关性得分和产业代码确定唯一分析对象"
        ),
        "sourceLevel7ProductCount": total_level7_products,
        "target": target,
        "candidates": candidates,
        "simulation": build_simulated_analysis(
            target,
            upstream,
            downstream,
            news_title,
            news_text,
        ),
        "reason": "",
    }


def finalize_event(
    draft: dict[str, Any],
    edge_index: dict[str, list[dict[str, str]]],
    level5_catalog: dict[str, dict[str, str]],
    generated_at: str,
) -> dict[str, Any]:
    company_core_products = draft["selectedCoreProducts"]
    bridge_products = draft["semanticBridges"]
    core_products = [*company_core_products, *bridge_products]
    upstream, upstream_total = build_related_products("上游", core_products, edge_index)
    downstream, downstream_total = build_related_products("下游", core_products, edge_index)

    output_core: list[dict[str, Any]] = []
    for core in core_products:
        relation_rows = edge_index.get(core["code"], [])
        output_core.append(
            {
                "code": core["code"],
                "name": core["name"],
                "hierarchyPath": core["hierarchyPath"],
                "industryPath": core["industryPath"],
                "level5Industry": {
                    "code": core["level5IndustryCode"],
                    "name": core["level5IndustryName"],
                },
                "level6Industry": {
                    "code": core["level6IndustryCode"],
                    "name": core["level6IndustryName"],
                },
                "level7Product": {
                    "code": core["level7ProductCode"],
                    "name": core["level7ProductName"],
                },
                "matchedSourceLevel": core["matchedSourceLevel"],
                "mappingType": core["mappingType"],
                "bridgeBasis": core["bridgeBasis"],
                "stockCount": core["stockCount"],
                "stocks": sorted(
                    core["stocks"].values(),
                    key=lambda item: (item["stockName"], item["stockCode"]),
                ),
                "upstreamCount": sum(row["关系"] == "上游" for row in relation_rows),
                "downstreamCount": sum(row["关系"] == "下游" for row in relation_rows),
                "relevanceScore": core["relevanceScore"],
                "strongRelevanceScore": core["strongRelevanceScore"],
                "matchedTerms": core["matchedTerms"],
            }
        )

    mapped_stocks = [stock for stock in draft["stocks"] if stock["mapped"]]
    unmapped_stocks = [stock for stock in draft["stocks"] if not stock["mapped"]]
    if not draft["stocks"]:
        status = "no_four_star_stocks"
    elif not mapped_stocks:
        status = "no_company_product_mapping"
    elif not core_products:
        status = "no_relevant_core_products"
    elif not upstream and not downstream:
        status = "core_products_only"
    else:
        status = "ready"

    caveats = [
        "4星按 origin_star_num 中恰好4个实心星解析，包含★★★★与★★★★☆。",
        "核心产品仅来自 stock_name 公司映射；事件行业标签兜底不用于上下游扩展。",
        "上下游为双向补全明细中的直接一跳关系，未做多跳推断。",
    ]
    if bridge_products:
        caveats.append(
            "公司精确产品缺少直接边时，使用同名主题/上位产品作为显式标记的语义桥接节点。"
        )
    if unmapped_stocks:
        caveats.append(f"{len(unmapped_stocks)}只4星标的未在本地公司产品图谱中穿透。")

    industry_analysis = build_industry_analysis(
        company_core_products,
        level5_catalog,
        upstream,
        downstream,
        draft["title"],
        draft["newsText"],
    )
    return {
        "schemaVersion": 3,
        "generatedAt": generated_at,
        "status": status,
        "event": {
            "mainId": draft["mainId"],
            "uid": draft["uid"],
            "title": draft["title"],
            "date": draft["date"],
        },
        "selection": {
            "rule": "filled_star_count == 4",
            "sourceStockCount": len(draft["stocks"]),
            "mappedStockCount": len(mapped_stocks),
            "unmappedStockCount": len(unmapped_stocks),
            "stocks": draft["stocks"],
            "unmappedStocks": unmapped_stocks,
        },
        "totals": {
            "candidateCoreProductCount": len(draft["candidates"]),
            "selectedCoreProductCount": len(output_core),
            "selectedCompanyCoreProductCount": len(company_core_products),
            "semanticBridgeCount": len(bridge_products),
            "upstreamCandidateCount": upstream_total,
            "downstreamCandidateCount": downstream_total,
            "shownUpstreamCount": len(upstream),
            "shownDownstreamCount": len(downstream),
        },
        "chain": {
            "upstream": upstream,
            "core": output_core,
            "downstream": downstream,
        },
        "industryAnalysis": industry_analysis,
        "caveats": caveats,
    }


def validate_sources(events: pd.DataFrame, paths: pd.DataFrame, edges: pd.DataFrame) -> None:
    if events["source_row_number"].duplicated().any():
        raise ValueError("事件源行号不唯一")
    if events.groupby("main_id")["uid"].nunique().max() > 1:
        raise ValueError("同一 main_id 对应多个 uid，无法安全按 main_id 输出")

    path_keys = paths[["source_row_number", "main_id", "uid", "stock_code", "stock_name"]].drop_duplicates()
    source_keys = events[["source_row_number", "main_id", "uid", "stock_code", "stock_name"]]
    checked = path_keys.merge(source_keys, on="source_row_number", how="left", suffixes=("_path", "_event"), indicator=True)
    mismatched = checked["_merge"].ne("both")
    for field in ("main_id", "uid", "stock_code", "stock_name"):
        mismatched |= checked[f"{field}_path"].ne(checked[f"{field}_event"])
    if mismatched.any():
        raise ValueError(f"产业路径与事件源行键不一致: {int(mismatched.sum())}行")

    edge_key = ["当前产品代码", "关系", "关联产品代码"]
    if edges.duplicated(edge_key).any():
        raise ValueError("双向补全明细存在重复方向边")
    if not set(edges["关系"]).issubset({"上游", "下游"}):
        raise ValueError("双向补全明细出现未知关系值")
    upstream = edges["关系"].eq("上游")
    downstream = edges["关系"].eq("下游")
    bad_upstream = upstream & (
        edges["关联产品代码"].ne(edges["产业链上游代码"])
        | edges["当前产品代码"].ne(edges["产业链下游代码"])
    )
    bad_downstream = downstream & (
        edges["当前产品代码"].ne(edges["产业链上游代码"])
        | edges["关联产品代码"].ne(edges["产业链下游代码"])
    )
    if bad_upstream.any() or bad_downstream.any():
        raise ValueError("双向补全明细的关系方向与上下游代码不一致")


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    workspace_root = project_root.parent
    parser = argparse.ArgumentParser(description="生成新闻4星标的的一跳产业链上下游 JSON")
    parser.add_argument(
        "--events",
        type=Path,
        default=workspace_root / "1.迅兔事件数据获取" / "蓝宝书_事件关联股票.csv",
    )
    parser.add_argument(
        "--paths",
        type=Path,
        default=project_root / "data" / "generated" / "event_stock_industry_paths.csv",
    )
    parser.add_argument(
        "--edges",
        type=Path,
        default=project_root / "data" / "generated" / "产业链_双向补全明细.csv",
    )
    parser.add_argument(
        "--nodes",
        type=Path,
        default=workspace_root / "2.产业数据图谱" / "20260820节点.csv",
    )
    parser.add_argument(
        "--prompt-template",
        type=Path,
        default=project_root / "prompts" / "industry-cognition-stage1-v1.md",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "public" / "data" / "impact-chains",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events, event_encoding = read_csv_columns(args.events, EVENT_COLUMNS)
    paths, path_encoding = read_csv_columns(args.paths, PATH_COLUMNS)
    edges, edge_encoding = read_csv_columns(args.edges, EDGE_COLUMNS)
    nodes, node_encoding = read_csv_columns(args.nodes, NODE_COLUMNS)
    prompt_template = args.prompt_template.read_text(encoding="utf-8")
    missing_placeholders = [
        placeholder
        for placeholder in ("{{industry_name}}", "{{industry_description}}", "{{news_text}}")
        if placeholder not in prompt_template
    ]
    if missing_placeholders:
        raise ValueError(f"产业认知提示词缺少占位符: {missing_placeholders}")
    level5_catalog = build_level5_catalog(nodes)

    events.insert(0, "source_row_number", [str(number) for number in range(2, len(events) + 2)])
    events["filled_star_count"] = events["origin_star_num"].map(filled_star_count)
    validate_sources(events, paths, edges)

    company_paths = paths[
        paths["is_real_industry_path"].eq("1")
        & paths["mapping_method"].str.startswith("stock_name_")
        & paths["matched_node_code"].ne("")
    ].copy()
    company_paths = company_paths.drop_duplicates(
        ["source_row_number", "matched_node_code"], keep="first"
    )
    company_paths_by_source_row: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in company_paths.to_dict("records"):
        company_paths_by_source_row[row["source_row_number"]].append(row)

    drafts: list[dict[str, Any]] = []
    for _, event_rows in events.groupby("uid", sort=False):
        draft = build_event_draft(event_rows, company_paths_by_source_row)
        drafts.append(draft)

    edge_degrees = edges["当前产品代码"].value_counts().to_dict()
    edge_directions = (
        edges.groupby("当前产品代码")["关系"]
        .agg(lambda values: set(values))
        .to_dict()
    )
    graph_name_index: dict[str, list[dict[str, str]]] = defaultdict(list)
    graph_nodes = edges[["当前产品代码", "当前产品名称"]].drop_duplicates()
    for code, name in graph_nodes.itertuples(index=False, name=None):
        normalized_name = normalize_text(name)
        if len(normalized_name) >= 3:
            graph_name_index[normalized_name].append({"code": code, "name": name})

    expansion_codes: set[str] = set()
    for draft in drafts:
        selected_core = choose_core_products(draft["candidates"], edge_degrees)
        semantic_bridges = choose_semantic_bridge(
            draft,
            selected_core,
            graph_name_index,
            edge_degrees,
            edge_directions,
        )
        draft["selectedCoreProducts"] = selected_core
        draft["semanticBridges"] = semantic_bridges
        expansion_codes.update(product["code"] for product in [*selected_core, *semantic_bridges])

    relevant_edges = edges[edges["当前产品代码"].isin(expansion_codes)].copy()
    edge_index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in relevant_edges.to_dict("records"):
        edge_index[row["当前产品代码"]].append(row)

    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    index_events: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    analysis_status_counts: dict[str, int] = defaultdict(int)
    for draft in drafts:
        payload = finalize_event(
            draft,
            edge_index,
            level5_catalog,
            generated_at,
        )
        main_id = payload["event"]["mainId"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", main_id):
            raise ValueError(f"main_id 不适合用作文件名: {main_id!r}")
        filename = f"{main_id}.json"
        atomic_write_json(args.output_dir / filename, payload)
        status_counts[payload["status"]] += 1
        analysis_status_counts[payload["industryAnalysis"]["status"]] += 1
        analysis_target = payload["industryAnalysis"]["target"]
        index_events.append(
            {
                **payload["event"],
                "status": payload["status"],
                "file": filename,
                "sourceStockCount": payload["selection"]["sourceStockCount"],
                "mappedStockCount": payload["selection"]["mappedStockCount"],
                "coreProductCount": payload["totals"]["selectedCoreProductCount"],
                "upstreamCount": payload["totals"]["shownUpstreamCount"],
                "downstreamCount": payload["totals"]["shownDownstreamCount"],
                "industryAnalysisStatus": payload["industryAnalysis"]["status"],
                "level5IndustryCode": analysis_target["code"] if analysis_target else "",
                "level5IndustryName": analysis_target["name"] if analysis_target else "",
            }
        )

    index_events.sort(key=lambda item: (item["date"], natural_code_key(item["mainId"])), reverse=True)
    manifest = {
        "schemaVersion": 3,
        "generatedAt": generated_at,
        "eventCount": len(index_events),
        "statusCounts": dict(sorted(status_counts.items())),
        "industryAnalysisStatusCounts": dict(sorted(analysis_status_counts.items())),
        "source": {
            "events": args.events.name,
            "eventEncoding": event_encoding,
            "paths": args.paths.name,
            "pathEncoding": path_encoding,
            "edges": args.edges.name,
            "edgeEncoding": edge_encoding,
            "nodes": args.nodes.name,
            "nodeEncoding": node_encoding,
        },
        "events": index_events,
    }
    atomic_write_json(args.output_dir / "index.json", manifest)

    ready_or_core_only = status_counts.get("ready", 0) + status_counts.get("core_products_only", 0)
    print(f"新闻数: {len(index_events):,}")
    print(f"恰好4个实心星的新闻: {sum(item['sourceStockCount'] > 0 for item in index_events):,}")
    print(f"可展示核心产品的新闻: {ready_or_core_only:,}")
    print(f"可展示上下游的新闻: {status_counts.get('ready', 0):,}")
    print(f"可生成五级产业认知语料的新闻: {analysis_status_counts.get('ready', 0):,}")
    print(f"状态分布: {dict(sorted(status_counts.items()))}")
    print(f"输出目录: {args.output_dir}")


if __name__ == "__main__":
    main()
