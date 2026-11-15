"""wallstreet_kit v2 的契约测试:镜头表校验规则、film.js 生成、场景白名单。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "motion_design"
sys.path.insert(0, str(TOOLS))

import wallstreet_kit as wk  # noqa: E402

LINES = [
    {"id": "b01", "text": "表格里蹲了只小黄鸭。", "say": "表格里蹲了只小黄鸭。", "gap": 0.25},
    {"id": "b02", "text": "微软收跌百分之二点二，市值蒸发 893 亿美元。", "say": "同文", "gap": 0.25},
    {"id": "b03", "text": "AI 省下的时间，是你的下班时间。", "say": "同文", "gap": 0.25},
]


class KitTests(unittest.TestCase):
    def test_scene_catalog_has_no_photo_scenes(self):
        banned = {"person", "profile", "quote", "footage", "montage", "frames",
                  "desk", "article", "device", "pop", "cards3d", "flash"}
        self.assertEqual(banned & wk.ALLOWED_SCENES, set())

    def test_valid_shots_pass(self):
        shots = [
            {"scene": "statement", "until": "@b02", "says": "钩子",
             "lines": ["表格里", "蹲了只小黄鸭"], "hl": ["小黄鸭"],
             "at": ["@b01:表格里", "@b01:小黄鸭"]},
            {"scene": "number", "until": "@b03", "says": "微软蒸发的市值", "value": "$893亿",
             "color": "red", "tone": "wine", "brow": "微软 · 市值蒸发",
             "sub": {"label": "微软收跌", "value": "−2.2%", "at": "@b02:百分之二点二"}},
            {"scene": "statement", "says": "结尾",
             "lines": ["AI 省下的时间"], "hl": [], "at": ["@b03:省下"]},
        ]
        self.assertEqual(wk.validate_shots(shots, LINES), [])

    def test_photo_scene_rejected(self):
        shots = [{"scene": "footage", "until": "@b02", "says": "x", "img": "a.jpg"},
                 {"scene": "number", "says": "x", "value": "893"},
                 {"scene": "statement", "says": "x", "lines": ["结尾"]}]
        errs = wk.validate_shots(shots, LINES)
        self.assertTrue(any("禁止使用" in e for e in errs))

    def test_cue_word_must_exist(self):
        shots = [
            {"scene": "number", "until": "@b01:不存在的词", "says": "x", "value": "893"},
            {"scene": "number", "until": "@b02", "says": "x", "value": "893"},
            {"scene": "statement", "says": "x", "lines": ["结尾"]},
        ]
        errs = wk.validate_shots(shots, LINES)
        self.assertTrue(any("不在 b01" in e for e in errs))

    def test_fabricated_number_rejected(self):
        shots = [
            {"scene": "number", "until": "@b02", "says": "x", "value": "$9999亿"},
            {"scene": "number", "until": "@b03", "says": "x", "value": "893"},
            {"scene": "statement", "says": "x", "lines": ["结尾"]},
        ]
        errs = wk.validate_shots(shots, LINES)
        self.assertTrue(any("找不到对应数字" in e for e in errs))

    def test_statement_limits(self):
        shots = [
            {"scene": "statement", "until": "@b02", "says": "x",
             "lines": ["这一行超过十二个字就会被拦下来"], "hl": []},
            {"scene": "statement", "until": "@b02", "says": "x", "lines": ["第二句"]},
            {"scene": "statement", "until": "@b03", "says": "x", "lines": ["第三句"]},
            {"scene": "statement", "says": "x", "lines": ["第四句"]},
        ]
        errs = wk.validate_shots(shots, LINES)
        self.assertTrue(any("12 字" in e for e in errs))
        self.assertTrue(any("超过 3" in e for e in errs))

    def test_non_last_shot_needs_until(self):
        shots = [
            {"scene": "number", "says": "x", "value": "893"},
            {"scene": "number", "until": "@b03", "says": "x", "value": "893"},
            {"scene": "statement", "says": "x", "lines": ["结尾"]},
        ]
        errs = wk.validate_shots(shots, LINES)
        self.assertTrue(any("必须写 until" in e for e in errs))

    def test_film_js_registers_and_goes(self):
        js = wk.build_film_js([{"scene": "number", "says": "x", "value": "1"}])
        self.assertIn("await K.film(", js)
        self.assertIn("return K.go();", js)
        self.assertIn('"says": "x"', js)

    def test_skill_available_on_this_machine(self):
        ok, why = wk.available()
        self.assertTrue(ok, why)


if __name__ == "__main__":
    unittest.main()
