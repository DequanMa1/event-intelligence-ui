from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_TITLE_PATTERN = re.compile(
    r"日报|日刊|每日|每周|周报|周评|周刊|周度|周观点|周策略|双周报|月报|月度|季报|季度|晨报|晨会|晨讯|早报|早晨快讯|"
    r"收盘|晚报|定期报告|年度报告|半年度报告|季度报告|中报|年报|金股组合|市场早评|策略周报",
    re.IGNORECASE,
)
EXCLUDED_REPORT_TYPE_PATTERN = re.compile(r"个股研报|公司研究|晨会纪要|宏观研究", re.IGNORECASE)
BUSINESS_TERMS = (
    "需求", "订单", "价格", "成本", "供给", "库存", "产能", "开工", "出货", "交付",
    "渗透率", "良率", "客户", "商业化", "量产", "技术", "政策", "出口", "竞争格局",
)
DISCLAIMER_TERMS = ("免责声明", "分析师声明", "风险提示", "评级说明", "法律声明", "联系方式")
PERIODIC_BODY_PATTERN = re.compile(r"行业定期报告|行业周报|周度报告|周观点|本周专题", re.IGNORECASE)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u3000", " ").strip())


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def safe_filename(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", clean_text(value)).strip(" ._")
    return (cleaned or "report")[:limit]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"无法识别CSV编码: {path}")


def parse_report_title(raw_title: str, institution: str) -> str:
    title = clean_text(raw_title)
    title = re.sub(r"\.pdf(?:\.pdf)?$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[_\s-]+20\d{2}[-_]?\d{2}[-_]?\d{2}$", "", title)
    parts = [part.strip() for part in title.split("_") if part.strip()]
    if len(parts) > 1 and normalize_text(parts[0]) == normalize_text(institution):
        parts = parts[1:]
    return " ".join(parts) if parts else title


def parse_date(value: str) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    return digits[:8] if len(digits) >= 8 else ""


def load_report_catalog(cache_dirs: Iterable[Path]) -> list[dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for cache_dir in cache_dirs:
        if not cache_dir.exists():
            continue
        source = "tushare" if "tushare" in cache_dir.name.casefold() else "hczq"
        for csv_path in sorted(cache_dir.glob("*.csv")):
            for row in read_csv_rows(csv_path):
                report_id = clean_text(row.get("reportid"))
                pdf_url = clean_text(row.get("pdf_url") or row.get("url"))
                institution = clean_text(row.get("institutenamecn") or row.get("inst_csname"))
                title = parse_report_title(clean_text(row.get("title")), institution)
                publish_date = parse_date(row.get("pub_date") or row.get("trade_date") or csv_path.stem)
                report_type = clean_text(row.get("report_type") or row.get("kindname"))
                industry = clean_text(row.get("ind_name") or row.get("indu_sort_name"))
                if not report_id:
                    report_id = f"{source}_{hashlib.sha1((title + publish_date + pdf_url).encode('utf-8')).hexdigest()[:16]}"
                if not title or not publish_date or not pdf_url.startswith(("http://", "https://")):
                    continue
                key = f"{source}:{report_id}"
                candidate = {
                    "source": source,
                    "reportId": report_id,
                    "title": title,
                    "publishDate": publish_date,
                    "institution": institution,
                    "reportType": report_type,
                    "industry": industry,
                    "pdfUrl": pdf_url,
                }
                previous = catalog.get(key)
                if previous is None or len(candidate["title"]) > len(previous["title"]):
                    catalog[key] = candidate
    return list(catalog.values())


def report_existing_pdf_index(pdf_dirs: Iterable[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for pdf_dir in pdf_dirs:
        if not pdf_dir.exists():
            continue
        for path in pdf_dir.glob("*.pdf"):
            normalized_name = normalize_text(path.name)
            for token in re.findall(r"(?:TSR_[0-9a-f]+|\d{8,12})", path.name, flags=re.IGNORECASE):
                index.setdefault(normalize_text(token), path)
            index.setdefault(normalized_name, path)
    return index


def industry_aliases(industry_name: str, core_products: list[str], event_title: str) -> list[str]:
    aliases = [industry_name]
    stripped_variants = {
        re.sub(r"(?:相关)?(?:产品|设备|服务|材料|原料|制造|产业|行业|系统)$", "", industry_name),
        re.sub(r"(?:生产原料|研发服务|通信设备|生产设备|加工设备|应用软件)$", "", industry_name),
    }
    for stripped in stripped_variants:
        if len(normalize_text(stripped)) >= 2:
            aliases.append(stripped)
    for product in core_products:
        aliases.append(product)
        aliases.extend(re.findall(r"[A-Za-z][A-Za-z0-9+-]{1,12}", product))
        without_parentheses = re.sub(r"[（(][^）)]*[）)]", "", product).strip()
        if len(normalize_text(without_parentheses)) >= 2:
            aliases.append(without_parentheses)
    aliases.extend(re.findall(r"[A-Za-z][A-Za-z0-9+-]{1,12}", event_title))
    output: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = normalize_text(alias)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        output.append(clean_text(alias))
    return output


def report_relevance(report: dict[str, str], industry_name: str, aliases: list[str]) -> tuple[int, list[str]]:
    raw_title = report["title"]
    title_norm = normalize_text(report["title"])
    industry_norm = normalize_text(industry_name)
    matched: list[str] = []
    score = 0
    if industry_norm and industry_norm in title_norm:
        score += 120
        matched.append(industry_name)
    for index, alias in enumerate(aliases):
        alias_norm = normalize_text(alias)
        if len(alias_norm) < 2 or alias_norm == industry_norm:
            continue
        if re.fullmatch(r"[a-z0-9+-]+", alias_norm):
            is_match = bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", raw_title, flags=re.IGNORECASE))
        else:
            is_match = alias_norm in title_norm
        if is_match:
            weight = 45 if re.fullmatch(r"[a-z0-9+-]+", alias_norm) or len(alias_norm) >= 4 else 30
            score += weight if index < 8 else max(12, weight // 2)
            matched.append(alias)
    report_industry = normalize_text(report.get("industry", ""))
    if industry_norm and report_industry and (industry_norm in report_industry or report_industry in industry_norm):
        score += 20
    return score, list(dict.fromkeys(matched))


def select_reports_for_event(event: dict[str, Any], catalog: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
    industry_name = event["industryAnalysis"]["target"]["name"]
    # Semantic bridges are often the most precise event term (for example “功率半导体”).
    # Keep them for title matching even when they are not a direct company-product node.
    core_products = [item["name"] for item in event["chain"]["core"] if clean_text(item.get("name"))]
    aliases = industry_aliases(industry_name, core_products, event["event"]["title"])
    event_date = event["event"]["date"].replace("-", "")
    candidates: list[dict[str, Any]] = []
    for report in catalog:
        if report["publishDate"] > event_date:
            continue
        if EXCLUDED_TITLE_PATTERN.search(report["title"]):
            continue
        if EXCLUDED_REPORT_TYPE_PATTERN.search(report.get("reportType", "")):
            continue
        score, matched_terms = report_relevance(report, industry_name, aliases)
        industry_norm = normalize_text(industry_name)
        has_specific_term = any(
            normalize_text(term) == industry_norm
            or bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9+-]{1,12}", clean_text(term)))
            or len(normalize_text(term)) >= 4
            for term in matched_terms
        )
        # A broad parent word such as “医药”或“半导体” is not enough by itself.
        # Require either the full mapped industry title or a specific product/event term.
        if score < 40 or not matched_terms or not has_specific_term:
            continue
        candidates.append({**report, "relevanceScore": score, "matchedTerms": matched_terms})
    candidates.sort(key=lambda item: (item["publishDate"], item["relevanceScore"], item["reportId"]), reverse=True)
    selected: list[dict[str, Any]] = []
    selected_titles: list[str] = []
    for candidate in candidates:
        title_key = normalize_text(candidate["title"])
        if any(
            title_key == existing
            or (len(title_key) >= 12 and title_key in existing)
            or (len(existing) >= 12 and existing in title_key)
            for existing in selected_titles
        ):
            continue
        selected.append(candidate)
        selected_titles.append(title_key)
        if len(selected) >= limit:
            break
    return selected


def download_pdf(report: dict[str, Any], output_dir: Path, existing_index: dict[str, Path]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{report['publishDate']}_{safe_filename(report['reportId'], 28)}_"
        f"{safe_filename(report['institution'], 24)}_{safe_filename(report['title'])}.pdf"
    )
    target = output_dir / filename
    if target.exists() and target.stat().st_size > 10_000:
        return target
    existing = existing_index.get(normalize_text(report["reportId"]))
    if existing and existing.exists() and existing.stat().st_size > 10_000:
        shutil.copy2(existing, target)
        return target
    request = urllib.request.Request(
        report["pdfUrl"],
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    temporary = target.with_suffix(".pdf.part")
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    if temporary.stat().st_size < 10_000:
        temporary.unlink(missing_ok=True)
        raise ValueError("下载内容过小，不像有效PDF")
    temporary.replace(target)
    return target


def extract_pdf_text(pdf_path: Path, text_path: Path) -> str:
    if text_path.exists() and text_path.stat().st_size > 200:
        return text_path.read_text(encoding="utf-8")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("需要使用工作区自带Python运行本脚本，以提供pypdf") from exc
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            value = page.extract_text() or ""
        except Exception:
            value = ""
        if value.strip():
            pages.append(f"\n\n--- 第{page_number}页 ---\n{value}")
    text = "".join(pages).strip()
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    return text


def evidence_sentences(full_text: str, terms: list[str], limit: int = 5) -> list[str]:
    normalized_terms = [normalize_text(term) for term in terms if len(normalize_text(term)) >= 2]
    sentences = re.split(r"(?<=[。！？])|\n+", full_text)
    ranked: list[tuple[int, int, str]] = []
    for index, raw_sentence in enumerate(sentences):
        sentence = clean_text(raw_sentence).strip("•·-— ")
        if len(sentence) < 24 or len(sentence) > 260:
            continue
        if any(term in sentence for term in DISCLAIMER_TERMS):
            continue
        sentence_norm = normalize_text(sentence)
        matched_term_count = sum(term in sentence_norm for term in normalized_terms)
        business_count = sum(term in sentence for term in BUSINESS_TERMS)
        number_bonus = 2 if re.search(r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?(?:亿元|万吨|万台|GW|GWh|倍)", sentence) else 0
        score = matched_term_count * 7 + business_count * 2 + number_bonus
        if score >= 7:
            ranked.append((score, -index, sentence))
    ranked.sort(reverse=True)
    selected: list[str] = []
    selected_norms: list[str] = []
    for _, _, sentence in ranked:
        normalized = normalize_text(sentence)
        if any(normalized in other or other in normalized for other in selected_norms):
            continue
        selected.append(sentence)
        selected_norms.append(normalized)
        if len(selected) >= limit:
            break
    return selected


def process_report(
    report: dict[str, Any],
    event_terms: list[str],
    pdf_dir: Path,
    text_dir: Path,
    existing_index: dict[str, Path],
) -> dict[str, Any]:
    try:
        pdf_path = download_pdf(report, pdf_dir, existing_index)
        text_path = text_dir / f"{safe_filename(report['source'] + '_' + report['reportId'], 72)}.txt"
        full_text = extract_pdf_text(pdf_path, text_path)
        if PERIODIC_BODY_PATTERN.search(full_text[:5000]):
            return {
                "reportId": report["reportId"],
                "source": report["source"],
                "title": report["title"],
                "institution": report["institution"],
                "publishDate": report["publishDate"],
                "reportType": report["reportType"],
                "matchedTerms": report["matchedTerms"],
                "relevanceScore": report["relevanceScore"],
                "summaryStatus": "excluded-periodic",
                "pageCount": full_text.count("--- 第"),
                "characterCount": len(full_text),
                "evidenceSentences": [],
                "pdfPath": pdf_path.as_posix(),
                "textPath": text_path.as_posix(),
                "error": "PDF正文显示为周报或定期报告",
            }
        evidence = evidence_sentences(full_text, [*event_terms, *report.get("matchedTerms", [])])
        status = "source-extractive-draft" if evidence else "needs-ocr"
        return {
            "reportId": report["reportId"],
            "source": report["source"],
            "title": report["title"],
            "institution": report["institution"],
            "publishDate": report["publishDate"],
            "reportType": report["reportType"],
            "matchedTerms": report["matchedTerms"],
            "relevanceScore": report["relevanceScore"],
            "summaryStatus": status,
            "pageCount": full_text.count("--- 第"),
            "characterCount": len(full_text),
            "evidenceSentences": evidence,
            "pdfPath": pdf_path.as_posix(),
            "textPath": text_path.as_posix(),
            "error": "" if evidence else "PDF没有提取出可信的产业相关正文",
        }
    except Exception as exc:
        return {
            "reportId": report["reportId"],
            "source": report["source"],
            "title": report["title"],
            "institution": report["institution"],
            "publishDate": report["publishDate"],
            "reportType": report["reportType"],
            "matchedTerms": report["matchedTerms"],
            "relevanceScore": report["relevanceScore"],
            "summaryStatus": "needs-ocr",
            "pageCount": 0,
            "characterCount": 0,
            "evidenceSentences": [],
            "pdfPath": "",
            "textPath": "",
            "error": str(exc),
        }


def write_mapping_csv(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "main_id", "event_title", "event_date", "industry_name", "report_rank", "report_id", "report_title",
        "institution", "publish_date", "summary_status", "relevance_score", "matched_terms", "pdf_path", "text_path", "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in events:
            for rank, report in enumerate(event["reports"], start=1):
                writer.writerow({
                    "main_id": event["mainId"],
                    "event_title": event["eventTitle"],
                    "event_date": event["eventDate"],
                    "industry_name": event["industryName"],
                    "report_rank": rank,
                    "report_id": report["reportId"],
                    "report_title": report["title"],
                    "institution": report["institution"],
                    "publish_date": report["publishDate"],
                    "summary_status": report["summaryStatus"],
                    "relevance_score": report["relevanceScore"],
                    "matched_terms": "、".join(report["matchedTerms"]),
                    "pdf_path": report["pdfPath"],
                    "text_path": report["textPath"],
                    "error": report["error"],
                })


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    workspace_root = project_root.parent
    source_root = workspace_root / "1.迅兔事件数据获取"
    parser = argparse.ArgumentParser(description="按事件映射产业筛选并通读最新研报")
    parser.add_argument("--impact-dir", type=Path, default=project_root / "public" / "data" / "impact-chains")
    parser.add_argument("--event-ids", nargs="*", default=[])
    parser.add_argument("--reports-per-event", type=int, default=3)
    parser.add_argument("--cache-dir", type=Path, action="append", default=[
        source_root / "event_report_output" / "day_cache",
        source_root / "event_report_output_tushare" / "day_cache_tushare",
    ])
    parser.add_argument("--existing-pdf-dir", type=Path, action="append", default=[
        source_root / "event_report_output" / "pdfs",
        source_root / "event_report_output_tushare" / "pdfs",
    ])
    parser.add_argument("--output-root", type=Path, default=source_root / "industry_report_corpus")
    parser.add_argument("--corpus-json", type=Path, default=project_root / "generated" / "industry_report_corpus.json")
    parser.add_argument("--mapping-csv", type=Path, default=project_root / "generated" / "industry_report_mapping.csv")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    event_ids = set(args.event_ids)
    existing_payload: dict[str, Any] = {}
    if args.corpus_json.exists():
        existing_payload = json.loads(args.corpus_json.read_text(encoding="utf-8"))
    existing_synthesis = {
        item["mainId"]: item.get("synthesis")
        for item in existing_payload.get("events", [])
        if item.get("synthesis")
    }

    events: list[dict[str, Any]] = []
    for path in sorted(args.impact_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        main_id = payload["event"]["mainId"]
        if event_ids and main_id not in event_ids:
            continue
        analysis = payload.get("industryAnalysis", {})
        if analysis.get("status") != "ready" or not analysis.get("target"):
            continue
        events.append(payload)

    catalog = load_report_catalog(args.cache_dir)
    existing_index = report_existing_pdf_index(args.existing_pdf_dir)
    output_events: list[dict[str, Any]] = []
    for event in events:
        main_id = event["event"]["mainId"]
        candidate_limit = args.reports_per_event if args.dry_run else args.reports_per_event * 4
        selected = select_reports_for_event(event, catalog, candidate_limit)
        industry_name = event["industryAnalysis"]["target"]["name"]
        core_terms = [item["name"] for item in event["chain"]["core"][:8]]
        event_terms = industry_aliases(industry_name, core_terms, event["event"]["title"])
        if args.dry_run:
            reports = [{**item, "summaryStatus": "not_processed", "pageCount": 0, "characterCount": 0,
                        "evidenceSentences": [], "pdfPath": "", "textPath": "", "error": ""}
                       for item in selected[:args.reports_per_event]]
            rejected_reports: list[dict[str, Any]] = []
        else:
            reports = []
            rejected_reports = []
            for report in selected:
                processed = process_report(
                    report,
                    event_terms,
                    args.output_root / "pdfs",
                    args.output_root / "texts",
                    existing_index,
                )
                if processed["summaryStatus"] == "source-extractive-draft":
                    reports.append(processed)
                    if len(reports) >= args.reports_per_event:
                        break
                else:
                    rejected_reports.append(processed)
        output_events.append({
            "mainId": main_id,
            "eventTitle": event["event"]["title"],
            "eventDate": event["event"]["date"],
            "industryCode": event["industryAnalysis"]["target"]["code"],
            "industryName": industry_name,
            "selectionRule": "事件日及以前、标题产业相关、排除日报周报晨报及定期报告，并验证正文包含产业信息后，按发布日期倒序取3篇",
            "reports": reports,
            "rejectedReports": rejected_reports,
            "synthesis": existing_synthesis.get(main_id),
        })

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "catalogReportCount": len(catalog),
        "eventCount": len(output_events),
        "reportsPerEvent": args.reports_per_event,
        "events": output_events,
    }
    args.corpus_json.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.corpus_json.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.corpus_json)
    write_mapping_csv(args.mapping_csv, output_events)

    ready_reports = sum(report["summaryStatus"] == "source-extractive-draft" for event in output_events for report in event["reports"])
    missing_reports = sum(len(event["reports"]) < args.reports_per_event for event in output_events)
    print(f"研报目录: {len(catalog)}")
    print(f"事件数量: {len(output_events)}")
    print(f"已提取全文研报: {ready_reports}")
    print(f"不足{args.reports_per_event}篇的事件: {missing_reports}")
    print(f"语料文件: {args.corpus_json}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
