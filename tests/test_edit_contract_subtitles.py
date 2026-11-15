"""剪辑契约的字幕轨:结构校验、时长边界、排序。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "motion_design"
sys.path.insert(0, str(TOOLS))

from edit_contract import normalize_subtitles, validate  # noqa: E402

DOC = {
    "version": "edit_decisions_v2",
    "stage": "edit",
    "render_runtime": "ffmpeg:editmode",
    "title": "t",
    "output": {"width": 1080, "height": 1920, "fps": 30},
    "cuts": [
        {"source": "a.mp4", "source_in": 0.0, "source_out": 3.0,
         "speed": 1.0, "layer": 0, "transition_in": {"type": "硬切", "duration": 0}},
        {"source": "a.mp4", "source_in": 3.0, "source_out": 6.0,
         "speed": 1.0, "layer": 0, "transition_in": {"type": "硬切", "duration": 0}},
    ],
}


class SubtitleTests(unittest.TestCase):
    def test_valid_sorted(self):
        subs = normalize_subtitles(
            [{"start": 2.0, "end": 4.0, "text": "第二句"},
             {"start": 0.0, "end": 1.9, "text": "第一句"}], total=6.0)
        self.assertEqual([s["text"] for s in subs], ["第一句", "第二句"])

    def test_empty_ok(self):
        self.assertEqual(normalize_subtitles(None, 6.0), [])
        self.assertEqual(normalize_subtitles([], 6.0), [])

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subtitles([{"start": 0, "end": 1, "text": "  "}], 6.0)

    def test_too_long_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subtitles([{"start": 0, "end": 1, "text": "字" * 41}], 6.0)

    def test_too_short_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subtitles([{"start": 0, "end": 0.2, "text": "闪一下"}], 6.0)

    def test_beyond_total_rejected(self):
        with self.assertRaises(ValueError):
            normalize_subtitles([{"start": 0, "end": 6.5, "text": "超出"}], 6.0)

    def test_validate_carries_subtitles(self):
        doc = dict(DOC, subtitles=[{"start": 0.5, "end": 2.0, "text": "开场字幕"}])
        norm, total = validate(doc)
        self.assertEqual(norm["subtitles"][0]["text"], "开场字幕")
        self.assertEqual(total, 6.0)

    def test_validate_blank_doc_has_empty_track(self):
        norm, _ = validate(dict(DOC))
        self.assertEqual(norm["subtitles"], [])


if __name__ == "__main__":
    unittest.main()
