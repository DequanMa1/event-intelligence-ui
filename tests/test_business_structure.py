import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from business_structure import describe_business_structure, refined_revenue_matches, revenue_structure


def segments(*rows):
    return [{"name": name, "sharePct": share} for name, share in rows]


class BusinessStructureTests(unittest.TestCase):
    def describe(self, rows, product, profile=""):
        direct, contained = refined_revenue_matches(rows, product) or ([], [])
        return describe_business_structure(
            company_product=product, target_name="光通信设备",
            company_evidence={"revenueSegments": rows, "companyProfile": profile},
            direct_segments=direct, contained_segments=contained,
        )

    def test_small_product_is_compared_with_dominant_business(self):
        rows = segments(("电子电路", 63.85), ("触控面板及LCM模组", 14.92),
                        ("精密组件", 14.78), ("光模块", 3.58), ("其他", 2.87))
        text = self.describe(rows, "光模块")
        self.assertIn("3.58%", text)
        self.assertIn("63.85%", text)
        self.assertIn("较小", text)
        self.assertNotIn("主营支柱", text)

    def test_uco_uses_oil_processing_before_environmental_bucket(self):
        rows = segments(("油脂产品加工和销售", 51.33), ("环保无害化处理", 25.37),
                        ("供暖收入", 21.56), ("节能环保装备与配套工程", 1.39), ("其他", .36))
        direct, contained = refined_revenue_matches(rows, "再生废弃食用油脂(UCO)")
        self.assertEqual([s["name"] for s in contained], ["油脂产品加工和销售"])
        text = self.describe(rows, "再生废弃食用油脂(UCO)", "餐厨废弃物资源化处理")
        self.assertIn("51.33%", text)
        self.assertIn("原料回收与加工利用", text)

    def test_parallel_equipment_businesses_keep_parent_denominator(self):
        rows = segments(("光电子及半导体封测设备", 46.23), ("光伏设备及整体解决方案", 45.59), ("其他", 8.17))
        text = self.describe(rows, "光子器件集成耦合设备", "自动化装备和制造软件")
        self.assertIn("规模接近", text)
        self.assertIn("45.59%", text)
        self.assertNotIn("耦合设备占主营收入46.23%", text)

    def test_ambiguous_denominators_do_not_get_combined_or_ranked(self):
        rows = segments(("光模块", 80), ("国内", 60), ("海外", 40))
        mix = revenue_structure(rows, [rows[0]], [])
        self.assertFalse(mix["comparable"])
        text = self.describe(rows, "光模块")
        self.assertNotIn("超过其他业务合计", text)
        self.assertNotIn("规模接近", text)

    def test_deduplicate_segments_and_reject_nonfinite_percentages(self):
        rows = segments(("光模块", 80), ("光模块", 80), ("其他", 20), ("坏值", float("nan")))
        mix = revenue_structure(rows, [rows[0]], [])
        self.assertFalse(mix["comparable"])
        self.assertEqual(mix["total"], 100)

    def test_no_match_does_not_assign_product_to_largest_segment(self):
        rows = segments(("供暖", 80), ("其他", 20))
        text = self.describe(rows, "光模块")
        self.assertNotIn("光模块是供暖", text)
        self.assertNotIn("光模块属于", text)

    def test_exact_half_is_not_more_than_half(self):
        text = self.describe(segments(("光模块", 50), ("供暖", 50)), "光模块")
        self.assertIn("一半", text)
        self.assertNotIn("超过", text)

    def test_cached_ontology_has_same_results_and_no_shared_mutation(self):
        import build_event_impact_chains as generator
        for value in ("光通讯收发模块", "餐厨废弃油脂", "IGBT半导体功率器件", "测试设备", "", "未知业务"):
            normalized = generator.normalize_text(value)
            expected = {tag for tag, keys in generator.BUSINESS_SEMANTIC_GROUPS.items()
                        if normalized and any(generator.normalize_text(k) in normalized for k in keys)}
            actual = generator.semantic_business_tags(value)
            self.assertEqual(actual, expected)
            actual.clear()
            self.assertEqual(generator.semantic_business_tags(value), expected)

    def test_pluggable_optical_module_is_not_a_production_tool_or_cpo(self):
        import build_event_impact_chains as generator
        text = generator.describe_core_product_relation(
            "production_support", "含DSP可插拔光模块(DPO)", "Lightning连接器", "连接器", ("test",))
        self.assertIn("电信号", text)
        self.assertNotIn("设备或工程条件", text)
        self.assertNotIn("CPO", text)

    def test_profile_slogans_do_not_become_operating_facts(self):
        import build_event_impact_chains as generator
        self.assertEqual(generator.prepared_profile_relation_clauses(
            "未来，公司将加速推动智能制造向更高水平迈进，通过技术赋能推动产业链升级。"), ())


if __name__ == "__main__":
    unittest.main()
