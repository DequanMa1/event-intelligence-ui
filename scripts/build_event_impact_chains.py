from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
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
    "hierarchy_path",
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


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"[\t\r\n]+", " ", str(value).replace("\u3000", " ").strip())


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


def finalize_event(
    draft: dict[str, Any],
    edge_index: dict[str, list[dict[str, str]]],
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

    return {
        "schemaVersion": 1,
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
    for draft in drafts:
        payload = finalize_event(draft, edge_index, generated_at)
        main_id = payload["event"]["mainId"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", main_id):
            raise ValueError(f"main_id 不适合用作文件名: {main_id!r}")
        filename = f"{main_id}.json"
        atomic_write_json(args.output_dir / filename, payload)
        status_counts[payload["status"]] += 1
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
            }
        )

    index_events.sort(key=lambda item: (item["date"], natural_code_key(item["mainId"])), reverse=True)
    manifest = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "eventCount": len(index_events),
        "statusCounts": dict(sorted(status_counts.items())),
        "source": {
            "events": args.events.name,
            "eventEncoding": event_encoding,
            "paths": args.paths.name,
            "pathEncoding": path_encoding,
            "edges": args.edges.name,
            "edgeEncoding": edge_encoding,
        },
        "events": index_events,
    }
    atomic_write_json(args.output_dir / "index.json", manifest)

    ready_or_core_only = status_counts.get("ready", 0) + status_counts.get("core_products_only", 0)
    print(f"新闻数: {len(index_events):,}")
    print(f"恰好4个实心星的新闻: {sum(item['sourceStockCount'] > 0 for item in index_events):,}")
    print(f"可展示核心产品的新闻: {ready_or_core_only:,}")
    print(f"可展示上下游的新闻: {status_counts.get('ready', 0):,}")
    print(f"状态分布: {dict(sorted(status_counts.items()))}")
    print(f"输出目录: {args.output_dir}")


if __name__ == "__main__":
    main()
