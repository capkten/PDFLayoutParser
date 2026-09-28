"""
Sprint 1 比较器负例单元测试 (Negative Cases & Invariant Verification)。
测试比较器在遇到伪造 Provenance、隐藏文本状态不符、渲染模式失配等违规输入时，
能否如实判定为门禁失败，绝不产生假绿灯。
"""

import unittest
import copy
from compare_synthetic_diff import compare_spans

class TestComparatorNegativeCases(unittest.TestCase):

    def setUp(self):
        self.valid_base_span = {
            "order": 0,
            "text": "Hello",
            "bbox": [10.0, 10.0, 50.0, 20.0],
            "font": "TestFont",
            "size": 10.0,
            "is_invisible": False,
            "render_mode": 0,
            "characters": [
                {"c": "H", "bbox": [10.0, 10.0, 18.0, 20.0]},
                {"c": "e", "bbox": [18.0, 10.0, 26.0, 20.0]},
                {"c": "l", "bbox": [26.0, 10.0, 34.0, 20.0]},
                {"c": "l", "bbox": [34.0, 10.0, 42.0, 20.0]},
                {"c": "o", "bbox": [42.0, 10.0, 50.0, 20.0]},
            ]
        }

        self.valid_probe_span = {
            "order": 0,
            "text": "Hello",
            "bbox": [10.0, 10.0, 50.0, 20.0],
            "font": "TestFont",
            "size": 10.0,
            "is_invisible": False,
            "render_mode": 0,
            "provenance": {
                "page_index": 0,
                "pdfium_object_index": 1,
                "character_count": 5,
                "char_start_index": 0,
                "char_end_index": 5,
                "char_indices": [0, 1, 2, 3, 4],
                "is_derived": False,
                "derived_block": None,
                "derived_line": None,
            },
            "characters": [
                {"c": "H", "bbox": [10.0, 10.0, 18.0, 20.0], "char_index": 0},
                {"c": "e", "bbox": [18.0, 10.0, 26.0, 20.0], "char_index": 1},
                {"c": "l", "bbox": [26.0, 10.0, 34.0, 20.0], "char_index": 2},
                {"c": "l", "bbox": [34.0, 10.0, 42.0, 20.0], "char_index": 3},
                {"c": "o", "bbox": [42.0, 10.0, 50.0, 20.0], "char_index": 4},
            ]
        }

    def test_positive_match(self):
        """基准与探针完全合法合规时，判定为 MATCHED"""
        res = compare_spans([self.valid_base_span], [self.valid_probe_span], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 1)
        self.assertEqual(res["details"][0]["status"], "MATCHED")

    def test_negative_invisible_mismatch(self):
        """负例：探针标记为不可见，而基准为可见，必须拦截为 INVISIBLE_MISMATCH"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["is_invisible"] = True
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "INVISIBLE_MISMATCH")

    def test_negative_render_mode_mismatch(self):
        """负例：双方均有确切数值但 render_mode 不一致，必须拦截为 RENDER_MODE_MISMATCH"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["render_mode"] = 3 # Invisible
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "RENDER_MODE_MISMATCH")

    def test_render_mode_uncomparable_when_one_side_none(self):
        """当基准 render_mode 为 None 时，不伪造匹配，记录为不可比"""
        base = copy.deepcopy(self.valid_base_span)
        base["render_mode"] = None
        probe = copy.deepcopy(self.valid_probe_span)
        probe["render_mode"] = 0
        res = compare_spans([base], [probe], bbox_tol=0.5, page_index=0)
        self.assertFalse(res["details"][0]["render_mode_comparable"])
        self.assertEqual(res["details"][0]["status"], "MATCHED") # 其余项完全达标

    def test_negative_provenance_char_range_inverted(self):
        """负例：Provenance char_end_index < char_start_index，必须拦截为 PROVENANCE_INVALID"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["char_start_index"] = 5
        probe["provenance"]["char_end_index"] = 2
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("char_end_index" in v for v in res["details"][0]["prov_violations"]))

    def test_negative_provenance_length_mismatch(self):
        """负例：Provenance 范围跨度与 character_count 不相等，必须拦截"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["character_count"] = 10 # 虚报
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("span_length" in v for v in res["details"][0]["prov_violations"]))

    def test_negative_provenance_indices_not_contiguous(self):
        """负例：Provenance char_indices 不连续，必须拦截"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["char_indices"] = [0, 1, 3, 4, 5] # 跳过 2
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("not_contiguous" in v for v in res["details"][0]["prov_violations"]))

    def test_negative_provenance_page_mismatch(self):
        """负例：Provenance 记录的 page_index 与实际比较页面不符，必须拦截"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["page_index"] = 99 # 错位
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("provenance_page_index" in v for v in res["details"][0]["prov_violations"]))

    def test_negative_false_green_char_count_mismatch(self):
        """测试用户指出的假绿反例：两字符基线 ['a','b'] vs 单字符探针 ['ab']，必须拦截为 CHAR_MISMATCH"""
        base = {
            "order": 0,
            "text": "ab",
            "bbox": [10.0, 10.0, 30.0, 20.0],
            "font": "TestFont",
            "size": 10.0,
            "is_invisible": False,
            "render_mode": 0,
            "characters": [
                {"c": "a", "bbox": [10.0, 10.0, 20.0, 20.0]},
                {"c": "b", "bbox": [20.0, 10.0, 30.0, 20.0]},
            ]
        }
        probe = {
            "order": 0,
            "text": "ab",
            "bbox": [10.0, 10.0, 30.0, 20.0],
            "font": "TestFont",
            "size": 10.0,
            "is_invisible": False,
            "render_mode": 0,
            "provenance": {
                "page_index": 0,
                "pdfium_object_index": 1,
                "character_count": 1,
                "char_start_index": 0,
                "char_end_index": 1,
                "char_indices": [0],
                "is_derived": False,
                "derived_block": None,
                "derived_line": None,
            },
            "characters": [
                {"c": "ab", "bbox": [10.0, 10.0, 30.0, 20.0], "char_index": 0},
            ]
        }
        res = compare_spans([base], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "CHAR_MISMATCH")

    def test_negative_false_green_char_bbox_exceeded(self):
        """负例：字符文本全同但单个字符 BBox 误差超标，必须拦截为 CHAR_MISMATCH"""
        probe = copy.deepcopy(self.valid_probe_span)
        # 将第 0 个字符 BBox 偏移 2.0 pt (超过 0.5 pt 阈值)
        probe["characters"][0]["bbox"] = [12.0, 10.0, 20.0, 20.0]
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "CHAR_MISMATCH")

    def test_negative_provenance_falsely_claimed_derived(self):
        """负例：原生探针如果冒充 is_derived: true，必须拦截"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["is_derived"] = True
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("is_derived_must_be_false" in v for v in res["details"][0]["prov_violations"]))

    def test_negative_provenance_text_length_mismatch(self):
        """负例：text 长度与 provenance.character_count 不一致，必须拦截为 PROVENANCE_INVALID"""
        probe = copy.deepcopy(self.valid_probe_span)
        probe["provenance"]["character_count"] = 4 # 原 text 为 "Hello" (5)，篡改为 4
        res = compare_spans([self.valid_base_span], [probe], bbox_tol=0.5, page_index=0)
        self.assertEqual(res["fully_accepted_count"], 0)
        self.assertEqual(res["details"][0]["status"], "PROVENANCE_INVALID")
        self.assertTrue(any("text_length" in v for v in res["details"][0]["prov_violations"]))

if __name__ == "__main__":
    unittest.main()
