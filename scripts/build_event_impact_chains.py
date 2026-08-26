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
    "本次事件首先改变",
    "只有经过",
    "才会形成收入和利润增量",
    "产业链位置仍然成立",
    "利润弹性会低于主题预期",
    "预期进入经营结果仍需完成",
    "相关性停留在估值预期",
    "有望受益",
    "未来可期",
    "长期空间广阔",
    "建议关注",
    "后续重点跟踪",
    "系统打分",
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
    "thermal_management": (
        "液冷", "冷板", "冷却液", "冷却工质", "温控", "散热", "热管理", "精密空调",
        "机房空调", "冷水机组", "液冷机组", "浸没式冷却", "冷板式冷却", "均热板", "工质",
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
    "biofuel": (
        "可持续航空燃料", "航空生物燃料", "生物航油", "生物燃料", "生物柴油",
        "废弃油脂", "餐厨废油", "地沟油", "再生废油", "生物能源", "saf", "uco", "hvo",
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
    ("机房温控节能设备", {"thermal_management", "network_compute"}),
    ("户外机柜温控节能设备", {"thermal_management", "network_compute"}),
    ("温控节能设备", {"thermal_management", "network_compute"}),
    ("新能源", {"battery_storage", "solar", "wind_power", "power_grid", "hydrogen_energy"}),
    ("新能源材料", {"battery_storage", "solar", "advanced_materials", "chemicals"}),
    ("生物能源", {"biofuel", "oil_gas_energy", "environmental"}),
    ("生物能源产业", {"biofuel", "oil_gas_energy", "environmental"}),
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
            company["revenueComposition"],
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


BUSINESS_ROLE_KEYWORDS = {
    "wafer_foundry": ("晶圆代工", "晶圆制造", "晶圆加工", "晶圆厂", "先进制程", "成熟制程", "制程价格", "台积电"),
    "chip_packaging": ("芯片封装", "集成电路封装", "先进封装", "封装测试", "芯片封测", "晶圆级封装", "倒装", "qfn", "dfn", "sip"),
    "semiconductor_equipment": ("刻蚀设备", "薄膜沉积设备", "光刻设备", "量测设备", "清洗设备", "封装设备", "测试设备", "半导体设备"),
    "power_semiconductor": ("功率半导体", "功率器件", "igbt", "mosfet", "功率模块", "功率模组", "二极管"),
    "cpo": ("共封装光学", "cpo", "光引擎", "外置光源", "els"),
    "optical_module": ("光模块", "光收发", "光通信模块", "光互联产品"),
    "optical_component": ("光器件", "光组件", "光纤阵列", "fau", "连接器", "耦合", "光纤预制棒"),
    "optical_chip": ("光芯片", "激光器", "dfb", "cw激光", "外置光源"),
    "liquid_cooling": ("液冷", "冷板", "冷却工质", "冷却液", "液冷机组", "浸没式冷却", "冷板式冷却"),
    "thermal_management": ("温控", "散热", "热管理", "精密空调", "机房空调", "均热板", "冷水机组"),
    "server_compute": ("服务器", "交换机", "数据中心", "算力", "超算", "hpc"),
    "innovative_drug": ("创新药", "新药", "临床", "适应症", "药物授权", "药品获批"),
    "drug_service": ("cro", "cdmo", "研发服务", "临床服务", "医药外包", "商业化生产"),
    "biofuel_feedstock": ("废弃油脂", "地沟油", "餐厨废油", "uco", "原料收集", "油脂回收"),
    "biofuel_production": ("可持续航空燃料", "生物航油", "生物柴油", "生物燃料", "saf", "hvo"),
    "battery": ("动力电池", "储能电池", "锂电池", "固态电池", "电芯", "正极材料", "负极材料", "电解液", "隔膜"),
    "solar": ("光伏", "太阳能", "光伏组件", "逆变器", "电池片"),
    "grid": ("电网", "输变电", "变压器", "配电", "电力设备", "电力电子", "充电桩"),
    "robotics": ("机器人", "减速器", "伺服", "机器视觉", "工业自动化"),
    "software_ai": ("人工智能", "大模型", "ai软件", "算法", "数据库", "操作系统", "云服务"),
}

BUSINESS_ROLE_LABELS = {
    "wafer_foundry": "晶圆代工与制程定价",
    "chip_packaging": "芯片封装与测试",
    "semiconductor_equipment": "半导体制造设备",
    "power_semiconductor": "功率器件",
    "cpo": "CPO与光引擎",
    "optical_module": "光模块",
    "optical_component": "光器件与精密连接",
    "optical_chip": "光芯片与激光器",
    "liquid_cooling": "液冷系统、冷板与工质",
    "thermal_management": "温控与散热设备",
    "server_compute": "服务器与数据中心设备",
    "innovative_drug": "创新药权益与商业化",
    "drug_service": "医药研发及生产服务",
    "biofuel_feedstock": "废弃油脂原料",
    "biofuel_production": "SAF与生物燃料生产",
    "battery": "动力电池与储能材料",
    "solar": "光伏产品",
    "grid": "电网与电力设备",
    "robotics": "机器人与工业自动化",
    "software_ai": "AI软件与算力应用",
}

ROLE_COMPATIBILITY = {
    "cpo": {"cpo", "optical_module", "optical_component", "optical_chip", "chip_packaging", "semiconductor_equipment"},
    "optical_module": {"cpo", "optical_module", "optical_component", "optical_chip"},
    "optical_component": {"cpo", "optical_module", "optical_component", "optical_chip"},
    "optical_chip": {"cpo", "optical_module", "optical_component", "optical_chip"},
    "liquid_cooling": {"liquid_cooling", "thermal_management", "server_compute"},
    "thermal_management": {"liquid_cooling", "thermal_management"},
    "innovative_drug": {"innovative_drug", "drug_service"},
    "biofuel_production": {"biofuel_production", "biofuel_feedstock"},
}


def infer_business_roles(value: Any) -> set[str]:
    text = normalize_text(value)
    return {
        role
        for role, keywords in BUSINESS_ROLE_KEYWORDS.items()
        if any(normalize_text(keyword) in text for keyword in keywords)
    }


def roles_are_compatible(event_roles: set[str], company_roles: set[str]) -> bool:
    if not event_roles or not company_roles:
        return False
    if event_roles & company_roles:
        return True
    return any(
        company_role in ROLE_COMPATIBILITY.get(event_role, {event_role})
        for event_role in event_roles
        for company_role in company_roles
    )


def role_label(roles: set[str], fallback: str) -> str:
    labels = [BUSINESS_ROLE_LABELS[role] for role in BUSINESS_ROLE_LABELS if role in roles]
    return "、".join(labels[:2]) or fallback


def infer_realization_stage(event_title: str, reason: str) -> tuple[int, str, str]:
    text = normalize_text(f"{event_title} {reason}")
    stage_rules = (
        (11, "利润体现", ("利润体现", "贡献利润", "实现盈利")),
        (10, "回款", ("完成回款", "收到货款", "回款")),
        (9, "收入确认", ("确认收入", "收入确认")),
        (8, "规模出货", ("规模出货", "大批量交付", "批量供货", "规模交付")),
        (7, "小批交付", ("小批交付", "小批量供货", "小批量交付")),
        (6, "正式合同或订单", ("正式合同", "销售合同", "采购订单", "中标", "获得订单", "签订合同")),
        (5, "框架协议", ("框架协议", "战略协议", "合作协议")),
        (4, "客户定点", ("客户定点", "项目定点", "获得定点", "定点")),
        (3, "认证或验证", ("完成认证", "通过认证", "完成验证", "通过验证", "联合验证", "客户认证", "进入供应链", "进入产线", "验证")),
        (2, "送样", ("送样", "样品测试", "样品验证")),
        (1, "研发或试产", ("试产", "中试", "在研", "研发", "临床")),
        (0, "概念或布局", ("布局", "关注", "具备能力", "技术储备", "互动平台")),
    )
    for rank, label, keywords in stage_rules:
        if any(normalize_text(keyword) in text for keyword in keywords):
            return rank, label, keywords[0]
    return -1, "行业事件", ""


def extract_reason_fact(reason: str, event_title: str) -> str:
    candidates: list[tuple[int, str]] = []
    promotional_terms = ("受益", "龙头", "核心标的", "直接映射", "最直接", "稀缺标的", "弹性标的", "值得")
    fact_terms = ("产品", "设备", "材料", "客户", "订单", "合同", "中标", "验证", "认证", "定点", "送样", "量产", "供货", "产线", "项目", "权益", "授权")
    for clause in re.split(r"[。；;！!?，,]", professionalize_reason(reason)):
        cleaned = clean_text(clause).strip(" ：:，,；;。")
        if len(cleaned) < 8 or normalize_text(cleaned) in normalize_text(event_title):
            continue
        if any(term in cleaned for term in promotional_terms):
            continue
        score = sum(2 for term in fact_terms if term in cleaned)
        score += 2 if re.search(r"\d", cleaned) else 0
        score += 1 if any(term in cleaned for term in ("已", "完成", "进入", "覆盖", "占")) else 0
        if score:
            candidates.append((score, cleaned))
    if not candidates:
        return ""
    return compact_text(max(candidates, key=lambda item: (item[0], len(item[1])))[1], 72)


def build_investment_analysis(
    event_title: str,
    stock_name: str,
    reason: str,
    company_evidence: dict[str, Any],
    filled_stars: int,
) -> str:
    """Write an A-share event note around business identity, realization and disproof."""

    reason_text = professionalize_reason(reason)
    event_label = clean_text(event_title)
    for source_term, client_term in (
        ("半年度报告", "中期业绩"), ("半年报", "中期业绩"),
        ("年度报告", "年度业绩"), ("年报", "年度业绩"),
        ("季度报告", "季度业绩"), ("季报", "季度业绩"),
    ):
        event_label = event_label.replace(source_term, client_term)

    transmission = infer_event_transmission(event_title, reason_text)
    business_relation = company_evidence.get("businessRelation", {})
    relation_status = clean_text(business_relation.get("status")) or "unavailable"
    relevant_products = list(dict.fromkeys(
        clean_text(product.get("name"))
        for product in business_relation.get("relevantProducts", [])
        if clean_text(product.get("name"))
    ))
    known_products = list(dict.fromkeys(
        clean_text(product)
        for product in business_relation.get("knownProducts", [])
        if clean_text(product)
    ))
    relevant_product_text = "、".join(relevant_products[:4])
    known_product_text = "、".join(known_products[:4])
    profile_focus = compact_text(
        company_evidence.get("profileSummary") or company_evidence.get("majorProducts"), 82
    ).rstrip("。；;，, ")
    business_base = compact_text(
        company_evidence.get("majorProducts") or known_product_text or profile_focus or "现有产品与服务", 88
    ).rstrip("。；;，, ")

    positive_segments = [
        segment for segment in company_evidence.get("revenueSegments", [])
        if segment.get("sharePct", 0) > 0
    ]
    direct_segments = [segment for segment in positive_segments if segment.get("relationType") == "direct"]
    contained_segments = [segment for segment in positive_segments if segment.get("relationType") == "contained"]
    top_segments = positive_segments[:3]
    top_revenue_text = format_segment_evidence(top_segments, 3)

    event_roles = infer_business_roles(event_title)
    company_business_text = " ".join((
        company_evidence.get("majorProducts", ""), company_evidence.get("companyProfile", ""),
        known_product_text, relevant_product_text,
        " ".join(segment["name"] for segment in positive_segments),
    ))
    company_roles = infer_business_roles(company_business_text)
    reason_roles = infer_business_roles(reason_text)
    role_match = roles_are_compatible(event_roles, company_roles)
    semantic_overlap = bool(
        semantic_business_tags(event_title) & semantic_business_tags(company_business_text) & SPECIFIC_BUSINESS_TAGS
    )
    event_names_company = bool(normalize_text(stock_name) and normalize_text(stock_name) in normalize_text(event_title))

    role_segments = [
        segment for segment in positive_segments
        if event_roles & infer_business_roles(segment["name"])
    ]
    effective_direct_segments = direct_segments or role_segments
    direct_share = sum(segment["sharePct"] for segment in effective_direct_segments)
    direct_text = format_segment_evidence(effective_direct_segments, 3)
    contained_text = format_segment_evidence(contained_segments, 3)

    stage_rank, stage_label, _ = infer_realization_stage(event_title, reason_text)
    early_stage = stage_rank in {0, 1, 2}
    same_profit_pool = role_match or not event_roles or not company_roles
    advanced_process_event = bool(re.search(r"(?:[357]\s*nm|先进制程)", event_title, flags=re.IGNORECASE))
    specialty_process_company = any(
        term in normalize_text(f"{company_business_text} {reason_text}")
        for term in ("成熟制程", "特色工艺", "功率器件晶圆制造", "mems晶圆制造")
    )
    advanced_process_company = bool(re.search(
        r"(?:[357]\s*nm|先进制程)", f"{company_business_text} {reason_text}", flags=re.IGNORECASE
    ))
    process_spec_mismatch = advanced_process_event and specialty_process_company and not advanced_process_company

    if direct_share > 0 and same_profit_pool:
        relation_label = "真相关" if direct_share >= 15 else "小基数布局"
    elif relation_status == "broad_segment":
        relation_label = "宽口径相关"
    elif relation_status == "product_confirmed":
        relation_label = "小基数布局" if early_stage else "宽口径相关"
    elif relation_status == "profile_supported":
        if role_match and role_segments and direct_share >= 15:
            relation_label = "真相关"
        elif early_stage:
            relation_label = "小基数布局"
        else:
            relation_label = "宽口径相关"
    elif relation_status == "business_mismatch":
        relation_label = "宽口径相关" if event_names_company and role_match else "错位"
    elif relation_status in {"unverified", "unavailable"}:
        if event_names_company and (role_match or semantic_overlap):
            relation_label = "小基数布局" if early_stage else "宽口径相关"
        elif role_match and reason_roles & company_roles:
            relation_label = "小基数布局"
        else:
            relation_label = "蹭概念"
    elif event_roles and company_roles and not role_match:
        relation_label = "错位"
    else:
        relation_label = "宽口径相关" if semantic_overlap else "蹭概念"

    if relation_label == "真相关" and not same_profit_pool:
        relation_label = "宽口径相关"
    if process_spec_mismatch:
        relation_label = "错位"

    event_role_text = role_label(event_roles, compact_text(event_label, 38))
    company_role_text = role_label(company_roles, known_product_text or compact_text(business_base, 46))
    if process_spec_mismatch:
        event_role_text = "7nm及以下先进制程代工与定价"
        company_role_text = "成熟制程或特色工艺晶圆制造"
    product_anchor = relevant_product_text or known_product_text or compact_text(business_base, 54)
    variant = narrative_variant(stock_name)
    reason_fact = extract_reason_fact(reason, event_title)

    if relation_label == "真相关":
        openings = (
            f"真相关。{stock_name}这次对应的不是泛题材，而是{product_anchor}，新闻动到的就是公司能收费的产品线。",
            f"{stock_name}和这件事属于真相关，落点在{product_anchor}；产品、客户使用场景和公司收入科目能接上。",
            f"真相关。这条新闻确实打到{stock_name}的生意上，直接抓手是{product_anchor}，不是只靠名字联想。",
        )
    elif relation_label == "宽口径相关":
        openings = (
            f"宽口径相关。{stock_name}能接上{product_anchor}这条线，但新闻对应的实际敞口没有被单独拆出来。",
            f"{stock_name}不是纯蹭热点，不过只能算宽口径相关：公司卖{product_anchor}，与事件处在同一业务场景，分部口径却给不出准确权重。",
            f"宽口径相关。这事和{stock_name}有业务交集，真正能对上的部分是{product_anchor}；问题在于这部分被装在更大的收入科目里。",
        )
    elif relation_label == "小基数布局":
        openings = (
            f"小基数布局。{stock_name}在{product_anchor}上有产品或项目，但目前更像一条待放量的新业务，改不了公司当期收入大盘。",
            f"小基数布局。{stock_name}方向没跑偏，能对应的是{product_anchor}，只是生意还小，题材热度明显跑在报表前面。",
            f"小基数布局。这票不是完全没货，{stock_name}手里有{product_anchor}，但现阶段不能当成熟主业定价。",
        )
    elif relation_label == "错位":
        openings = (
            f"业务错位。新闻要看的是{event_role_text}，{stock_name}目前卖的主要是{company_role_text}，同在一条大产业链不代表赚的是同一笔钱。",
            f"业务错位。{stock_name}和这条新闻对不上同一个利润池：事件影响{event_role_text}，公司收入落在{company_role_text}，中间缺少直接订单关系。",
            f"业务错位。这次不能硬往{stock_name}身上套。新闻对象是{event_role_text}，公司手里的实货是{company_role_text}，产品用途和收款环节不同。",
        )
    else:
        openings = (
            f"蹭概念成分更重。{stock_name}现有产品里找不到与{event_role_text}同用途、同客户环节的明确收入抓手。",
            f"蹭概念。{stock_name}目前只能算题材映射：新闻讲的是{event_role_text}，公司能落到报表的仍是{company_role_text}，两边缺产品和订单验证。",
            f"蹭概念。这条新闻和{stock_name}的关系更像分时图逻辑，现有业务没有给出{event_role_text}对应的产品、客户位置或收入科目。",
        )
    opening = openings[variant]
    fact_sentence = f"公司侧能落地的具体事实是{reason_fact}。" if reason_fact else ""

    if relation_label == "错位" and direct_share > 0 and direct_text:
        revenue_sentence = f"{direct_text}合计约占收入{format_share_pct(direct_share)}，说明{company_role_text}确实是公司生意，但这恰好证明钱落在另一类产品和收款环节。"
    elif direct_share >= 50 and direct_text:
        revenue_sentence = f"{direct_text}合计约占收入{format_share_pct(direct_share)}，是主业级别，订单、售价或出货一旦变化，整张利润表都会有感觉。"
    elif direct_share >= 15 and direct_text:
        revenue_sentence = f"{direct_text}合计约占收入{format_share_pct(direct_share)}，已经有经营分量，但公司其他业务仍会稀释这条新闻对整体利润的影响。"
    elif direct_share > 0 and direct_text:
        revenue_sentence = f"{direct_text}合计约占收入{format_share_pct(direct_share)}，产品是真产品，分部却还是小分部，高增速也不等于能拉动全公司。"
    elif contained_text:
        revenue_sentence = f"相关产品被装进{contained_text}这类大分部，能确认公司参与，却不能把整个分部占比都算成新闻敞口。"
    elif top_revenue_text:
        revenue_sentence = f"公司收入大头在{top_revenue_text}，事件相关产品没有独立列项，能判断业务位置，算不出它到底贡献了多少收入和利润。"
    else:
        revenue_sentence = "现有信息没有把对应产品落到明确收入科目，眼下只能判断业务方向，不能给经营权重。"

    context_roles = event_roles | company_roles | reason_roles
    driver = transmission["driver"]
    if not same_profit_pool and event_roles and company_roles:
        operating_sentence = (
            f"这里最容易混淆的是产业链相邻和利润直接受益：{event_role_text}的{driver}不会自动变成"
            f"{company_role_text}的提价或新增订单，先影响的反而可能是客户采购节奏、成本或资本开支。"
        )
    elif "liquid_cooling" in context_roles or "thermal_management" in context_roles:
        operating_sentence = (
            "液冷事件真正改的是客户认证、冷板或工质方案的定型，以及后面的采购量。验证通过只解决技术可用性，"
            "还要经过定点和批量订单；收入放量靠交付数量，利润则会被定制开发、材料成本、大客户议价和售后维护啃掉。"
        )
    elif "semiconductor_equipment" in company_roles:
        operating_sentence = (
            "设备公司赚的不是芯片涨价本身，而是晶圆厂扩线形成的设备订单。合同之后还有交付和验收，收入落点取决于验收节奏；"
            "研发投入、售后服务和应收回款会决定订单看着很满时，利润和现金能不能同步。"
        )
    elif "wafer_foundry" in company_roles or "power_semiconductor" in company_roles:
        operating_sentence = (
            "这类公司的报表敏感项是报价、排产、产能利用率和产品结构。紧缺型号多卖、产线更满可以抬收入，"
            "但晶圆及封装成本、良率爬坡、折旧和客户压价会吃掉价差，收入涨幅不能直接照搬成利润涨幅。"
        )
    elif context_roles & {"cpo", "optical_module", "optical_component", "optical_chip"}:
        if "semiconductor_equipment" in company_roles:
            operating_sentence = "CPO设备收入看客户扩线、工艺改造和新增测试工位，订单领先于收入，验收决定报表时点，售后投入和设备标准化程度决定毛利质量。"
        elif "optical_component" in company_roles:
            operating_sentence = "精密连接与耦合件赚的是单机用量和供货份额，平台定点转成批量采购才算数；量产良率、自动化程度和客户压价决定新增出货能留下多少利润。"
        elif "optical_chip" in company_roles:
            operating_sentence = "光源和光芯片看单套系统用量、功率规格与供货份额，认证慢、良率低或方案减少外置光源数量，都会让行业放量落不到公司利润上。"
        else:
            operating_sentence = "CPO不是传统可插拔光模块销量的简单倍增，产品形态和单机价值量都在变。新方案能否拿到定点、批量份额并覆盖旧产品替代压力，才决定收入和毛利方向。"
    elif "innovative_drug" in context_roles or "drug_service" in context_roles:
        if "drug_service" in company_roles:
            operating_sentence = "药企授权金额不是服务商收入，服务商只能靠新增项目、在手订单执行和产能利用率赚钱；项目取消、价格竞争和回款变慢，会把行业交易热度吃掉。"
        else:
            operating_sentence = "创新药要拆开首付款、里程碑、销售分成和持续研发费用，交易总额不能一次性当利润。临床成功率、商业化费用和同适应症竞争，决定账面价值最终能留下多少。"
    elif context_roles & {"biofuel_feedstock", "biofuel_production"}:
        if "biofuel_feedstock" in company_roles:
            operating_sentence = "原料端赚的是采购与销售价差，不是SAF销量本身。废弃油脂价格、库存周转、认证追溯和运费一起决定收入增加后还能不能保住利润。"
        else:
            operating_sentence = "生产端看SAF或生物燃料产销量、装置利用率和单位价差。原料上涨快过产品提价，或者工艺收率和认证进度拖后腿，销量增长也可能不增利。"
    elif "供需缺口" in driver:
        operating_sentence = "供需变化先打到报价、排产和库存。公司只有同时拿到销量与价格，且原料和制造成本没有更快上涨，毛利才会真改善；渠道补库造成的短缺通常来得快、退得也快。"
    elif "政策约束" in driver:
        operating_sentence = "政策不直接给公司打钱，能改报表的是准入、采购预算、招投标和项目开工。订单增加但回款周期拉长，利润表好看、经营现金流难看，股价逻辑照样会打折。"
    elif "产能释放" in driver:
        operating_sentence = "扩产只是把可交付上限抬高，不是锁定收入。新增产线能否被订单填满、售价能否覆盖折旧和爬坡费用，决定扩产是放大利润还是制造闲置成本。"
    elif "终端需求" in driver:
        operating_sentence = "需求增长要经过客户采购量、公司份额和产品单价三道关。出货多了但价格战加剧，或低毛利产品占比上升，收入往上走，利润未必跟得上。"
    elif "技术商业化" in driver:
        operating_sentence = "技术新闻先改认证和产品导入速度，不直接改收入。产品定型后还要看订单、交付和良率；研发费用已经花出去、量产迟迟不上来，题材越热，报表落差越大。"
    else:
        operating_sentence = f"对{stock_name}真正有用的变量是{transmission['signals']}。订单、交付、收入确认和回款要能串起来，行业热度才不会只停在盘口。"

    if stage_rank >= 10:
        stage_sentence = f"兑现已经走到{stage_label}，含金量高，接下来要防的是应收、减值或一次性确认让利润质量打折。"
    elif stage_rank >= 8:
        stage_sentence = f"当前线索已到{stage_label}，离报表不远；出货能否按期确认收入、回款能否跟上，比新增题材标签重要。"
    elif stage_rank >= 6:
        stage_sentence = f"现在能确认到{stage_label}，还没走完交付、验收、收入确认和回款，合同含金量要靠执行率说话。"
    elif stage_rank == 5:
        stage_sentence = "目前只到框架协议，框架不等于采购订单，数量、价格和交付时间没落定前，不能拿协议总盘子估收入。"
    elif stage_rank == 4:
        stage_sentence = "线索走到客户定点，说明进入方案，但定点不保证份额；正式订单、单机用量和量产节奏才决定收入。"
    elif stage_rank == 3:
        stage_sentence = "现在只到认证或联合验证，技术可用不等于进入批量供应链，后面还差定点、采购订单和规模交付。"
    elif stage_rank == 2:
        stage_sentence = "当前只到送样，样品过关之前没有供货资格，过关之后也要重新争定点和价格，离收入仍有好几步。"
    elif stage_rank in {0, 1}:
        stage_sentence = f"兑现阶段还在{stage_label}，没有明确订单和收入，短期先反映在研发费用和市场情绪，改不了利润表。"
    elif "供需缺口" in driver:
        stage_sentence = "这是一条行业价格与供需新闻，不代表公司已经新增订单；公司报价、排产和库存没有同步变化，报表就不会跟。"
    elif "政策约束" in driver:
        stage_sentence = "这条线目前停在政策端，细则、招标和项目开工还没落到公司合同之前，不能提前把行业预算算成公司收入。"
    else:
        stage_sentence = "目前没有看到它跨过正式订单、批量交付和收入确认这些门槛，经营影响只能按待验证处理。"

    if relation_label == "错位":
        disproof_sentence = f"最容易证伪的点很直接：{stock_name}拿不出与{event_role_text}同产品、同客户用途的合同或收入科目，这个关联就只能留在板块联动。"
    elif relation_label == "蹭概念":
        disproof_sentence = f"{filled_stars}星在这里不能替代生意。中报、季报里看不到对应产品收入，订单也没有从口头布局往前走，分时图的热度就没有报表接力。"
    elif "semiconductor_equipment" in company_roles:
        disproof_sentence = "晶圆厂资本开支没有转成设备订单，或者设备交付后长期等不到验收，芯片端再热也改不了设备公司的收入和现金回款。"
    elif stage_rank == -1 and "供需缺口" in driver:
        disproof_sentence = "公司报价、排产、产能利用率和毛利没有同步改善，或者库存先堆起来，这条缺货逻辑就更像渠道补库，不是持续景气。"
    elif stage_rank == -1 and "政策约束" in driver:
        disproof_sentence = "政策细则没有带来招标、正式合同和回款，或者项目只开工不结算，行业预算就不能算成公司的经营增量。"
    elif stage_rank <= 3:
        disproof_sentence = "最容易被打脸的是认证、送样或布局迟迟转不成定点和批量订单；相关产品收入没有抬头，题材强度就应主动下修。"
    elif stage_rank <= 6:
        disproof_sentence = "最容易证伪的是协议或订单不转交付，或者交付后应收账款抬得比收入更快，前者说明需求虚，后者说明现金含量差。"
    else:
        disproof_sentence = f"最硬的照妖镜是{transmission['signals']}：这些指标没有在收入、毛利和经营现金流里一起出现，股价讲的就比公司赚的多。"

    if relation_label == "真相关":
        parts = [opening, fact_sentence, revenue_sentence, operating_sentence, stage_sentence, disproof_sentence]
    elif relation_label == "宽口径相关":
        parts = [opening, fact_sentence, revenue_sentence, stage_sentence, operating_sentence, disproof_sentence]
    elif relation_label == "小基数布局":
        parts = [opening, fact_sentence, stage_sentence, revenue_sentence, operating_sentence, disproof_sentence]
    elif relation_label == "错位":
        parts = [opening, revenue_sentence, operating_sentence, stage_sentence, disproof_sentence]
    else:
        parts = [opening, revenue_sentence, stage_sentence, disproof_sentence]

    analysis = clean_text("".join(parts))
    if len(analysis) < 180:
        analysis += "要把这条逻辑坐实，至少需要对应产品、正式订单、收入确认和现金回款中的两项同时出现，单靠板块上涨不能证明公司赚到了钱。"
    if len(analysis) > 540:
        analysis = compact_text(analysis, 540)
    return finalize_investment_analysis(analysis, stock_name)
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
        "schemaVersion": 15,
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
        default=project_root / "prompts" / "investment-opportunity-analyst-v6.md",
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
        "schemaVersion": 15,
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
