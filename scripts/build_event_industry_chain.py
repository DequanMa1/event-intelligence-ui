from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


EVENT_FILE_NAME = "蓝宝书_事件关联股票.csv"
INDUSTRY_FILE_NAME = "20260820节点.csv"

DETAIL_OUTPUT = "event_stock_industry_paths.csv"
SUMMARY_OUTPUT = "event_industry_chain_summary.csv"
COVERAGE_OUTPUT = "event_industry_mapping_coverage.csv"

EVENT_COLUMNS = [
    "main_id",
    "uid",
    "calendar_day",
    "seq",
    "topic_name",
    "first_level",
    "second_level",
    "stock_code",
    "stock_name",
    "industry1",
    "industry2",
    "industry3",
    "stock_feedback_question_id",
]

INDUSTRY_LEVELS = range(2, 8)
INDUSTRY_CODE_COLUMNS = [f"{level}industry_code" for level in INDUSTRY_LEVELS]
INDUSTRY_NAME_COLUMNS = [f"{level}industry_name" for level in INDUSTRY_LEVELS]

# Substring matching is intentionally restricted to a small technical-token allowlist.
# Generic Chinese labels such as "软件平台" are too broad and create unrelated paths.
SUBSTRING_FALLBACK_TOKENS = {"cpu", "gpu", "asic"}
SEMICONDUCTOR_PATH_TOKENS = {"半导体", "集成电路"}


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else format(value, "g")
    return re.sub(r"[\t\r\n]+", " ", str(value).replace("\u3000", " ").strip())


def clean_code(value: Any) -> str:
    text = clean_text(value)
    return text[:-2] if re.fullmatch(r"\d+\.0", text) else text


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"\s+", "", text)


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "\x1f".join(clean_text(part) for part in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:18]
    return f"{prefix}:{digest}"


def json_values(values: Iterable[Any]) -> str:
    cleaned = sorted({clean_text(value) for value in values if clean_text(value)})
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def choose_canonical(values: Iterable[Any]) -> str:
    cleaned = [clean_text(value) for value in values if clean_text(value)]
    if not cleaned:
        return ""
    counts = Counter(cleaned)
    return sorted(counts, key=lambda item: (-counts[item], -len(item), item))[0]


def split_companies(value: Any) -> list[str]:
    text = clean_text(value).replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def detect_csv_encoding(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            pd.read_csv(path, nrows=5, dtype=str, keep_default_na=False, encoding=encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法识别 CSV 编码: {path}")


def clean_dataframe(df: pd.DataFrame, code_columns: Iterable[str] = ()) -> pd.DataFrame:
    result = df.copy()
    code_columns = set(code_columns)
    for column in result.columns:
        cleaner = clean_code if column in code_columns else clean_text
        result[column] = result[column].map(cleaner)
    return result


def stock_name_variants(value: Any) -> set[str]:
    """Generate conservative aliases; callers only accept aliases with one target."""
    raw = unicodedata.normalize("NFKC", clean_text(value))
    candidates = {raw}

    outside = re.sub(r"[（(][^）)]*[）)]", "", raw).strip()
    if outside:
        candidates.add(outside)
    for inside in re.findall(r"[（(]([^）)]*)[）)]", raw):
        if inside.strip():
            candidates.add(inside.strip())

    expanded = set(candidates)
    for candidate in list(candidates):
        for part in re.split(r"[/／、,，;；|]", candidate):
            if part.strip():
                expanded.add(part.strip())

    final: set[str] = set()
    for candidate in expanded:
        normalized = normalize_name(candidate)
        if not normalized:
            continue
        final.add(normalized)
        final.add(re.sub(r"^\*?st", "", normalized, flags=re.IGNORECASE))
        final.add(re.sub(r"-(?:w|sw|b)$", "", normalized, flags=re.IGNORECASE))
        for suffix in ("股份有限公司", "有限责任公司", "有限公司"):
            if normalized.endswith(suffix):
                final.add(normalized[: -len(suffix)])
    return {item for item in final if item}


GENERIC_LABEL_TOKENS = {
    "上游",
    "中游",
    "下游",
    "核心参与方",
    "核心需求方",
    "终端客户",
    "其他",
}


def industry_label_tokens(value: Any) -> list[tuple[str, str]]:
    """Return (normalized token, display token), preserving useful composite parts."""
    raw = unicodedata.normalize("NFKC", clean_text(value))
    if not raw:
        return []

    displays: list[str] = [raw]
    if ":" in raw or "：" in raw:
        suffix = re.split(r"[:：]", raw)[-1].strip()
        if suffix:
            displays.append(suffix)

    outside = re.sub(r"[（(][^）)]*[）)]", "", raw).strip()
    if outside:
        displays.append(outside)
    displays.extend(part.strip() for part in re.findall(r"[（(]([^）)]*)[）)]", raw) if part.strip())

    for display in list(displays):
        displays.extend(part.strip() for part in re.split(r"[/／、,，;；+＋&＆|]", display) if part.strip())

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for display in displays:
        normalized = normalize_name(display)
        if len(normalized) < 2 or normalized in {normalize_name(item) for item in GENERIC_LABEL_TOKENS}:
            continue
        if normalized not in seen:
            result.append((normalized, display))
            seen.add(normalized)
    return result


def validate_columns(df: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise ValueError(f"{label} 缺少必要字段: {missing}")


def read_sources(event_path: Path, industry_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    event_encoding = detect_csv_encoding(event_path)
    industry_encoding = detect_csv_encoding(industry_path)

    header = pd.read_csv(event_path, nrows=0, encoding=event_encoding)
    validate_columns(header, EVENT_COLUMNS, event_path.name)
    events = pd.read_csv(
        event_path,
        dtype=str,
        keep_default_na=False,
        encoding=event_encoding,
        usecols=EVENT_COLUMNS,
    )
    events = clean_dataframe(events, ["main_id", "seq"])
    events.insert(0, "source_row_number", range(2, len(events) + 2))
    events.insert(
        1,
        "event_stock_row_id",
        [
            stable_id(
                "event_stock",
                row.uid,
                row.source_row_number,
                row.stock_code,
                row.stock_name,
                row.first_level,
                row.second_level,
            )
            for row in events.itertuples(index=False)
        ],
    )

    industries = pd.read_csv(
        industry_path,
        dtype=str,
        keep_default_na=False,
        encoding=industry_encoding,
    )
    required_industry_columns = ["id", "6industry_comp_name", "7industry_comp_name"]
    required_industry_columns += INDUSTRY_CODE_COLUMNS + INDUSTRY_NAME_COLUMNS
    validate_columns(industries, required_industry_columns, industry_path.name)
    industries = clean_dataframe(industries, ["id", *INDUSTRY_CODE_COLUMNS])
    metadata = {"event_encoding": event_encoding, "industry_encoding": industry_encoding}
    return events, industries, metadata


def industry_path_record(row: pd.Series, matched_source_level: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "industry_depth": matched_source_level - 1,
        "matched_source_level": matched_source_level,
        "matched_node_code": row[f"{matched_source_level}industry_code"],
        "matched_node_name": row[f"{matched_source_level}industry_name"],
        "industry_source_node_key": f"deep:L{matched_source_level}:{row[f'{matched_source_level}industry_code']}",
        "industry_source_row_id": row["id"],
    }
    path_names: list[str] = []
    for level in INDUSTRY_LEVELS:
        code = row[f"{level}industry_code"] if level <= matched_source_level else ""
        name = row[f"{level}industry_name"] if level <= matched_source_level else ""
        result[f"{level}industry_code"] = code
        result[f"{level}industry_name"] = name
        if name:
            path_names.append(name)
    result["hierarchy_path"] = " > ".join(path_names)
    return result


def build_company_indexes(
    industries: pd.DataFrame,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, set[str]],
    dict[str, str],
]:
    level7_index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    level6_index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    company_display_names: dict[str, list[str]] = defaultdict(list)

    for _, row in industries.iterrows():
        path = industry_path_record(row, 7)
        for company_name in split_companies(row["7industry_comp_name"]):
            normalized = normalize_name(company_name)
            company_display_names[normalized].append(company_name)
            key = path["industry_source_node_key"]
            level7_index[normalized][key] = {
                **path,
                "matched_company_name": company_name,
            }

    for _, row in industries.drop_duplicates("6industry_code").iterrows():
        path = industry_path_record(row, 6)
        for company_name in split_companies(row["6industry_comp_name"]):
            normalized = normalize_name(company_name)
            company_display_names[normalized].append(company_name)
            key = path["industry_source_node_key"]
            level6_index[normalized][key] = {
                **path,
                "matched_company_name": company_name,
            }

    variant_targets: dict[str, set[str]] = defaultdict(set)
    for normalized, display_names in company_display_names.items():
        for display_name in display_names:
            for variant in stock_name_variants(display_name):
                variant_targets[variant].add(normalized)

    canonical_company_names = {
        normalized: choose_canonical(display_names)
        for normalized, display_names in company_display_names.items()
    }
    level7 = {key: list(value.values()) for key, value in level7_index.items()}
    level6 = {key: list(value.values()) for key, value in level6_index.items()}
    return level7, level6, variant_targets, canonical_company_names


def match_company_paths(
    stock_name: str,
    level7_index: dict[str, list[dict[str, Any]]],
    level6_index: dict[str, list[dict[str, Any]]],
    variant_targets: dict[str, set[str]],
    canonical_company_names: dict[str, str],
) -> tuple[str, str, list[dict[str, Any]]]:
    normalized = normalize_name(stock_name)
    if normalized in level7_index:
        return "stock_name_exact_level7", canonical_company_names[normalized], level7_index[normalized]
    if normalized in level6_index:
        return "stock_name_exact_level6", canonical_company_names[normalized], level6_index[normalized]

    candidate_targets: set[str] = set()
    for variant in stock_name_variants(stock_name):
        targets = variant_targets.get(variant, set())
        if len(targets) == 1:
            candidate_targets.update(targets)
    if len(candidate_targets) != 1:
        return "", "", []

    target = next(iter(candidate_targets))
    if target in level7_index:
        return "stock_name_alias_level7", canonical_company_names[target], level7_index[target]
    if target in level6_index:
        return "stock_name_alias_level6", canonical_company_names[target], level6_index[target]
    return "", "", []


def build_node_name_index(industries: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for level in INDUSTRY_LEVELS:
        code_column = f"{level}industry_code"
        name_column = f"{level}industry_name"
        for _, row in industries.drop_duplicates(code_column).iterrows():
            record = industry_path_record(row, level)
            record["path_normalized_names"] = {
                normalize_name(row[f"{path_level}industry_name"])
                for path_level in range(2, level + 1)
            }
            index[normalize_name(row[name_column])].append(record)
    return index


def build_substring_node_index(
    events: pd.DataFrame,
    node_name_index: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Precompute conservative token-in-node-name matches for composite labels such as CPU/GPU/ASIC."""
    tokens: set[str] = set()
    for field in FALLBACK_FIELDS:
        for value in events[field].drop_duplicates():
            tokens.update(token for token, _ in industry_label_tokens(value))

    node_names = list(node_name_index)
    result: dict[str, list[dict[str, Any]]] = {}
    for token in sorted(tokens):
        if token in node_name_index or token not in SUBSTRING_FALLBACK_TOKENS:
            continue
        matched_names = [node_name for node_name in node_names if token in node_name]
        candidates = [record for node_name in matched_names for record in node_name_index[node_name]]
        # CPU/GPU/ASIC have unrelated homonyms in chemicals, vehicles and equipment.
        # Only retain the intended electronic-semiconductor knowledge-graph branch.
        candidates = [
            record
            for record in candidates
            if normalize_name(record["2industry_name"]) == normalize_name("电子")
            and bool(record["path_normalized_names"] & SEMICONDUCTOR_PATH_TOKENS)
        ]
        if candidates:
            result[token] = candidates
    return result


FALLBACK_FIELDS = ("industry3", "industry2", "industry1", "second_level", "first_level")
EXPECTED_SOURCE_LEVEL = {"industry1": 2, "industry2": 3, "industry3": 4}


def match_industry_label_paths(
    event_row: pd.Series,
    node_name_index: dict[str, list[dict[str, Any]]],
    substring_node_index: dict[str, list[dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    context_labels = {
        normalize_name(event_row[field])
        for field in ("industry1", "industry2", "industry3")
        if normalize_name(event_row[field])
    }

    for field in FALLBACK_FIELDS:
        token_matches: list[dict[str, Any]] = []
        for token, display_token in industry_label_tokens(event_row[field]):
            candidates = node_name_index.get(token, [])
            label_match_type = "exact"
            if not candidates:
                candidates = substring_node_index.get(token, [])
                label_match_type = "substring"
            if not candidates:
                continue

            def rank(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
                level = int(candidate["matched_source_level"])
                compatibility = len(context_labels & candidate["path_normalized_names"])
                if field in EXPECTED_SOURCE_LEVEL:
                    distance = abs(level - EXPECTED_SOURCE_LEVEL[field])
                else:
                    distance = 0
                return (distance, -compatibility, -level, candidate["matched_node_code"])

            ranked = sorted(candidates, key=rank)
            best_rank = rank(ranked[0])[:3]
            for candidate in ranked:
                if rank(candidate)[:3] != best_rank:
                    break
                token_matches.append(
                    {
                        **candidate,
                        "match_basis_field": field,
                        "match_basis_value": event_row[field],
                        "match_basis_token": display_token,
                        "label_match_type": label_match_type,
                    }
                )
        if token_matches:
            deduped: dict[str, dict[str, Any]] = {}
            for candidate in token_matches:
                deduped[candidate["industry_source_node_key"]] = candidate
            return field, list(deduped.values())
    return "", []


def base_detail_record(event_row: pd.Series) -> dict[str, Any]:
    return {
        "event_stock_row_id": event_row["event_stock_row_id"],
        "source_row_number": event_row["source_row_number"],
        "main_id": event_row["main_id"],
        "uid": event_row["uid"],
        "calendar_day": event_row["calendar_day"],
        "seq": event_row["seq"],
        "topic_name": event_row["topic_name"],
        "event_feedback_id": event_row["stock_feedback_question_id"],
        "stock_code": event_row["stock_code"],
        "stock_name": event_row["stock_name"],
        "normalized_stock_name": normalize_name(event_row["stock_name"]),
        "source_first_level": event_row["first_level"],
        "source_second_level": event_row["second_level"],
        "source_industry1": event_row["industry1"],
        "source_industry2": event_row["industry2"],
        "source_industry3": event_row["industry3"],
    }


def empty_industry_path() -> dict[str, Any]:
    result: dict[str, Any] = {
        "industry_depth": "",
        "matched_source_level": "",
        "matched_node_code": "",
        "matched_node_name": "",
        "industry_source_node_key": "",
        "industry_source_row_id": "",
        "hierarchy_path": "",
    }
    for level in INDUSTRY_LEVELS:
        result[f"{level}industry_code"] = ""
        result[f"{level}industry_name"] = ""
    return result


def build_detail(
    events: pd.DataFrame,
    industries: pd.DataFrame,
) -> pd.DataFrame:
    level7_index, level6_index, variant_targets, canonical_company_names = build_company_indexes(industries)
    node_name_index = build_node_name_index(industries)
    substring_node_index = build_substring_node_index(events, node_name_index)
    records: list[dict[str, Any]] = []

    for _, event_row in events.iterrows():
        base = base_detail_record(event_row)
        method, matched_company_name, company_paths = match_company_paths(
            event_row["stock_name"],
            level7_index,
            level6_index,
            variant_targets,
            canonical_company_names,
        )
        if company_paths:
            for path in company_paths:
                records.append(
                    {
                        "mapping_id": stable_id(
                            "event_industry",
                            event_row["event_stock_row_id"],
                            method,
                            path["industry_source_node_key"],
                        ),
                        **base,
                        "mapping_method": method,
                        "match_basis_field": "stock_name",
                        "match_basis_value": event_row["stock_name"],
                        "match_basis_token": event_row["stock_name"],
                        "matched_company_name": matched_company_name,
                        "is_real_industry_path": 1,
                        **{key: value for key, value in path.items() if key != "matched_company_name"},
                        "mapping_note": "公司名称直接映射到第7层产品" if method.endswith("level7") else "无第7层公司关系，回退到第6层品类",
                    }
                )
            continue

        fallback_field, fallback_paths = match_industry_label_paths(
            event_row,
            node_name_index,
            substring_node_index,
        )
        if fallback_paths:
            for path in fallback_paths:
                records.append(
                    {
                        "mapping_id": stable_id(
                            "event_industry",
                            event_row["event_stock_row_id"],
                            "industry_label_fallback",
                            path["industry_source_node_key"],
                        ),
                        **base,
                        "mapping_method": f"industry_label_fallback_{fallback_field}_{path['label_match_type']}",
                        "match_basis_field": path["match_basis_field"],
                        "match_basis_value": path["match_basis_value"],
                        "match_basis_token": path["match_basis_token"],
                        "matched_company_name": "",
                        "is_real_industry_path": 1,
                        **{
                            key: value
                            for key, value in path.items()
                            if key not in {
                                "path_normalized_names",
                                "match_basis_field",
                                "match_basis_value",
                                "match_basis_token",
                                "label_match_type",
                            }
                        },
                        "mapping_note": (
                            "股票名称未命中公司名单，使用事件表行业标签精确回退"
                            if path["label_match_type"] == "exact"
                            else "股票名称及行业标签精确名称均未命中，使用标签包含匹配回退"
                        ),
                    }
                )
            continue

        records.append(
            {
                "mapping_id": stable_id(
                    "event_industry",
                    event_row["event_stock_row_id"],
                    "unmatched",
                ),
                **base,
                "mapping_method": "unmatched_stock_and_industry_labels",
                "match_basis_field": "",
                "match_basis_value": "",
                "match_basis_token": "",
                "matched_company_name": "",
                "is_real_industry_path": 0,
                **empty_industry_path(),
                "mapping_note": "该股票行暂无公司或行业标签映射；保留记录供审计",
            }
        )

    detail = pd.DataFrame(records)
    return detail.sort_values(
        ["calendar_day", "seq", "uid", "source_row_number", "is_real_industry_path", "hierarchy_path"],
        ascending=[True, True, True, True, False, True],
    ).reset_index(drop=True)


def build_summary(events: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    real = detail[detail["is_real_industry_path"].eq(1)].copy()
    records: list[dict[str, Any]] = []

    for (uid, root_code), group in real.groupby(["uid", "2industry_code"], sort=False):
        event = events[events["uid"].eq(uid)].iloc[0]
        methods = sorted(set(group["mapping_method"]))
        records.append(
            {
                "event_chain_id": stable_id("event_chain", uid, root_code),
                "main_id": event["main_id"],
                "uid": uid,
                "calendar_day": event["calendar_day"],
                "seq": event["seq"],
                "topic_name": event["topic_name"],
                "2industry_code": root_code,
                "2industry_name": choose_canonical(group["2industry_name"]),
                "matched_stock_count": len(group[["stock_code", "stock_name"]].drop_duplicates()),
                "matched_event_stock_row_count": group["event_stock_row_id"].nunique(),
                "path_count": len(group),
                "company_based_path_count": int(group["mapping_method"].str.startswith("stock_name_").sum()),
                "industry_fallback_path_count": int(group["mapping_method"].str.startswith("industry_label_").sum()),
                "level7_product_count": group.loc[group["7industry_code"].ne(""), "7industry_code"].nunique(),
                "stock_names_json": json_values(group["stock_name"]),
                "matched_company_names_json": json_values(group["matched_company_name"]),
                "level3_nodes_json": json_values(group["3industry_name"]),
                "level4_nodes_json": json_values(group["4industry_name"]),
                "level5_nodes_json": json_values(group["5industry_name"]),
                "level6_nodes_json": json_values(group["6industry_name"]),
                "level7_products_json": json_values(group["7industry_name"]),
                "mapping_methods_json": json_values(methods),
            }
        )

    covered_uids = set(real["uid"])
    for uid in sorted(set(events["uid"]) - covered_uids):
        event = events[events["uid"].eq(uid)].iloc[0]
        records.append(
            {
                "event_chain_id": stable_id("event_chain", uid, "UNMATCHED"),
                "main_id": event["main_id"],
                "uid": uid,
                "calendar_day": event["calendar_day"],
                "seq": event["seq"],
                "topic_name": event["topic_name"],
                "2industry_code": "UNMATCHED",
                "2industry_name": "未匹配",
                "matched_stock_count": 0,
                "matched_event_stock_row_count": 0,
                "path_count": 0,
                "company_based_path_count": 0,
                "industry_fallback_path_count": 0,
                "level7_product_count": 0,
                "stock_names_json": "[]",
                "matched_company_names_json": "[]",
                "level3_nodes_json": "[]",
                "level4_nodes_json": "[]",
                "level5_nodes_json": "[]",
                "level6_nodes_json": "[]",
                "level7_products_json": "[]",
                "mapping_methods_json": "[]",
            }
        )

    return pd.DataFrame(records).sort_values(["calendar_day", "seq", "uid", "2industry_name"]).reset_index(drop=True)


def build_coverage(events: pd.DataFrame, detail: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for uid, event_group in events.groupby("uid", sort=False):
        detail_group = detail[detail["uid"].eq(uid)]
        real = detail_group[detail_group["is_real_industry_path"].eq(1)]
        company_rows = set(
            real.loc[real["mapping_method"].str.startswith("stock_name_"), "event_stock_row_id"]
        )
        fallback_rows = set(
            real.loc[real["mapping_method"].str.startswith("industry_label_"), "event_stock_row_id"]
        )
        matched_rows = company_rows | fallback_rows
        all_rows = set(event_group["event_stock_row_id"])
        unmatched_rows = all_rows - matched_rows
        first = event_group.iloc[0]
        records.append(
            {
                "main_id": first["main_id"],
                "uid": uid,
                "calendar_day": first["calendar_day"],
                "seq": first["seq"],
                "topic_name": first["topic_name"],
                "source_stock_row_count": len(event_group),
                "unique_stock_count": len(event_group[["stock_code", "stock_name"]].drop_duplicates()),
                "company_matched_stock_row_count": len(company_rows),
                "industry_fallback_stock_row_count": len(fallback_rows),
                "unmatched_stock_row_count": len(unmatched_rows),
                "stock_row_match_rate": round(len(matched_rows) / len(all_rows), 6) if all_rows else 0,
                "real_industry_path_count": len(real),
                "industry_chain_count": real["2industry_code"].nunique(),
                "level7_product_count": real.loc[real["7industry_code"].ne(""), "7industry_code"].nunique(),
                "has_real_industry_path": 1 if len(real) else 0,
                "coverage_status": "covered" if len(real) else "uncovered",
                "mapping_methods_json": json_values(real["mapping_method"]),
                "unmatched_stocks_json": json_values(
                    event_group.loc[event_group["event_stock_row_id"].isin(unmatched_rows), "stock_name"]
                ),
            }
        )
    coverage = pd.DataFrame(records)
    summary_uids = set(summary["uid"])
    coverage["present_in_summary"] = coverage["uid"].isin(summary_uids).astype(int)
    return coverage.sort_values(["calendar_day", "seq", "uid"]).reset_index(drop=True)


def validate_outputs(
    events: pd.DataFrame,
    detail: pd.DataFrame,
    summary: pd.DataFrame,
    coverage: pd.DataFrame,
    allow_unmatched_news: bool,
) -> None:
    input_uids = set(events["uid"])
    input_stock_rows = set(events["event_stock_row_id"])
    checks = {
        "event_stock_row_id unique": not events["event_stock_row_id"].duplicated().any(),
        "mapping_id unique": not detail["mapping_id"].duplicated().any(),
        "all input stock rows preserved": input_stock_rows == set(detail["event_stock_row_id"]),
        "coverage has one row per news": len(coverage) == len(input_uids) and set(coverage["uid"]) == input_uids,
        "summary contains every news": set(summary["uid"]) == input_uids,
        "no blank uid": not detail["uid"].eq("").any(),
        "real paths have root industry": not detail.loc[
            detail["is_real_industry_path"].eq(1), "2industry_code"
        ].eq("").any(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("映射结构校验失败: " + "; ".join(failed))

    uncovered = coverage[coverage["has_real_industry_path"].ne(1)]
    if not allow_unmatched_news and not uncovered.empty:
        examples = uncovered[["uid", "topic_name", "unmatched_stocks_json"]].head(20)
        raise RuntimeError(
            "存在整条新闻无真实产业层级，已阻止生成供网页使用的数据。\n"
            + examples.to_string(index=False)
        )


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(temporary, index=False, encoding="utf-8-sig", lineterminator="\n")
    temporary.replace(path)


def run(
    event_path: Path,
    industry_path: Path,
    output_dir: Path,
    allow_unmatched_news: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events, industries, metadata = read_sources(event_path, industry_path)
    detail = build_detail(events, industries)
    summary = build_summary(events, detail)
    coverage = build_coverage(events, detail, summary)
    validate_outputs(events, detail, summary, coverage, allow_unmatched_news)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_atomic(detail, output_dir / DETAIL_OUTPUT)
    write_csv_atomic(summary, output_dir / SUMMARY_OUTPUT)
    write_csv_atomic(coverage, output_dir / COVERAGE_OUTPUT)

    print(f"事件表编码: {metadata['event_encoding']}")
    print(f"产业表编码: {metadata['industry_encoding']}")
    print(f"新闻数: {events['uid'].nunique():,}")
    print(f"新闻-股票源记录: {len(events):,}")
    print(f"产业路径明细: {len(detail):,}")
    print(f"新闻-产业链汇总: {len(summary):,}")
    print(f"全新闻真实产业层级覆盖: {int(coverage['has_real_industry_path'].sum()):,}/{len(coverage):,}")
    print(f"输出目录: {output_dir}")
    return detail, summary, coverage


def default_paths() -> tuple[Path, Path, Path]:
    ui_root = Path(__file__).resolve().parents[1]
    workspace_root = ui_root.parent
    event_path = workspace_root / "1.迅兔事件数据获取" / EVENT_FILE_NAME
    industry_path = workspace_root / "2.产业数据图谱" / INDUSTRY_FILE_NAME
    output_dir = ui_root / "data" / "generated"
    return event_path, industry_path, output_dir


def parse_args() -> argparse.Namespace:
    default_event, default_industry, default_output = default_paths()
    parser = argparse.ArgumentParser(
        description="把蓝宝书新闻关联股票映射到 20260820 产业层级，生成网页可用的明细与汇总 CSV。"
    )
    parser.add_argument("--event-stock-csv", type=Path, default=default_event)
    parser.add_argument("--industry-node-csv", type=Path, default=default_industry)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument(
        "--allow-unmatched-news",
        action="store_true",
        help="允许整条新闻没有真实产业路径；默认严格阻止这种输出",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(
        args.event_stock_csv.resolve(),
        args.industry_node_csv.resolve(),
        args.output_dir.resolve(),
        allow_unmatched_news=args.allow_unmatched_news,
    )


if __name__ == "__main__":
    main()
