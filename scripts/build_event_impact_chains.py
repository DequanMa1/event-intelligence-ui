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
    "reason",
    "first_level",
    "second_level",
    "industry1",
    "industry2",
    "industry3",
]

COMPANY_PROFILE_COLUMNS = [
    "代码",
    "名称",
    "公司简介",
    "主营产品名称",
    "主营收入构成2025年报",
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

CONTEXT_WEIGHTS = {
    "first_level": 5,
    "second_level": 6,
    "industry1": 1,
    "industry2": 2,
    "industry3": 3,
}

MAX_CORE_PRODUCTS = 18
MAX_RELATED_INDUSTRIES = 2
MAX_RELATED_INDUSTRY_PRODUCTS = 4
MIN_INVESTMENT_STARS = 3
STAR_PATTERN = re.compile(r"^[★☆]{1,5}(?:\s*\(\d+/\d+分\))?$")
A_SHARE_CODE_PATTERN = re.compile(r"^\d{6}\.(?:SH|SS|SZ|BJ)$", re.IGNORECASE)
REVENUE_SEGMENT_PATTERN = re.compile(r"^\s*(.+)\s*[:：]\s*(-?\d+(?:\.\d+)?)%\s*$")
INTERNAL_SOURCE_REF_PATTERN = re.compile(r"\[[0-9a-f]{20,}(?:_[0-9]+)?\]", re.IGNORECASE)
TECH_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+-]{1,15}")
SPLIT_PATTERN = re.compile(r"[/／、,，;；|+&]|\s+-\s+")
GENERIC_CONTEXT_TERMS = {
    "上游",
    "中游",
    "下游",
    "材料",
    "产品",
    "设备",
    "模组",
    "模块",
    "核心组件",
    "核心材料",
    "核心设备",
    "厂商",
    "潜力企业",
    "国内厂商",
    "海外厂商",
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
    "A类",
    "B类",
    "C类",
    "影响性质更接近",
    "规则命中",
    "模型判断",
    "相关变化直接作用于",
    "潜在需求只有转化为持续采购",
    "如果相关变化继续兑现",
    "后续仍需观察",
    "利好可能主要停留在预期层面",
)

INVESTMENT_ANALYSIS_BANNED_PHRASES = (
    "核心矛盾",
    "年报",
    "公司简介",
    "关联理由",
    "事件关联表",
    "公司库",
    "资料显示",
    "材料显示",
    "数据显示",
    "公告显示",
    "根据资料",
    "根据材料",
    "据资料",
    "据材料",
    "现有证据",
    "证据层级",
    "缺少可匹配的公司资料",
    "未匹配到公司资料",
    "未匹配到业务资料",
    "从收入结构看",
    "年报口径",
    "输入信息",
    "处理过程",
)

INVESTMENT_GROUPS = {
    5: {"name": "核心强相关组合", "relevance": "最强相关"},
    4: {"name": "高度相关组合", "relevance": "强相关"},
    3: {"name": "中度相关组合", "relevance": "中等相关"},
}

EVENT_TRANSMISSION_PROFILES = (
    {
        "keywords": ("禁令", "制裁", "处罚", "事故", "停产", "召回", "下调", "下滑", "萎缩", "违约"),
        "driver": "经营约束及需求或供给冲击",
        "path": "事件影响订单、价格或交付能力，再传导至收入、毛利率及潜在减值压力",
        "signals": "订单变化、产品价格、交付节奏和减值迹象",
        "risk": "冲击持续时间超预期，或公司缺少转嫁成本和替代客户的能力",
    },
    {
        "keywords": ("涨价", "提价", "降价", "价格", "量价", "缺货", "供不应求", "库存", "短缺"),
        "driver": "供需缺口与产品价格",
        "path": "供需变化先影响报价和订单排期，再通过销量、产能利用率和单位盈利进入报表",
        "signals": "产品报价、订单排期、产销率和毛利率",
        "risk": "供给恢复、库存反转或终端需求转弱使价格弹性快速收敛",
    },
    {
        "keywords": ("临床", "新药", "获批", "审批", "适应症", "药证", "授权"),
        "driver": "研发里程碑与商业化成功概率",
        "path": "研发或授权进展改变项目成功率和未来现金流预期，再通过里程碑收入、销售分成或费用投入影响利润",
        "signals": "临床数据、监管节点、首付款及里程碑确认和销售放量",
        "risk": "研发、审批或商业化进度不及预期，且前期投入难以形成对应回报",
    },
    {
        "keywords": ("政策", "补贴", "规划", "标准", "监管", "改革", "目录", "办法"),
        "driver": "政策约束与需求释放节奏",
        "path": "政策先改变客户采购意愿或行业准入，再通过项目落地、订单转化和成本变化影响经营结果",
        "signals": "政策细则、招投标规模、项目开工率和回款进度",
        "risk": "政策执行弱于预期、补贴退坡或项目回款周期拉长",
    },
    {
        "keywords": ("量产", "订单", "中标", "采购", "交付", "签约", "合作", "定点", "商业化", "采用率"),
        "driver": "商业化进度和订单兑现",
        "path": "客户验证转化为订单，再通过交付量、产品结构和产能利用率影响收入及毛利率",
        "signals": "客户认证、新增订单、交付节奏、相关业务收入和毛利率",
        "risk": "客户验证或交付节奏低于预期，订单停留在小批量阶段",
    },
    {
        "keywords": ("扩产", "投产", "产能", "产线", "开工", "达产"),
        "driver": "产能释放与行业供给变化",
        "path": "新增产能改变可交付规模和行业供需，再通过产销率、价格和折旧负担影响利润",
        "signals": "在建工程转固、产能利用率、产销率、库存和产品价格",
        "risk": "需求承接不足导致新增产能闲置，折旧上升反而压低盈利能力",
    },
    {
        "keywords": ("需求", "渗透率", "销量", "出口", "消费", "景气", "增长"),
        "driver": "终端需求与渗透率变化",
        "path": "终端需求传导至客户采购和公司出货，再通过销量、产品结构和规模效应影响利润",
        "signals": "终端销量、客户采购量、公司出货和相关产品收入增速",
        "risk": "终端需求低于预期，或竞争加剧使收入增长无法转化为利润增长",
    },
    {
        "keywords": ("技术", "突破", "发布", "验证", "升级", "迭代", "替代", "国产化"),
        "driver": "技术商业化与产品迭代速度",
        "path": "技术验证先影响客户导入和产品结构，再通过订单放量、良率和单位价值量改变盈利",
        "signals": "客户认证、量产良率、订单规模、产品收入占比和毛利率",
        "risk": "技术路线变化、良率爬坡缓慢或竞争方案更快成熟",
    },
)

DEFAULT_TRANSMISSION_PROFILE = {
    "driver": "事件能否转化为可确认的经营增量",
    "path": "产业链位置先转化为客户需求和订单，再通过交付、收入确认及盈利质量进入报表",
    "signals": "订单、收入确认、产品结构和毛利率变化",
    "risk": "事件关联停留在主题层面，未形成可持续订单或利润贡献",
}

PROFILE_BUSINESS_MARKERS = (
    "主营",
    "业务",
    "产品",
    "服务",
    "聚焦",
    "从事",
    "提供",
    "覆盖",
    "布局",
    "形成",
    "包括",
)

REVENUE_NAME_SUFFIXES = (
    "主营业务收入",
    "主营业务",
    "其他业务",
    "类产品",
    "类业务",
    "业务收入",
    "产品收入",
    "产品",
    "业务",
)

GENERIC_REVENUE_NAMES = {
    "其他",
    "其他产品",
    "其他业务",
    "其他主营业务",
    "主营业务",
}

# Business ontology used to compare an event's actual product chain with a
# company's products and accounting revenue labels.  The labels deliberately
# mix product names, common industry aliases and parent categories so that a
# broad revenue bucket is not treated as unrelated merely because its wording
# differs from the event terminology.
BUSINESS_SEMANTIC_GROUPS = {
    "optical_communication": (
        "光通信", "光模块", "光器件", "光子器件", "光互联", "光收发", "光传输",
        "光纤", "光缆", "硅光", "光芯片", "激光器", "外置光源", "cpo", "npo",
        "lpo", "dpo", "xpo", "fau", "els",
    ),
    "network_compute": (
        "服务器", "超算", "交换机", "路由器", "网络设备", "数据中心", "算力",
        "云计算", "云端", "边缘计算", "机房", "网关", "idc", "ict", "hpc",
    ),
    "semiconductor_equipment": (
        "半导体设备", "封装设备", "封测设备", "测试设备", "检测设备", "耦合设备", "清洗设备", "电镀设备",
        "刻蚀设备", "薄膜设备", "光刻设备", "量测设备", "分选机", "测试机", "固晶机",
        "键合设备", "cmp设备", "晶圆设备",
    ),
    "semiconductor_chip": (
        "半导体", "集成电路", "芯片", "晶圆", "封装测试", "芯片封测", "处理器",
        "存储芯片", "微控制器", "mcu", "功率器件", "功率半导体", "mosfet", "igbt",
        "二极管", "传感器", "模拟产品",
    ),
    "pcb_components": (
        "印制电路板", "电路板", "pcb", "fpc", "覆铜板", "封装基板", "连接器",
        "电子元件", "电子元器件", "被动元件", "电容", "电感", "继电器", "天线",
    ),
    "electronic_materials": (
        "电子布", "玻璃纤维布", "玻纤布", "低介电布", "lowdk", "low-dk", "覆铜板",
        "电子铜箔", "载体铜箔", "电子材料",
    ),
    "display_optics": (
        "显示面板", "显示器件", "显示材料", "触控", "液晶", "oled", "mled", "led",
        "背光", "光学膜", "玻璃基板", "光电显示", "面板",
    ),
    "consumer_electronics": (
        "消费电子", "3c电子", "智能手机", "手机", "电脑", "可穿戴", "智能终端",
        "vr", "ar", "游戏机", "耳机", "摄像头",
    ),
    "automation_robotics": (
        "自动化", "机器人", "机器视觉", "工业控制", "工控", "伺服", "减速器", "mes",
        "智能制造", "智能装备",
    ),
    "software_ai": (
        "软件", "人工智能", "ai", "大模型", "算法", "数据库", "操作系统", "云服务",
        "信息化", "系统集成", "数字化", "ip授权",
    ),
    "cybersecurity": ("网络安全", "信息安全", "数据安全", "密码", "安全产品"),
    "automotive": (
        "汽车", "整车", "车载", "新能源车", "智能驾驶", "座舱", "汽车零部件",
        "发动机", "底盘", "轮胎",
    ),
    "battery_storage": (
        "动力电池", "储能", "锂电", "电池", "正极", "负极", "电解液", "隔膜",
        "铜箔", "固态电池", "钠电",
    ),
    "solar": ("光伏", "太阳能", "硅片", "电池片", "光伏组件", "逆变器", "光伏电站"),
    "wind_power": ("风电", "风机", "叶片", "海上风电", "塔筒"),
    "power_grid": (
        "电网", "电力设备", "输变电", "变压器", "配电", "智能电网", "电缆", "电表",
        "充电桩", "电力电子",
    ),
    "hydrogen_energy": ("氢能", "燃料电池", "电解槽", "制氢", "储氢"),
    "oil_gas_energy": (
        "石油", "天然气", "油气", "煤炭", "lng", "炼化", "成品油", "电力", "发电",
        "核电", "水电", "火电",
    ),
    "chemicals": (
        "化工", "化学品", "化学材料", "树脂", "涂料", "胶", "添加剂", "催化剂",
        "氟化工", "气体", "农药", "化肥",
    ),
    "advanced_materials": (
        "新材料", "复合材料", "陶瓷材料", "碳纤维", "玻璃纤维", "膜材料", "导热材料",
        "靶材", "石英", "硅微粉", "磁材", "高分子材料",
    ),
    "metals_mining": (
        "有色金属", "钢铁", "铜产品", "铝", "稀土", "黄金", "锂矿", "矿山", "采矿",
        "冶炼", "金属材料",
    ),
    "critical_minerals": (
        "战略矿产", "关键矿产", "关键金属", "稀土", "金属铋", "精铋", "锗", "镓",
        "锑", "钨", "钼",
    ),
    "industrial_machinery": (
        "机械设备", "专用设备", "通用设备", "工程机械", "机床", "泵", "阀", "压缩机",
        "仪器仪表", "工业设备", "高端制造",
    ),
    "aerospace_defense": (
        "航空", "航天", "军工", "卫星", "火箭", "无人机", "导弹", "雷达", "低空经济",
    ),
    "pharma_biotech": (
        "医药", "药品", "创新药", "生物制药", "疫苗", "原料药", "制剂", "临床",
        "cro", "cdmo", "医疗服务",
    ),
    "medical_devices": ("医疗器械", "医学影像", "诊断", "检测试剂", "耗材", "手术机器人"),
    "agriculture": ("农业", "种业", "种子", "养殖", "生猪", "饲料", "农产品", "林业"),
    "food_beverage": ("食品", "饮料", "白酒", "啤酒", "乳制品", "调味品", "餐饮"),
    "construction_real_estate": (
        "房地产", "房屋销售", "建筑", "建材", "水泥", "玻璃", "装修", "物业", "租赁",
    ),
    "transport_logistics": (
        "物流", "快递", "铁路", "公路", "航空运输", "机场", "交通运输", "供应链服务",
    ),
    "shipping": ("航运", "船舶", "港口", "集装箱", "海运"),
    "finance": (
        "证券", "银行", "保险", "投资银行", "资产管理", "经纪业务", "金融服务", "信托",
    ),
    "environmental": ("环保", "水处理", "固废", "危废", "节能", "再生资源", "碳减排"),
    "home_appliances": ("家电", "空调", "冰箱", "洗衣机", "厨电", "小家电"),
    "textile_apparel": ("纺织", "服装", "纤维", "面料", "鞋", "家纺"),
    "media_tourism": ("传媒", "游戏", "影视", "广告", "旅游", "酒店", "景区", "教育"),
    "telecom_service": ("电信运营", "通信服务", "运营商", "移动通信服务", "宽带服务"),
}

SPECIFIC_BUSINESS_TAGS = frozenset(BUSINESS_SEMANTIC_GROUPS)

SEMANTIC_SEGMENT_MATCH_TAGS = SPECIFIC_BUSINESS_TAGS - {
    "chemicals",
    "advanced_materials",
    "industrial_machinery",
}

BROAD_REVENUE_CONTAINMENT = (
    ("3c电子产品", {"network_compute", "consumer_electronics", "pcb_components", "optical_communication"}),
    ("电子产品", {"network_compute", "consumer_electronics", "pcb_components", "semiconductor_chip", "optical_communication"}),
    ("电子工艺装备", {"semiconductor_equipment", "automation_robotics", "display_optics", "industrial_machinery"}),
    ("电子化学品", {"battery_storage", "semiconductor_chip", "semiconductor_equipment", "display_optics", "chemicals"}),
    ("电子材料", {"electronic_materials", "semiconductor_chip", "display_optics", "pcb_components"}),
    ("玻璃纤维布", {"electronic_materials", "advanced_materials"}),
    ("玻璃纤维纱", {"electronic_materials", "advanced_materials"}),
    ("石英玻璃", {"semiconductor_chip", "semiconductor_equipment", "display_optics", "advanced_materials"}),
    ("资源化", {"critical_minerals", "metals_mining", "environmental", "battery_storage", "chemicals"}),
    ("半导体业务", {"semiconductor_chip", "semiconductor_equipment"}),
    ("半导体", {"semiconductor_chip", "semiconductor_equipment"}),
    ("网络设备", {"network_compute", "optical_communication"}),
    ("通信设备", {"network_compute", "optical_communication", "pcb_components"}),
    ("ict基础设施", {"network_compute", "optical_communication", "software_ai"}),
    ("新能源", {"battery_storage", "solar", "wind_power", "power_grid", "hydrogen_energy"}),
    ("新能源材料", {"battery_storage", "solar", "advanced_materials", "chemicals"}),
    ("化工材料", {"chemicals", "advanced_materials"}),
    ("电子元件", {"pcb_components", "semiconductor_chip", "optical_communication"}),
    ("电子元器件", {"pcb_components", "semiconductor_chip", "optical_communication"}),
    ("工业设备", {"industrial_machinery", "automation_robotics", "semiconductor_equipment"}),
    ("专用设备", {"industrial_machinery", "automation_robotics", "semiconductor_equipment"}),
    ("高端制造", {"industrial_machinery", "automation_robotics", "semiconductor_equipment"}),
)

BROAD_REVENUE_EXACT_NAMES = {
    "半导体",
    "半导体业务",
    "芯片",
    "电子",
    "电子产品",
    "3C电子产品",
    "电子工艺装备",
    "设备",
    "专用设备",
    "工业设备板及其他",
    "高端制造",
    "新能源",
    "新能源产品",
    "新能源材料",
    "化工材料",
    "网络设备",
    "通信设备",
    "ICT基础设施及服务",
    "技术服务",
    "产品销售",
    "零部件",
    "配件",
    "组件",
    "解决方案",
}


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"[\t\r\n]+", " ", str(value).replace("\u3000", " ").strip())


def clean_reason(value: Any) -> str:
    return re.sub(INTERNAL_SOURCE_REF_PATTERN, "", clean_text(value)).strip()


def compact_text(value: Any, limit: int) -> str:
    text = clean_text(value).rstrip("。！？!?；;，, ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("。！？!?；;，, ") + "…"


def professionalize_reason(value: Any) -> str:
    text = clean_reason(value)
    replacements = (
        ("根据公司年报", ""),
        ("据公司年报", ""),
        ("公司年报显示", ""),
        ("年报显示", ""),
        ("财报显示", ""),
        ("公司简介显示", ""),
        ("公开资料显示", ""),
        ("资料显示", ""),
        ("数据显示", ""),
        ("公告显示", ""),
        ("关联理由显示", ""),
        ("关联理由为", ""),
        ("有望直接受益于", "直接受益环节在于"),
        ("有望受益于", "受益环节在于"),
        ("有望受益", "具备潜在受益条件"),
        ("值得重点关注", "关键变量是"),
        ("值得关注", "关键变量是"),
        ("未来可期", "商业化仍待验证"),
        ("后续重点看", "关键验证信号是"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    text = re.sub(
        r"(?:根据|据)?(?:公司)?(?:20\d{2}年)?(?:年度)?年报(?:中|口径)?(?:显示|指出|披露|提到|表明|称)?[：:，, ]*",
        "",
        text,
    )
    text = re.sub(
        r"(?:根据|据)?(?:公司)?(?:财报|公司简介|公开资料|相关资料)(?:中|口径)?(?:显示|指出|披露|提到|表明|称)?[：:，, ]*",
        "",
        text,
    )
    return text.strip(" ：:，,；;。")


def normalize_security_code(value: Any) -> str:
    code = clean_text(value).upper().replace(" ", "")
    return code[:-3] + ".SH" if code.endswith(".SS") else code


def is_a_share_code(value: Any) -> bool:
    return bool(A_SHARE_CODE_PATTERN.fullmatch(clean_text(value).upper().replace(" ", "")))


def is_ordered_subsequence(needle: str, haystack: str) -> bool:
    iterator = iter(haystack)
    return all(character in iterator for character in needle)


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


def parse_revenue_segments(value: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for part in re.split(r"[;；]", clean_text(value)):
        if not part.strip():
            continue
        match = REVENUE_SEGMENT_PATTERN.fullmatch(part)
        if not match:
            continue
        segments.append(
            {
                "name": clean_text(match.group(1)),
                "sharePct": float(match.group(2)),
            }
        )
    return sorted(segments, key=lambda item: (-item["sharePct"], item["name"]))


def read_company_profiles(path: Path) -> dict[str, Any]:
    header = pd.read_excel(path, nrows=0).columns.tolist()
    missing = [column for column in COMPANY_PROFILE_COLUMNS if column not in header]
    if missing:
        raise ValueError(f"{path.name} 缺少字段: {missing}")

    frame = pd.read_excel(
        path,
        usecols=COMPANY_PROFILE_COLUMNS,
        dtype=str,
        keep_default_na=False,
    )
    for column in frame.columns:
        frame[column] = frame[column].map(clean_text)

    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_row_number, row in enumerate(frame.to_dict("records"), start=2):
        company_code = normalize_security_code(row["代码"])
        company_name = clean_text(row["名称"])
        if not company_code or not company_name:
            continue
        if company_code in by_code:
            raise ValueError(f"{path.name} 存在重复证券代码: {company_code}")
        record = {
            "sourceRowNumber": source_row_number,
            "companyCode": company_code,
            "companyName": company_name,
            "companyProfile": clean_text(row["公司简介"]),
            "majorProducts": clean_text(row["主营产品名称"]),
            "revenueComposition": clean_text(row["主营收入构成2025年报"]),
            "revenueSegments": parse_revenue_segments(row["主营收入构成2025年报"]),
            "sourceWorkbook": path.name,
        }
        by_code[company_code] = record
        by_name[normalize_text(company_name)].append(record)

    return {
        "byCode": by_code,
        "byName": by_name,
        "sourceWorkbook": path.name,
        "companyCount": len(by_code),
    }


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
        "stockCode": normalize_security_code(row["stock_code"]),
        "stockName": row["stock_name"],
        "rating": row["origin_star_num"],
        "filledStars": int(row["filled_star_count"]),
        "mapped": mapped,
        "anchorProductCount": product_count,
    }


def stock_context_terms(row: pd.Series) -> set[str]:
    terms: set[str] = set()
    for field in ("first_level", "second_level", "industry1", "industry2", "industry3"):
        for value in split_context_value(row[field]):
            normalized = normalize_text(value)
            if len(normalized) >= 2:
                terms.add(normalized)
    for value in (row["topic_name"], row["reason"]):
        for token in TECH_TOKEN_PATTERN.findall(clean_text(value)):
            normalized = normalize_text(token)
            if len(normalized) >= 2:
                terms.add(normalized)
    return terms


def summarize_company_profile(profile: str, context_terms: set[str], limit: int = 220) -> str:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])", clean_text(profile))
        if sentence.strip()
    ]
    if not sentences:
        return ""

    ranked: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        normalized = normalize_text(sentence)
        score = sum(2 for marker in PROFILE_BUSINESS_MARKERS if marker in sentence)
        score += sum(min(len(term), 6) for term in context_terms if term in normalized)
        if sentence.startswith(("目前", "现阶段", "公司主营", "公司业务", "公司聚焦")):
            score += 3
        if "成立于" in sentence and not any(marker in sentence for marker in PROFILE_BUSINESS_MARKERS):
            score -= 2
        ranked.append((score, index, sentence))

    selected = sorted(ranked, key=lambda item: (-item[0], item[1]))[:2]
    selected.sort(key=lambda item: item[1])
    summary = "".join(item[2] for item in selected if item[0] > 0) or sentences[0]
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip("，,；;。 ") + "…"
    return summary


def match_company_profile(
    stock_code: str,
    stock_name: str,
    company_profiles: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    normalized_code = normalize_security_code(stock_code)
    matched = company_profiles["byCode"].get(normalized_code)
    if matched:
        return matched, "stock_code"

    name_matches = company_profiles["byName"].get(normalize_text(stock_name), [])
    if len(name_matches) == 1:
        return name_matches[0], "stock_name"
    return None, "none"


def semantic_business_tags(value: Any) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()
    return {
        tag
        for tag, keywords in BUSINESS_SEMANTIC_GROUPS.items()
        if any(normalize_text(keyword) in normalized for keyword in keywords)
    }


def event_business_terms(row: pd.Series) -> set[str]:
    terms: set[str] = set()
    for field in ("first_level", "second_level"):
        for value in split_context_value(row[field]):
            normalized = normalize_text(value)
            if len(normalized) >= 2 and clean_text(value) not in GENERIC_CONTEXT_TERMS:
                terms.add(normalized)
    for token in TECH_TOKEN_PATTERN.findall(
        f"{clean_text(row['topic_name'])} {clean_reason(row['reason'])}"
    ):
        normalized = normalize_text(token)
        if len(normalized) >= 2:
            terms.add(normalized)
    return terms


def path_text(path: dict[str, str]) -> str:
    return " ".join(
        clean_text(path.get(field))
        for field in (
            "matched_node_name",
            "5industry_name",
            "6industry_name",
            "7industry_name",
            "hierarchy_path",
        )
    )


def select_event_relevant_products(
    row: pd.Series,
    stock_paths: list[dict[str, str]],
    *,
    level7_only: bool = False,
    limit: int | None = 6,
) -> list[dict[str, Any]]:
    context_text = clean_text(
        f"{row['topic_name']} {row['first_level']} {row['second_level']} {clean_reason(row['reason'])}"
    )
    normalized_context = normalize_text(context_text)
    target_tags = semantic_business_tags(context_text)
    target_terms = event_business_terms(row)
    technical_tokens = TECH_TOKEN_PATTERN.findall(
        f"{clean_text(row['topic_name'])} {clean_reason(row['reason'])}"
    )
    anchor_text = clean_text(
        f"{row['topic_name']} {row['second_level']} {' '.join(technical_tokens)}"
    )
    anchor_tags = semantic_business_tags(anchor_text)
    ranked: list[dict[str, Any]] = []

    for path in stock_paths:
        if level7_only and (
            clean_text(path.get("matched_source_level")) != "7"
            or not clean_text(path.get("7industry_code"))
            or not clean_text(path.get("7industry_name"))
            or not clean_text(path.get("5industry_code"))
            or not clean_text(path.get("5industry_name"))
        ):
            continue
        product_text = path_text(path)
        normalized_product = normalize_text(product_text)
        product_tags = semantic_business_tags(product_text)
        exact_matches = {
            term
            for term in target_terms
            if term in normalized_product
            or (
                3 <= len(term) <= 8
                and is_ordered_subsequence(term, normalized_product)
            )
        }
        named_matches = {
            normalize_text(path.get(field))
            for field in ("matched_node_name", "6industry_name", "7industry_name")
            if len(normalize_text(path.get(field))) >= 3
            and normalize_text(path.get(field)) in normalized_context
        }
        semantic_matches = target_tags & product_tags & SPECIFIC_BUSINESS_TAGS
        anchor_semantic_matches = anchor_tags & product_tags & SPECIFIC_BUSINESS_TAGS
        if anchor_tags and not (anchor_semantic_matches or exact_matches or named_matches):
            continue
        score = len(exact_matches) * 8 + len(named_matches) * 10 + len(semantic_matches) * 4
        score += len(anchor_semantic_matches) * 8
        if score <= 0:
            continue
        ranked.append(
            {
                "code": clean_text(path.get("matched_node_code"))
                or clean_text(path.get("7industry_code")),
                "name": clean_text(path.get("matched_node_name"))
                or clean_text(path.get("7industry_name")),
                "category": clean_text(path.get("6industry_name"))
                or clean_text(path.get("5industry_name")),
                "hierarchyPath": clean_text(path.get("hierarchy_path")),
                "matchedSourceLevel": int(clean_text(path.get("matched_source_level")) or 0),
                "level5IndustryCode": clean_text(path.get("5industry_code")),
                "level5IndustryName": clean_text(path.get("5industry_name")),
                "level7ProductCode": clean_text(path.get("7industry_code")),
                "level7ProductName": clean_text(path.get("7industry_name")),
                "tags": sorted(product_tags),
                "score": score,
                "matchedTerms": sorted(exact_matches | named_matches),
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in ranked:
        key = product["level7ProductCode"] or product["code"] or normalize_text(product["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(product)
    return unique if limit is None else unique[:limit]


def is_broad_revenue_segment(name: str) -> bool:
    cleaned = clean_text(name)
    normalized = normalize_text(cleaned)
    return (
        cleaned in GENERIC_REVENUE_NAMES
        or cleaned in BROAD_REVENUE_EXACT_NAMES
        or "及其他" in cleaned
        or "等产品" in cleaned
        or any(normalize_text(phrase) in normalized for phrase, _ in BROAD_REVENUE_CONTAINMENT)
    )


def classify_revenue_segment_relation(
    segment_name: str,
    row: pd.Series,
    relevant_products: list[dict[str, Any]],
) -> str:
    cleaned_name = clean_text(segment_name)
    if cleaned_name in GENERIC_REVENUE_NAMES:
        return "unrelated"

    segment_name_normalized = normalize_text(cleaned_name)
    segment_core = segment_name_normalized
    for suffix in REVENUE_NAME_SUFFIXES:
        normalized_suffix = normalize_text(suffix)
        if segment_core.endswith(normalized_suffix) and len(segment_core) - len(normalized_suffix) >= 3:
            segment_core = segment_core[: -len(normalized_suffix)]
            break

    direct_context = normalize_text(f"{row['topic_name']} {clean_reason(row['reason'])}")
    structure_terms = {
        normalize_text(term)
        for term in split_context_value(row["second_level"])
        if len(normalize_text(term)) >= 3
    }
    direct_match = (
        (len(segment_name_normalized) >= 3 and segment_name_normalized in direct_context)
        or (len(segment_core) >= 3 and segment_core in direct_context)
        or any(
            term in segment_name_normalized
            or (len(term) <= 8 and is_ordered_subsequence(term, segment_name_normalized))
            for term in structure_terms
        )
    )

    relevant_tags = {
        tag
        for product in relevant_products
        for tag in product.get("tags", [])
    }
    path_direct_match = False
    for product in relevant_products:
        candidates = (
            product.get("name", ""),
            product.get("category", ""),
        )
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            if len(normalized_candidate) < 3:
                continue
            if (
                normalized_candidate in segment_name_normalized
                or segment_core in normalized_candidate
                or (
                    len(segment_core) <= 8
                    and is_ordered_subsequence(segment_core, normalized_candidate)
                )
            ):
                path_direct_match = True
                break
        if path_direct_match:
            break

    broad = is_broad_revenue_segment(cleaned_name)
    if (direct_match or path_direct_match) and relevant_products:
        return "contained" if broad else "direct"

    segment_tags = semantic_business_tags(cleaned_name)
    if relevant_products and segment_tags & relevant_tags & SEMANTIC_SEGMENT_MATCH_TAGS:
        return "contained"

    for phrase, allowed_tags in BROAD_REVENUE_CONTAINMENT:
        if normalize_text(phrase) in segment_name_normalized and relevant_tags & allowed_tags:
            return "contained"
    return "unrelated"


def build_company_evidence(
    row: pd.Series,
    company_profiles: dict[str, Any],
    stock_paths: list[dict[str, str]],
) -> dict[str, Any]:
    stock_code = row["stock_code"]
    stock_name = row["stock_name"] or stock_code
    company, match_method = match_company_profile(stock_code, stock_name, company_profiles)
    if not company:
        return {
            "matched": False,
            "matchMethod": "none",
            "sourceWorkbook": company_profiles["sourceWorkbook"],
            "companyCode": "",
            "companyName": "",
            "companyProfile": "",
            "profileSummary": "",
            "majorProducts": "",
            "revenueComposition": "",
            "revenueSegments": [],
            "businessRelation": {
                "status": "unavailable",
                "relevantProducts": [],
                "knownProducts": [],
                "directSegmentCount": 0,
                "containedSegmentCount": 0,
            },
        }

    context_terms = stock_context_terms(row)
    relevant_products = select_event_relevant_products(row, stock_paths)
    known_products: list[str] = []
    known_product_keys: set[str] = set()
    for path in stock_paths:
        product_name = clean_text(path.get("matched_node_name")) or clean_text(path.get("7industry_name"))
        product_key = normalize_text(product_name)
        if not product_key or product_key in known_product_keys:
            continue
        known_product_keys.add(product_key)
        known_products.append(product_name)
    revenue_segments: list[dict[str, Any]] = []
    for segment in company["revenueSegments"]:
        relation_type = classify_revenue_segment_relation(
            segment["name"],
            row,
            relevant_products,
        )
        revenue_segments.append(
            {
                **segment,
                "relatedToEvent": relation_type == "direct",
                "relationType": relation_type,
            }
        )

    direct_segment_count = sum(
        segment["relationType"] == "direct" for segment in revenue_segments
    )
    contained_segment_count = sum(
        segment["relationType"] == "contained" for segment in revenue_segments
    )
    target_text = clean_text(
        f"{row['topic_name']} {row['first_level']} {row['second_level']} {clean_reason(row['reason'])}"
    )
    target_tags = semantic_business_tags(target_text)
    company_business_text = " ".join(
        (
            company["companyProfile"],
            company["majorProducts"],
            *(path_text(path) for path in stock_paths),
        )
    )
    company_tags = semantic_business_tags(company_business_text)
    if direct_segment_count:
        relation_status = "direct_segment"
    elif contained_segment_count:
        relation_status = "broad_segment"
    elif relevant_products:
        relation_status = "product_confirmed"
    elif target_tags & company_tags:
        relation_status = "profile_supported"
    elif target_tags and company_tags:
        relation_status = "business_mismatch"
    else:
        relation_status = "unverified"

    return {
        "matched": True,
        "matchMethod": match_method,
        "sourceWorkbook": company["sourceWorkbook"],
        "companyCode": company["companyCode"],
        "companyName": company["companyName"],
        "companyProfile": company["companyProfile"],
        "profileSummary": summarize_company_profile(company["companyProfile"], context_terms),
        "majorProducts": company["majorProducts"],
        "revenueComposition": company["revenueComposition"],
        "revenueSegments": revenue_segments,
        "businessRelation": {
            "status": relation_status,
            "relevantProducts": [
                {"name": product["name"], "category": product["category"]}
                for product in relevant_products
            ],
            "knownProducts": known_products[:8],
            "directSegmentCount": direct_segment_count,
            "containedSegmentCount": contained_segment_count,
        },
    }


def format_share_pct(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"


def infer_event_transmission(event_title: str, reason: str) -> dict[str, Any]:
    context = normalize_text(f"{event_title} {reason}")
    for profile in EVENT_TRANSMISSION_PROFILES:
        if any(normalize_text(keyword) in context for keyword in profile["keywords"]):
            return profile
    return DEFAULT_TRANSMISSION_PROFILE


def narrative_variant(stock_name: str) -> int:
    return sum(ord(character) for character in stock_name) % 3


def format_segment_evidence(segments: list[dict[str, Any]], limit: int = 2) -> str:
    return "、".join(
        f"{segment['name']}（{format_share_pct(segment['sharePct'])}）"
        for segment in segments[:limit]
    )


def finalize_investment_analysis(text: str, stock_name: str) -> str:
    analysis = clean_text(text)
    forbidden = [
        phrase
        for phrase in INVESTMENT_ANALYSIS_BANNED_PHRASES
        if phrase in analysis
    ]
    if forbidden:
        raise ValueError(f"{stock_name}的研究判断包含后台来源或处理表述: {forbidden}")
    return analysis


def build_investment_analysis(
    event_title: str,
    stock_name: str,
    reason: str,
    company_evidence: dict[str, Any],
    filled_stars: int,
) -> str:
    reason_text = compact_text(professionalize_reason(reason), 92)
    transmission = infer_event_transmission(event_title, reason_text)
    variant = narrative_variant(stock_name)
    reason_clause = reason_text or "公司在产业链中的具体参与环节尚未充分明确"

    def finalize(text: str) -> str:
        return finalize_investment_analysis(text, stock_name)

    if not company_evidence["matched"]:
        unmatched_variants = (
            (
                f"{stock_name}与事件的具体业务联系在于：{reason_clause}。本次变化首先影响{transmission['driver']}，"
                f"只有经由{transmission['path']}，才会转化为可确认的经营增量。相关业务目前究竟属于存量主业、"
                "小基数增量还是产业链布局尚不清晰，因此业绩弹性暂时不能量化。"
                f"判断强弱应聚焦{transmission['signals']}；若{transmission['risk']}，"
                "相关性仍可能存在，但对公司盈利的解释力会明显下降。"
            ),
            (
                f"{stock_name}具备事件相关的业务抓手：{reason_clause}，但相关业务的收入权重和利润贡献尚不清楚。"
                f"即使{transmission['driver']}改善，也要经过{transmission['path']}，才可能形成公司层面的业绩变化。"
                f"因此，当前更适合把{transmission['signals']}作为经营兑现的关键刻度；这些信号持续改善，"
                "相关业务才可能从产业链布局上升为利润增量。"
                f"反之，{transmission['risk']}会使市场预期先于基本面回落。"
            ),
            (
                f"本次事件首先改变{stock_name}的{transmission['driver']}预期，业务抓手是：{reason_clause}。"
                f"预期进入经营结果仍需完成{transmission['path']}这一整段传导，而相关业务的真实基数和战略重要性尚不明确。"
                "这意味着公司可能同时具备产业趋势弹性和较大的兑现不确定性。"
                f"{transmission['signals']}若连续强化，逻辑可信度会随之提升；若{transmission['risk']}，"
                "当前相关性更可能停留在估值预期，而难以转化为利润贡献。"
            ),
        )
        return finalize(unmatched_variants[variant])

    positive_segments = [
        segment
        for segment in company_evidence["revenueSegments"]
        if segment["sharePct"] > 0
    ]
    top_segments = positive_segments[:3]
    related_segments = [
        segment
        for segment in positive_segments
        if segment.get("relationType") == "direct"
    ]
    contained_segments = [
        segment
        for segment in positive_segments
        if segment.get("relationType") == "contained"
    ]
    business_relation = company_evidence.get("businessRelation", {})
    relation_status = business_relation.get("status", "unverified")
    relevant_product_names = [
        product["name"]
        for product in business_relation.get("relevantProducts", [])
        if clean_text(product.get("name"))
    ]
    known_product_names = [
        clean_text(name)
        for name in business_relation.get("knownProducts", [])
        if clean_text(name)
    ]
    product_text = "、".join(relevant_product_names[:3]) or "相关产品"
    profile_focus = compact_text(company_evidence["profileSummary"], 88)
    major_products = compact_text(company_evidence.get("majorProducts", ""), 88)
    business_base = "、".join(known_product_names[:4]) or major_products or profile_focus or "现有业务"

    if related_segments:
        related_text = format_segment_evidence(related_segments)
        related_share = sum(segment["sharePct"] for segment in related_segments)
        if len(related_segments) == 1:
            only_segment = related_segments[0]
            related_evidence = (
                f"{only_segment['name']}占收入的"
                f"{format_share_pct(only_segment['sharePct'])}"
            )
        elif related_share <= 100.5:
            related_evidence = f"{related_text}合计约占收入的{format_share_pct(related_share)}"
        else:
            related_evidence = f"{related_text}已经形成可识别收入"

        if related_share >= 50:
            high_exposure_variants = (
                (
                    f"{stock_name}与事件的关系已经落在存量主业，而非远期概念：{related_evidence}。"
                    f"公司在产业链中的具体抓手是：{reason_clause}。本次事件若改变{transmission['driver']}，"
                    f"影响会沿着“{transmission['path']}”进入经营结果。对这类高基数业务，市场分歧不在公司是否参与，"
                    f"而在新增需求能否超过既有规模并转化为份额或盈利改善；{transmission['signals']}比主题热度更有解释力。"
                    f"若{transmission['risk']}，业务相关性仍然成立，但业绩上修空间可能低于市场定价。"
                ),
                (
                    f"{stock_name}的相关业务已决定公司大部分经营表现：{related_evidence}。"
                    f"公司与事件的直接业务联系是：{reason_clause}，真正的增量取决于{transmission['driver']}，"
                    f"并需经过“{transmission['path']}”才能体现。由于存量基数已经较高，单纯行业放量未必自动带来更高利润弹性，"
                    f"{transmission['signals']}需要显示公司获得超越行业的增量。"
                    f"{transmission['risk']}是这条逻辑最主要的反向约束。"
                ),
                (
                    f"{stock_name}的事件暴露较为直接：{related_evidence}，相关业务不是边缘尝试；"
                    f"具体业务抓手是：{reason_clause}。事件对公司的意义更接近存量主业景气变化，而不是新增题材。"
                    f"利润端能否同步改善，仍取决于{transmission['driver']}是否通过“{transmission['path']}”放大，"
                    f"尤其需要用{transmission['signals']}区分行业普涨与公司自身竞争力。"
                    f"如果{transmission['risk']}，高收入相关度也可能只带来收入波动，而非利润质量提升。"
                ),
            )
            return finalize(high_exposure_variants[variant])
        elif related_share >= 10:
            medium_exposure_variants = (
                (
                    f"{stock_name}的事件逻辑具备真实业务底座，但尚不足以代表全部公司：{related_evidence}。"
                    f"公司与事件的具体联系在于：{reason_clause}，对应的核心变量是{transmission['driver']}。"
                    f"若这一变量沿着“{transmission['path']}”兑现，相关业务可以贡献实质增量，"
                    "但整体利润弹性仍会被其他主业的景气和产品结构稀释。"
                    f"因此，{transmission['signals']}既是催化验证，也是判断事件影响能否从局部扩散到公司层面的关键；"
                    f"{transmission['risk']}则可能令增量低于预期。"
                ),
                (
                    f"对{stock_name}而言，{reason_clause}并非纯概念映射，因为{related_evidence}。"
                    "这意味着事件影响有进入报表的基础，却仍是一项重要增量而非唯一主业。"
                    f"本次事件改变的是{transmission['driver']}，传导效率取决于“{transmission['path']}”。"
                    f"市场可能低估相关业务放量对产品结构的改善，也可能高估它对公司总利润的贡献，"
                    f"两者需要由{transmission['signals']}来区分；若{transmission['risk']}，重估逻辑会被削弱。"
                ),
                (
                    f"{stock_name}已有可跟踪的事件相关经营分部，而不是从零开始的远期期权：{related_evidence}。"
                    f"公司在产业链中的位置是：{reason_clause}，{transmission['driver']}则决定增量大小。"
                    f"只有完成“{transmission['path']}”，相关业务的增长才可能改善公司整体盈利。"
                    f"{transmission['signals']}还需与其他主业表现同时改善；"
                    f"{transmission['risk']}会使局部业务亮点难以转化为公司层面的业绩变化。"
                ),
            )
            return finalize(medium_exposure_variants[variant])
        else:
            low_exposure_variants = (
                (
                    f"{stock_name}更接近“小基数、高弹性”的事件期权，而不是当前利润主线。"
                    f"{related_evidence}，公司在产业链中的具体抓手是：{reason_clause}。"
                    f"若{transmission['driver']}沿着“{transmission['path']}”兑现，相关业务增速可能很高，"
                    "但较低的收入基数意味着短期贡献未必足以改变公司整体业绩。"
                    f"这类标的最重要的不是行业空间叙事，而是{transmission['signals']}能否证明业务开始跨越规模门槛；"
                    f"若{transmission['risk']}，估值弹性往往会先于报表弹性消退。"
                ),
                (
                    f"{stock_name}在事件链条中的位置是：{reason_clause}；{related_evidence}，目前仍是较小的收入来源。"
                    f"因此，本次事件首先改变的可能是市场对业务上限的估计，随后才是{transmission['driver']}经由"
                    f"“{transmission['path']}”带来的实际利润。小基数提供增速弹性，也放大了预期与兑现之间的落差。"
                    f"{transmission['signals']}若迟迟不能改善，或出现{transmission['risk']}，这条逻辑就难以从期权走向主业。"
                ),
                (
                    f"{stock_name}已经参与事件相关业务，但收入基数仍小：{related_evidence}，"
                    f"说明公司已有业务抓手，但“{reason_clause}”所隐含的空间仍明显大于当前收入贡献。"
                    f"真正的预期差在于{transmission['driver']}能否驱动“{transmission['path']}”，从而推动业务跨过小规模阶段。"
                    f"在此之前，{transmission['signals']}比总收入增速更值得跟踪；若{transmission['risk']}，"
                    "市场对远期空间的定价可能缺少当期业绩支撑。"
                ),
            )
            return finalize(low_exposure_variants[variant])

    if contained_segments:
        contained_text = format_segment_evidence(contained_segments)
        contained_variants = (
            (
                f"{stock_name}与事件存在真实业务交集：公司已有{product_text}，与{reason_clause}所处的产业环节一致。"
                f"{contained_text}属于更宽的经营口径，相关产品可能包含其中，但不能把该分部的全部收入都视为事件敞口。"
                f"本次变化主要影响{transmission['driver']}，只有经过“{transmission['path']}”，才会形成可确认的收入和利润增量。"
                f"{transmission['signals']}能够判断相关产品是否从宽口径业务中的一部分成长为重要增量；"
                f"若{transmission['risk']}，产业链位置仍然成立，但公司层面的利润弹性会低于主题预期。"
            ),
            (
                f"{stock_name}的{contained_text}覆盖范围较宽，其中能够承载{product_text}，因此业务名称不同不等于与事件无关。"
                f"公司与新闻的具体连接点是：{reason_clause}。现阶段无法用整个分部占比直接衡量受益程度，"
                f"因为{transmission['driver']}还需沿“{transmission['path']}”传导，相关产品在分部内部的收入权重才会逐步显现。"
                f"{transmission['signals']}若持续增强，事件影响可以从产品层面扩散到公司盈利；"
                f"若{transmission['risk']}，宽口径业务规模不会自动转化为事件带来的业绩增量。"
            ),
            (
                f"{stock_name}已经具备{product_text}等业务能力，{reason_clause}并非单纯概念映射。"
                f"当前对应的收入被归入{contained_text}这类综合分部，具体占比无法单独量化，"
                "既不能把整个分部都算作受益业务，也不能因为没有同名分部就把贡献判为零。"
                f"事件能否提升公司价值，取决于{transmission['driver']}是否通过“{transmission['path']}”放大，"
                f"并最终反映在{transmission['signals']}上；{transmission['risk']}会使产品相关性与利润贡献出现明显落差。"
            ),
        )
        return finalize(contained_variants[variant])

    if top_segments:
        revenue_text = format_segment_evidence(top_segments)
        if relation_status == "product_confirmed":
            product_variants = (
                (
                    f"{stock_name}实际经营中已有{product_text}，与事件指向的{reason_clause}能够对应，业务联系并不因分部名称不同而消失。"
                    f"公司当前收入集中在{revenue_text}，相关产品没有单独拆分，因此只能确认参与环节，暂时不能把收入权重或利润弹性量化。"
                    f"本次事件若改善{transmission['driver']}，需要沿“{transmission['path']}”进入经营结果。"
                    f"{transmission['signals']}将决定这部分业务是维持小规模配套，还是成长为能够影响公司整体业绩的增量；"
                    f"若{transmission['risk']}，产品存在不等于利润一定增加。"
                ),
                (
                    f"{stock_name}拥有{product_text}，其产业链位置与{reason_clause}一致；当前的{revenue_text}并未把这部分产品单独列示。"
                    "这意味着事件关联可以在业务层面成立，但相关收入可能分散在多个经营口径中，不能简单按零处理，也不能直接套用整个分部占比。"
                    f"真正的业绩增量仍由{transmission['driver']}决定，并需完成“{transmission['path']}”。"
                    f"只有{transmission['signals']}持续改善，产品能力才会转化为公司层面的收入和盈利提升；"
                    f"{transmission['risk']}则会限制兑现幅度。"
                ),
                (
                    f"{stock_name}与新闻之间有明确产品抓手：{product_text}，对应{reason_clause}。"
                    f"收入主体目前是{revenue_text}，事件相关产品被包含在现有业务体系内而非独立分部，因而无法直接读取其规模。"
                    f"新闻首先改变{transmission['driver']}预期，随后要经过“{transmission['path']}”才能进入利润表。"
                    f"{transmission['signals']}若形成连续改善，相关产品对整体经营的贡献会逐步提高；"
                    f"若{transmission['risk']}，事件影响更可能停留在产品布局层面。"
                ),
            )
            return finalize(product_variants[variant])

        if relation_status == "business_mismatch":
            mismatch_variants = (
                (
                    f"{stock_name}当前收入集中在{revenue_text}，现有产品以{business_base}为主，"
                    f"与新闻所指的“{reason_clause}”并不是同一业务链条。"
                    "这类名称或主题上的关联不能直接推导为公司具备对应产品，更不能据此估算收入弹性。"
                    f"只有公司真正形成与事件一致的产品、客户和订单，{transmission['driver']}才可能沿“{transmission['path']}”进入经营结果。"
                    f"在此之前，{transmission['signals']}若没有出现，事件对公司基本面的影响应按较弱处理；"
                    f"{transmission['risk']}会进一步压低相关性。"
                ),
                (
                    f"{stock_name}的主要经营内容是{revenue_text}，具体产品集中在{business_base}。"
                    f"“{reason_clause}”描述的产业环节与公司现有产品体系缺少可确认的业务衔接，因此不能仅凭星级或题材把两者等同。"
                    f"本次事件即使改善{transmission['driver']}，也需要先补上产品落地和客户导入，再经过“{transmission['path']}”才可能影响业绩。"
                    f"{transmission['signals']}没有同步改善时，股价反应更可能来自主题交易；"
                    f"若{transmission['risk']}，基本面解释力会继续下降。"
                ),
                (
                    f"{stock_name}现有收入由{revenue_text}贡献，主营产品为{business_base}，与{reason_clause}指向的产品形态存在明显差异。"
                    "因此，新闻并不能直接改变公司当前订单和利润，相关性需要由新增产品、明确客户或批量交付重新建立。"
                    f"在业务连接真正形成后，{transmission['driver']}才会通过“{transmission['path']}”产生财务影响。"
                    f"现阶段{transmission['signals']}比概念标签更重要；若{transmission['risk']}，事件对公司中期业绩的贡献将十分有限。"
                ),
            )
            return finalize(mismatch_variants[variant])

        if relation_status == "profile_supported":
            supported_variants = (
                (
                    f"{stock_name}现有业务与{reason_clause}处于同一产业方向，收入主体为{revenue_text}。"
                    "相关业务没有单独形成清晰分部，说明其规模和盈利贡献仍难量化，但不能因此认定公司与事件无关。"
                    f"本次事件主要改变{transmission['driver']}，只有经由“{transmission['path']}”，业务交集才会转化为业绩增量。"
                    f"{transmission['signals']}若逐步增强，相关业务的重要性会提高；若{transmission['risk']}，"
                    "影响仍可能局限在估值预期。"
                ),
                (
                    f"{stock_name}的业务范围能够覆盖{reason_clause}所处的产业环节，但当前{revenue_text}仍是收入主体，"
                    "事件相关部分尚未单独量化。公司不是完全缺席，也尚不足以确认其对整体利润具有决定性影响。"
                    f"{transmission['driver']}需要沿“{transmission['path']}”完成兑现，"
                    f"并在{transmission['signals']}上形成持续改善；若{transmission['risk']}，业务联系对盈利的贡献会受到限制。"
                ),
                (
                    f"{stock_name}与新闻存在业务方向上的交集：{reason_clause}；公司当前收入主要来自{revenue_text}。"
                    "由于相关产品没有独立收入口径，合理结论是业务具备承接可能，但利润弹性暂时无法确认。"
                    f"事件对{transmission['driver']}的推动只有经过“{transmission['path']}”才能进入报表，"
                    f"{transmission['signals']}决定这一交集能否升级为实际增量；{transmission['risk']}是主要失效条件。"
                ),
            )
            return finalize(supported_variants[variant])

        no_segment_variants = (
            (
                f"{stock_name}当前收入集中在{revenue_text}，而{reason_clause}所指业务尚未形成可单独识别的经营规模。"
                f"这意味着新闻首先影响{transmission['driver']}预期，业务端仍需沿“{transmission['path']}”传导后才能确认。"
                f"{transmission['signals']}如果持续改善，相关业务可能从产业布局转为实际增量；"
                f"若{transmission['risk']}，公司与事件的联系即使存在，也难以解释整体收入和利润变化。"
            ),
            (
                f"{stock_name}的事件主线是：{reason_clause}，但当前收入结构尚未体现其重要性，收入重心仍是{revenue_text}。"
                "因此，这条新闻更可能先改变市场对新产品、客户导入或产业链卡位的估值，"
                f"而不是立刻改变当期利润。要让逻辑成立，{transmission['driver']}需要沿“{transmission['path']}”传导，"
                f"并在{transmission['signals']}上留下可核验痕迹。若{transmission['risk']}，事件相关性仍可能成立，"
                "但对公司整体业绩的解释力有限。"
            ),
            (
                f"{stock_name}目前更依赖{revenue_text}，事件相关业务尚未形成独立收入分部。"
                f"公司与事件的具体联系在于：{reason_clause}，更接近一条待兑现的增量主线，而非已经占据利润表的重要业务。"
                f"本次事件的研究价值，在于它是否改变{transmission['driver']}；公司的产业链位置只有经过"
                f"“{transmission['path']}”才能转化为收入。现阶段可以用{transmission['signals']}判断预期差方向；"
                f"若{transmission['risk']}，短期主题弹性与中期业绩贡献可能明显背离。"
            ),
        )
        return finalize(no_segment_variants[variant])

    if relevant_product_names:
        no_revenue_product_variants = (
            (
                f"{stock_name}已经拥有{product_text}，与{reason_clause}处于同一产业链环节，业务联系可以成立。"
                "相关产品尚未形成独立的收入占比，因此能够确认公司参与，却不能直接判断对整体利润的贡献大小。"
                f"本次事件若改善{transmission['driver']}，仍需经过“{transmission['path']}”才能形成财务增量。"
                f"{transmission['signals']}持续增强时，相关产品可能从能力储备进入规模化贡献；"
                f"若{transmission['risk']}，产品布局与实际盈利之间仍会存在较大距离。"
            ),
            (
                f"{stock_name}与事件之间有具体产品连接：{product_text}，对应{reason_clause}。"
                "目前无法单独量化这些产品的收入权重，因而不能把公司归为纯概念，也不能把产业空间直接等同于利润弹性。"
                f"{transmission['driver']}只有沿“{transmission['path']}”完成兑现，才会改变公司经营结果。"
                f"{transmission['signals']}将决定业务能否跨过小规模阶段；若{transmission['risk']}，"
                "事件对公司的影响会主要停留在产品布局层面。"
            ),
            (
                f"{stock_name}现有产品包括{product_text}，因此{reason_clause}具备现实业务基础。"
                "由于相关业务尚未单独拆分收入，其在公司整体经营中的重要性仍不能量化。"
                f"新闻对{transmission['driver']}的推动还要经过“{transmission['path']}”，"
                f"并最终体现为{transmission['signals']}的持续改善。若{transmission['risk']}，"
                "业务相关性仍然存在，但利润贡献可能明显低于市场预期。"
            ),
        )
        return finalize(no_revenue_product_variants[variant])

    if relation_status == "business_mismatch":
        no_revenue_mismatch_variants = (
            (
                f"{stock_name}现有产品以{business_base}为主，与{reason_clause}指向的业务并非同一产品链条。"
                "在缺少对应产品、客户和批量订单的情况下，新闻无法直接改变公司的收入和利润。"
                f"只有业务连接真实建立，{transmission['driver']}才可能通过“{transmission['path']}”形成经营增量。"
                f"{transmission['signals']}没有同步出现时，相关性应按较弱处理；若{transmission['risk']}，"
                "事件对公司基本面的解释力会进一步下降。"
            ),
            (
                f"{stock_name}当前业务集中在{business_base}，与新闻所述的{reason_clause}缺少明确产品衔接。"
                "这意味着星级或产业标签本身不足以确认公司受益，后续必须先出现对应产品落地和客户导入。"
                f"此后{transmission['driver']}才可能沿“{transmission['path']}”进入经营结果。"
                f"若{transmission['signals']}迟迟没有改善，或出现{transmission['risk']}，"
                "新闻影响更可能停留在短期主题层面。"
            ),
            (
                f"{stock_name}的实际产品是{business_base}，与{reason_clause}描述的产品形态存在明显差异。"
                "因此，本次事件尚不能直接映射到公司订单，相关业务需要由新增产品、明确客户或交付记录重新确认。"
                f"在此之前，{transmission['driver']}缺少进入“{transmission['path']}”的业务入口，"
                f"{transmission['signals']}也难以形成持续改善；{transmission['risk']}会进一步削弱中期业绩贡献。"
            ),
        )
        return finalize(no_revenue_mismatch_variants[variant])

    no_revenue_variants = (
        (
            f"{stock_name}现有业务为{profile_focus}；公司与事件的具体联系在于：{reason_clause}。"
            "相关收入尚未单独拆分，真实权重无法判断。"
            f"当前更有价值的问题是{transmission['driver']}能否通过{transmission['path']}形成独立披露。"
            f"在{transmission['signals']}出现前，业绩弹性仍难量化；若{transmission['risk']}，事件影响可能停留在预期层面。"
        ),
        (
            f"对{stock_name}而言，公司与事件的业务交集是：{reason_clause}，但相关收入权重尚未单独拆分，"
            "这条逻辑暂时无法完成重要性判断。"
            f"{transmission['driver']}究竟影响主业还是边缘布局，要看{transmission['signals']}能否显示"
            f"{transmission['path']}正在发生。若{transmission['risk']}，更强的利润判断便难以成立。"
        ),
        (
            f"{stock_name}的事件方向较为清楚，但业务权重仍不明确：{profile_focus}；"
            f"公司在事件链条中的具体位置是：{reason_clause}，相关收入尚未单独拆分。"
            f"这意味着盈利判断需要保留弹性，重点观察{transmission['driver']}是否经由{transmission['path']}"
            f"转化为可识别收入。{transmission['signals']}若没有改善，或出现{transmission['risk']}，"
            "就不能把业务交集进一步外推成利润贡献。"
        ),
    )
    return finalize(no_revenue_variants[variant])


def build_investment_opportunities(
    event_rows: pd.DataFrame,
    company_paths_by_source_row: dict[str, list[dict[str, str]]],
    company_profiles: dict[str, Any],
    analysis_prompt_version: str,
) -> dict[str, Any]:
    first = event_rows.iloc[0]
    event_title = first["topic_name"]
    selected_by_stock: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_rating_count = 0
    excluded_low_star_count = 0
    excluded_non_a_share_count = 0
    eligible_row_count = 0

    for _, row in event_rows.iterrows():
        filled_stars_value = row["filled_star_count"]
        if pd.isna(filled_stars_value):
            invalid_rating_count += 1
            continue

        filled_stars = int(filled_stars_value)
        if filled_stars < MIN_INVESTMENT_STARS:
            excluded_low_star_count += 1
            continue
        if filled_stars not in INVESTMENT_GROUPS:
            invalid_rating_count += 1
            continue
        stock_name = row["stock_name"]
        source_stock_code = row["stock_code"]
        if not is_a_share_code(source_stock_code):
            excluded_non_a_share_count += 1
            continue
        stock_code = normalize_security_code(source_stock_code)
        eligible_row_count += 1
        if not stock_name and not stock_code:
            invalid_rating_count += 1
            continue

        reason = clean_reason(row["reason"])
        stock_paths = company_paths_by_source_row.get(row["source_row_number"], [])
        company_evidence = build_company_evidence(row, company_profiles, stock_paths)
        record = {
            "sourceRowNumber": int(row["source_row_number"]),
            "stockCode": stock_code,
            "stockName": stock_name or stock_code,
            "rating": row["origin_star_num"],
            "filledStars": filled_stars,
            "reason": reason,
            "reasonSourceAvailable": bool(reason),
            "companyEvidence": company_evidence,
            "analysis": build_investment_analysis(
                event_title,
                stock_name or stock_code,
                reason,
                company_evidence,
                filled_stars,
            ),
        }
        stock_key = (stock_code, stock_name)
        existing = selected_by_stock.get(stock_key)
        if (
            existing is None
            or filled_stars > existing["filledStars"]
            or (
                filled_stars == existing["filledStars"]
                and record["reasonSourceAvailable"]
                and not existing["reasonSourceAvailable"]
            )
            or (
                filled_stars == existing["filledStars"]
                and record["companyEvidence"]["matched"]
                and not existing["companyEvidence"]["matched"]
            )
        ):
            selected_by_stock[stock_key] = record

    groups: list[dict[str, Any]] = []
    stocks = list(selected_by_stock.values())
    for filled_stars in sorted(INVESTMENT_GROUPS, reverse=True):
        group_stocks = sorted(
            (stock for stock in stocks if stock["filledStars"] == filled_stars),
            key=lambda stock: (stock["sourceRowNumber"], stock["stockName"], stock["stockCode"]),
        )
        if not group_stocks:
            continue
        group = INVESTMENT_GROUPS[filled_stars]
        groups.append(
            {
                "filledStars": filled_stars,
                "rating": "★" * filled_stars + "☆" * (5 - filled_stars),
                "name": group["name"],
                "relevance": group["relevance"],
                "stockCount": len(group_stocks),
                "stocks": group_stocks,
            }
        )

    missing_reason_count = sum(not stock["reasonSourceAvailable"] for stock in stocks)
    matched_company_count = sum(stock["companyEvidence"]["matched"] for stock in stocks)
    duplicate_stock_count = eligible_row_count - len(stocks)
    caveats = [
        "投资机会仅纳入 origin_star_num 中3至5个实心星的标的，并按星级从高到低分组。",
        "股票范围仅限沪深北交易所A股；源数据中的上海市场 .SS 后缀统一转换为 .SH。",
        f"公司简介与2025年主营收入构成来自《{company_profiles['sourceWorkbook']}》，优先按证券代码匹配，名称仅作唯一兜底。",
        "星级表示事件与公司业务的相对关联强度，不构成收益排序或买卖建议。",
    ]
    if missing_reason_count:
        caveats.append(f"{missing_reason_count}只标的缺少 reason，仅展示语料缺口，不做扩展推断。")
    if invalid_rating_count:
        caveats.append(f"{invalid_rating_count}条源记录因星级格式无法解析而未进入组合。")
    if excluded_low_star_count:
        caveats.append(f"{excluded_low_star_count}条低于3星的源记录已按当前关注口径排除。")
    if excluded_non_a_share_count:
        caveats.append(f"{excluded_non_a_share_count}条3至5星非A股、未上市或代码不规范记录未进入组合。")
    unmatched_company_count = len(stocks) - matched_company_count
    if unmatched_company_count:
        caveats.append(f"{unmatched_company_count}只标的未匹配到A股2025年报公司资料，多为非A股、未上市或新近上市公司。")
    if duplicate_stock_count:
        caveats.append(f"{duplicate_stock_count}条重复标的记录已保留较高星级或更完整 reason。")

    return {
        "status": "ready" if groups else "no_a_share_stocks",
        "sourceRowCount": len(event_rows),
        "eligibleSourceRowCount": eligible_row_count,
        "totalStockCount": len(stocks),
        "groupCount": len(groups),
        "invalidRatingCount": invalid_rating_count,
        "excludedLowStarCount": excluded_low_star_count,
        "excludedNonAShareCount": excluded_non_a_share_count,
        "missingReasonCount": missing_reason_count,
        "companyProfileMatchedCount": matched_company_count,
        "companyProfileUnmatchedCount": unmatched_company_count,
        "sourceWorkbook": company_profiles["sourceWorkbook"],
        "analysisPromptVersion": analysis_prompt_version,
        "groups": groups,
        "caveats": caveats,
    }


def unique_ordered(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_industry_portfolio_draft(
    event_rows: pd.DataFrame,
    company_paths_by_source_row: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    eligible_rows = event_rows[
        event_rows["filled_star_count"].between(MIN_INVESTMENT_STARS, 5, inclusive="both")
        & event_rows["stock_code"].map(is_a_share_code)
    ].copy()
    groups: dict[str, dict[str, Any]] = {}
    stocks: list[dict[str, Any]] = []
    all_level7_product_codes: set[str] = set()

    for _, stock_row in eligible_rows.iterrows():
        source_row_number = stock_row["source_row_number"]
        relevant_products = select_event_relevant_products(
            stock_row,
            company_paths_by_source_row.get(source_row_number, []),
            level7_only=True,
            limit=None,
        )
        level7_codes = {
            product["level7ProductCode"]
            for product in relevant_products
            if product["level7ProductCode"]
        }
        stocks.append(make_stock_record(stock_row, len(level7_codes), bool(level7_codes)))
        all_level7_product_codes.update(level7_codes)

        for product in relevant_products:
            level5_code = product["level5IndustryCode"]
            level5_name = product["level5IndustryName"]
            level7_code = product["level7ProductCode"]
            level7_name = product["level7ProductName"]
            if not level5_code or not level5_name or not level7_code or not level7_name:
                continue

            group = groups.setdefault(
                level5_code,
                {
                    "code": level5_code,
                    "name": level5_name,
                    "products": {},
                    "stocks": {},
                    "relevanceScore": 0,
                },
            )
            stock_key = normalize_security_code(stock_row["stock_code"])
            stock_record = {
                "stockCode": stock_key,
                "stockName": stock_row["stock_name"],
                "rating": stock_row["origin_star_num"],
                "filledStars": int(stock_row["filled_star_count"]),
            }
            existing_stock = group["stocks"].get(stock_key)
            if existing_stock is None or stock_record["filledStars"] > existing_stock["filledStars"]:
                group["stocks"][stock_key] = stock_record

            product_record = group["products"].setdefault(
                level7_code,
                {
                    "code": level7_code,
                    "name": level7_name,
                    "hierarchyPath": product["hierarchyPath"],
                    "matchedSourceLevel": 7,
                    "relevanceScore": 0,
                    "matchedTerms": [],
                    "stocks": {},
                },
            )
            product_record["relevanceScore"] = max(
                product_record["relevanceScore"],
                int(product["score"]),
            )
            product_record["matchedTerms"] = unique_ordered(
                [*product_record["matchedTerms"], *product["matchedTerms"]]
            )
            existing_product_stock = product_record["stocks"].get(stock_key)
            if (
                existing_product_stock is None
                or stock_record["filledStars"] > existing_product_stock["filledStars"]
            ):
                product_record["stocks"][stock_key] = stock_record
            group["relevanceScore"] += int(product["score"])

    return {
        "stocks": stocks,
        "groups": groups,
        "level7ProductCount": len(all_level7_product_codes),
    }


def finalize_industry_portfolio(
    portfolio_draft: dict[str, Any],
    core_industry_code: str,
    level5_catalog: dict[str, dict[str, str]],
) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for code, group in portfolio_draft["groups"].items():
        if code == core_industry_code:
            continue
        products: list[dict[str, Any]] = []
        for product in group["products"].values():
            product_stocks = sorted(
                product["stocks"].values(),
                key=lambda item: (-item["filledStars"], item["stockName"], item["stockCode"]),
            )
            products.append(
                {
                    "code": product["code"],
                    "name": product["name"],
                    "hierarchyPath": product["hierarchyPath"],
                    "matchedSourceLevel": 7,
                    "stockCount": len(product_stocks),
                    "stocks": product_stocks,
                    "relevanceScore": product["relevanceScore"],
                    "matchedTerms": product["matchedTerms"],
                }
            )
        products.sort(
            key=lambda item: (
                -int(bool(item["matchedTerms"])),
                -item["relevanceScore"],
                -item["stockCount"],
                item["name"],
                natural_code_key(item["code"]),
            )
        )
        stocks = sorted(
            group["stocks"].values(),
            key=lambda item: (-item["filledStars"], item["stockName"], item["stockCode"]),
        )
        catalog_item = level5_catalog.get(code, {})
        ranked.append(
            {
                "code": code,
                "name": catalog_item.get("name") or group["name"],
                "description": catalog_item.get("description", ""),
                "stockCount": len(stocks),
                "starWeight": sum(stock["filledStars"] for stock in stocks),
                "level7ProductCount": len(products),
                "relevanceScore": group["relevanceScore"],
                "stocks": stocks,
                "products": products,
            }
        )

    ranked.sort(
        key=lambda item: (
            -item["stockCount"],
            -item["starWeight"],
            -item["relevanceScore"],
            -item["level7ProductCount"],
            item["name"],
            natural_code_key(item["code"]),
        )
    )
    selected = ranked[:MAX_RELATED_INDUSTRIES]
    for index, industry in enumerate(selected, start=1):
        industry["rank"] = index
        industry["products"] = industry["products"][:MAX_RELATED_INDUSTRY_PRODUCTS]

    mapped_stocks = [stock for stock in portfolio_draft["stocks"] if stock["mapped"]]
    return {
        "rule": "A-share and 3 <= filled_star_count <= 5; real level-7 product -> level-5 industry",
        "sourceStockCount": len(portfolio_draft["stocks"]),
        "mappedStockCount": len(mapped_stocks),
        "unmappedStockCount": len(portfolio_draft["stocks"]) - len(mapped_stocks),
        "level7ProductCount": portfolio_draft["level7ProductCount"],
        "candidateIndustryCount": len(ranked),
        "relatedIndustryCount": len(selected),
        "stocks": portfolio_draft["stocks"],
        "relatedIndustries": selected,
    }


def build_event_draft(
    event_rows: pd.DataFrame,
    company_paths_by_source_row: dict[str, list[dict[str, str]]],
    company_profiles: dict[str, Any],
    investment_prompt_version: str,
) -> dict[str, Any]:
    first = event_rows.iloc[0]
    star_rows = event_rows[
        event_rows["filled_star_count"].eq(4)
        & event_rows["stock_code"].map(is_a_share_code)
    ].copy()
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
                "stockCode": normalize_security_code(stock_row["stock_code"]),
                "stockName": stock_row["stock_name"],
                "rating": stock_row["origin_star_num"],
                "filledStars": int(stock_row["filled_star_count"]),
            }

    return {
        "mainId": first["main_id"],
        "uid": first["uid"],
        "title": first["topic_name"],
        "date": first["calendar_day"],
        "newsText": extract_news_text(first["source_reason"]),
        "stocks": stocks,
        "candidates": candidates,
        "industryPortfolioDraft": build_industry_portfolio_draft(
            event_rows,
            company_paths_by_source_row,
        ),
        "investmentOpportunities": build_investment_opportunities(
            event_rows,
            company_paths_by_source_row,
            company_profiles,
            investment_prompt_version,
        ),
    }


def choose_core_products(
    candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in candidates.values():
        if (
            candidate["matchedSourceLevel"] != 7
            or not candidate["level7ProductCode"]
            or not candidate["level7ProductName"]
            or not candidate["level5IndustryCode"]
            or not candidate["level5IndustryName"]
        ):
            continue
        candidate = {**candidate}
        candidate["stockCount"] = len(candidate["stocks"])
        ranked.append(candidate)

    ranked.sort(
        key=lambda item: (
            -item["strongRelevanceScore"],
            -item["relevanceScore"],
            -item["stockCount"],
            item["name"],
            natural_code_key(item["code"]),
        )
    )
    topic_relevance = [item for item in ranked if item["strongRelevanceScore"] > 0]
    high_relevance = [item for item in ranked if item["relevanceScore"] >= 3]
    medium_relevance = [item for item in ranked if item["relevanceScore"] >= 2]
    pool = topic_relevance or high_relevance or medium_relevance
    return pool[:MAX_CORE_PRODUCTS]


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


def build_industry_overview(target: dict[str, Any]) -> str:
    description = clean_text(target.get("description", ""))
    first_sentence = re.split(r"[。！？；;]", description, maxsplit=1)[0].strip(" ，,：:")
    products = unique_ordered(item["name"] for item in target["matchedCoreProducts"] if item["name"])
    product_text = "、".join(products[:3]) + ("等" if len(products) > 3 else "")
    if first_sentence:
        overview = first_sentence + "。"
    elif product_text:
        overview = f"{target['name']}主要覆盖{product_text}相关产品或服务。"
    else:
        overview = f"{target['name']}是本次事件涉及的细分产业。"
    if product_text and not any(product in overview for product in products[:3]):
        overview += f"与本次事件关联度较高的产品包括{product_text}。"
    return re.sub(r"\s+", " ", overview).strip()


def build_industry_analysis(
    company_core_products: list[dict[str, Any]],
    level5_catalog: dict[str, dict[str, str]],
    research_bundle: dict[str, Any] | None,
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
            "target": None,
            "overview": None,
            "impact": None,
            "researchSources": [],
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
    public_target = {"code": target["code"], "name": target["name"]}
    synthesis = (research_bundle or {}).get("synthesis") or {}
    if synthesis.get("summaryStatus") != "ai-reviewed":
        return {
            "status": "research_pending",
            "target": public_target,
            "overview": build_industry_overview(target),
            "impact": None,
            "researchSources": [],
            "reason": "该产业的专项研究内容正在补充中",
        }

    if (
        clean_text((research_bundle or {}).get("industryCode")) != target["code"]
        or clean_text((research_bundle or {}).get("industryName")) != target["name"]
    ):
        raise ValueError(
            f"事件研报语料与五级产业不一致: {research_bundle.get('mainId')} "
            f"{research_bundle.get('industryName')} != {target['name']}"
        )

    overview = clean_text(synthesis.get("industryOverview"))
    impact_direction = clean_text(synthesis.get("impactDirection"))
    impact_text = clean_text(synthesis.get("impactAnalysis"))
    allowed_directions = {"偏利好", "偏利空", "利好与利空并存", "影响暂不明确"}
    if not overview or not impact_text or impact_direction not in allowed_directions:
        raise ValueError(f"事件研报综合结论不完整: {research_bundle.get('mainId')}")
    forbidden = [
        phrase
        for phrase in CLIENT_BANNED_PHRASES
        if phrase in overview or phrase in impact_text
    ]
    if forbidden:
        raise ValueError(f"投资者可见产业解读包含禁用表述: {forbidden}")

    report_index = {
        clean_text(report.get("reportId")): report
        for report in (research_bundle or {}).get("reports", [])
    }
    research_sources: list[dict[str, str]] = []
    for report_id in synthesis.get("sourceReportIds", []):
        report = report_index.get(clean_text(report_id))
        if not report:
            raise ValueError(f"产业解读引用了不存在的研报: {report_id}")
        publish_date = clean_text(report.get("publishDate"))
        if re.fullmatch(r"\d{8}", publish_date):
            publish_date = f"{publish_date[:4]}-{publish_date[4:6]}-{publish_date[6:]}"
        research_sources.append(
            {
                "reportId": clean_text(report.get("reportId")),
                "title": clean_text(report.get("title")),
                "institution": clean_text(report.get("institution")),
                "publishDate": publish_date,
            }
        )
    if len(research_sources) != 3:
        raise ValueError(f"每条产业解读必须引用3篇已通读研报: {research_bundle.get('mainId')}")

    return {
        "status": "ready",
        "target": public_target,
        "overview": overview,
        "impact": {"direction": impact_direction, "text": impact_text},
        "researchSources": research_sources,
        "reason": "",
    }


def finalize_event(
    draft: dict[str, Any],
    level5_catalog: dict[str, dict[str, str]],
    research_bundle: dict[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    company_core_products = draft["selectedCoreProducts"]
    selected_product_counts: Counter[str] = Counter()
    for product in company_core_products:
        selected_product_counts.update(product["stocks"].keys())
    core_stocks = [
        {
            **stock,
            "mapped": str(stock["sourceRowNumber"]) in selected_product_counts,
            "anchorProductCount": selected_product_counts.get(str(stock["sourceRowNumber"]), 0),
        }
        for stock in draft["stocks"]
    ]

    output_core: list[dict[str, Any]] = []
    for core in company_core_products:
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
                "stockCount": core["stockCount"],
                "stocks": sorted(
                    core["stocks"].values(),
                    key=lambda item: (-item["filledStars"], item["stockName"], item["stockCode"]),
                ),
                "relevanceScore": core["relevanceScore"],
                "strongRelevanceScore": core["strongRelevanceScore"],
                "matchedTerms": core["matchedTerms"],
            }
        )

    mapped_stocks = [stock for stock in core_stocks if stock["mapped"]]
    unmapped_stocks = [stock for stock in core_stocks if not stock["mapped"]]
    if not core_stocks:
        status = "no_four_star_stocks"
    elif not mapped_stocks:
        status = "no_company_product_mapping"
    elif not company_core_products:
        status = "no_relevant_core_products"
    else:
        status = "ready"

    caveats = [
        "核心产品仅纳入沪深北A股中恰好4个实心星的标的。",
        "相关产业仅纳入3至5星A股标的，先确认真实七级产品，再按该产品的父级五级产业聚合。",
        "两个相关产业会排除核心产业，并按支持标的数、星级权重、事件相关度和七级产品覆盖排序。",
        "本阶段暂不展示或推断上下游关系；证据不足时不会强行补足两个产业。",
    ]
    if unmapped_stocks:
        caveats.append(f"{len(unmapped_stocks)}只4星A股标的未穿透到事件相关七级产品。")

    industry_analysis = build_industry_analysis(
        company_core_products,
        level5_catalog,
        research_bundle,
    )
    core_industry_code = (
        industry_analysis["target"]["code"]
        if industry_analysis.get("target")
        else ""
    )
    industry_portfolio = finalize_industry_portfolio(
        draft["industryPortfolioDraft"],
        core_industry_code,
        level5_catalog,
    )
    return {
        "schemaVersion": 14,
        "generatedAt": generated_at,
        "status": status,
        "event": {
            "mainId": draft["mainId"],
            "uid": draft["uid"],
            "title": draft["title"],
            "date": draft["date"],
        },
        "selection": {
            "rule": "A-share and filled_star_count == 4",
            "sourceStockCount": len(core_stocks),
            "mappedStockCount": len(mapped_stocks),
            "unmappedStockCount": len(unmapped_stocks),
            "stocks": core_stocks,
            "unmappedStocks": unmapped_stocks,
        },
        "totals": {
            "candidateCoreProductCount": len(draft["candidates"]),
            "selectedCoreProductCount": len(output_core),
            "selectedCompanyCoreProductCount": len(company_core_products),
            "level7ProductCount": industry_portfolio["level7ProductCount"],
            "relatedIndustryCandidateCount": industry_portfolio["candidateIndustryCount"],
            "shownRelatedIndustryCount": industry_portfolio["relatedIndustryCount"],
        },
        "productIndustryMap": {
            "coreProducts": output_core,
            "relatedIndustries": industry_portfolio["relatedIndustries"],
        },
        "industryPortfolio": industry_portfolio,
        "industryAnalysis": industry_analysis,
        "investmentOpportunities": draft["investmentOpportunities"],
        "caveats": caveats,
    }


def validate_sources(events: pd.DataFrame, paths: pd.DataFrame) -> None:
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


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    workspace_root = project_root.parent
    parser = argparse.ArgumentParser(description="生成新闻核心产品、相关产业与3至5星投资机会 JSON")
    parser.add_argument(
        "--events",
        type=Path,
        default=workspace_root / "1.迅兔事件数据获取" / "蓝宝书_事件关联股票.csv",
    )
    parser.add_argument(
        "--company-profiles",
        type=Path,
        default=workspace_root / "1.迅兔事件数据获取" / "2025年报公司简介和主营业务占比.xlsx",
    )
    parser.add_argument(
        "--paths",
        type=Path,
        default=project_root / "data" / "generated" / "event_stock_industry_paths.csv",
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
        "--investment-prompt-template",
        type=Path,
        default=project_root / "prompts" / "investment-opportunity-analyst-v4.md",
    )
    parser.add_argument(
        "--report-corpus",
        type=Path,
        default=project_root / "generated" / "industry_report_corpus.json",
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
    company_profiles = read_company_profiles(args.company_profiles)
    paths, path_encoding = read_csv_columns(args.paths, PATH_COLUMNS)
    nodes, node_encoding = read_csv_columns(args.nodes, NODE_COLUMNS)
    prompt_template = args.prompt_template.read_text(encoding="utf-8")
    investment_prompt_template = args.investment_prompt_template.read_text(encoding="utf-8")
    report_corpus = (
        json.loads(args.report_corpus.read_text(encoding="utf-8"))
        if args.report_corpus.exists()
        else {"events": []}
    )
    research_by_main_id = {
        clean_text(item.get("mainId")): item
        for item in report_corpus.get("events", [])
        if clean_text(item.get("mainId"))
    }
    missing_placeholders = [
        placeholder
        for placeholder in (
            "{{industry_name}}",
            "{{industry_description}}",
            "{{event_basic_info}}",
            "{{industry_research_corpus}}",
        )
        if placeholder not in prompt_template
    ]
    if missing_placeholders:
        raise ValueError(f"产业认知提示词缺少占位符: {missing_placeholders}")
    missing_investment_placeholders = [
        placeholder
        for placeholder in (
            "{{event_title}}",
            "{{stock_name}}",
            "{{stock_code}}",
            "{{filled_stars}}",
            "{{reason}}",
            "{{company_profile}}",
            "{{major_products}}",
            "{{revenue_composition}}",
            "{{mapped_products}}",
            "{{revenue_segment_relations}}",
        )
        if placeholder not in investment_prompt_template
    ]
    if missing_investment_placeholders:
        raise ValueError(f"投资机会提示词缺少占位符: {missing_investment_placeholders}")
    level5_catalog = build_level5_catalog(nodes)

    events.insert(0, "source_row_number", [str(number) for number in range(2, len(events) + 2)])
    events["filled_star_count"] = events["origin_star_num"].map(filled_star_count)
    validate_sources(events, paths)

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
        draft = build_event_draft(
            event_rows,
            company_paths_by_source_row,
            company_profiles,
            args.investment_prompt_template.name,
        )
        drafts.append(draft)

    for draft in drafts:
        draft["selectedCoreProducts"] = choose_core_products(draft["candidates"])

    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    index_events: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    analysis_status_counts: dict[str, int] = defaultdict(int)
    for draft in drafts:
        payload = finalize_event(
            draft,
            level5_catalog,
            research_by_main_id.get(draft["mainId"]),
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
                "relatedIndustryCount": payload["totals"]["shownRelatedIndustryCount"],
                "industryAnalysisStatus": payload["industryAnalysis"]["status"],
                "investmentStockCount": payload["investmentOpportunities"]["totalStockCount"],
                "investmentGroupCount": payload["investmentOpportunities"]["groupCount"],
                "investmentCompanyProfileMatchedCount": payload["investmentOpportunities"]["companyProfileMatchedCount"],
                "investmentCompanyProfileUnmatchedCount": payload["investmentOpportunities"]["companyProfileUnmatchedCount"],
                "level5IndustryCode": analysis_target["code"] if analysis_target else "",
                "level5IndustryName": analysis_target["name"] if analysis_target else "",
            }
        )

    index_events.sort(key=lambda item: (item["date"], natural_code_key(item["mainId"])), reverse=True)
    manifest = {
        "schemaVersion": 14,
        "generatedAt": generated_at,
        "eventCount": len(index_events),
        "statusCounts": dict(sorted(status_counts.items())),
        "industryAnalysisStatusCounts": dict(sorted(analysis_status_counts.items())),
        "source": {
            "events": args.events.name,
            "eventEncoding": event_encoding,
            "companyProfiles": args.company_profiles.name,
            "companyProfileCount": company_profiles["companyCount"],
            "investmentPrompt": args.investment_prompt_template.name,
            "paths": args.paths.name,
            "pathEncoding": path_encoding,
            "nodes": args.nodes.name,
            "nodeEncoding": node_encoding,
        },
        "events": index_events,
    }
    atomic_write_json(args.output_dir / "index.json", manifest)

    print(f"新闻数: {len(index_events):,}")
    print(f"有4星A股核心标的的新闻: {sum(item['sourceStockCount'] > 0 for item in index_events):,}")
    print(f"可展示核心产品的新闻: {status_counts.get('ready', 0):,}")
    print(f"展示相关产业数: {sum(item['relatedIndustryCount'] for item in index_events):,}")
    print(f"可生成五级产业认知语料的新闻: {analysis_status_counts.get('ready', 0):,}")
    print(f"A股2025年报公司资料: {company_profiles['companyCount']:,}")
    print(f"3至5星投资标的: {sum(item['investmentStockCount'] for item in index_events):,}")
    print(f"已匹配年报资料: {sum(item['investmentCompanyProfileMatchedCount'] for item in index_events):,}")
    print(f"状态分布: {dict(sorted(status_counts.items()))}")
    print(f"输出目录: {args.output_dir}")


if __name__ == "__main__":
    main()
