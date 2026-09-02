"""焊件切割清单封装的离线契约测试。"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.sw_weldment import (
    SW_END_CONDITION_MITER,
    _body_cut_list_key,
    _body_length_key,
    export_cut_list_csv,
    read_property_manager,
)


class FakePropertyManager:
    """@brief 模拟本地化制造属性与无关标题栏属性。"""

    values = {
        "长度": "205.4",
        "QUANTITY": "2",
        "PROFILE_DESIGNATION": "HSS1x1x16ga",
        "设计": "张三",
    }

    def GetNames(self):
        return tuple(self.values)

    def Get6(self, name, _cached, raw, resolved, was_resolved, linked):
        raw.value = self.values[name]
        resolved.value = self.values[name]
        was_resolved.value = True
        linked.value = name in {"长度", "QUANTITY"}
        return 2


class FakeBody:
    def GetBodyBox(self):
        return (0.0, 0.0, 0.0, 0.0254, 0.2054, 0.0254)


def test_property_reader_keeps_cut_list_fields_and_filters_title_block_noise():
    properties = read_property_manager(FakePropertyManager())
    assert set(properties) == {"长度", "QUANTITY", "PROFILE_DESIGNATION"}
    assert properties["QUANTITY"]["resolved"] == "2"
    assert properties["长度"]["linked"] is True


def test_body_length_group_key_is_micrometre_stable():
    assert _body_length_key(FakeBody()) == 205400
    assert _body_cut_list_key(FakeBody()) == (25400, 25400, 205400)
    assert SW_END_CONDITION_MITER == 1


def test_cut_list_csv_contains_manufacturing_and_traceability_fields(tmp_path):
    evidence = {
        "cut_list_folders": [
            {
                "name": "切割清单项目1",
                "body_count": 2,
                "properties": {
                    "长度": {"resolved": "205.4", "raw": ""},
                    "QUANTITY": {"resolved": "2", "raw": ""},
                    "SOURCE_SKU": {"resolved": "01760", "raw": ""},
                },
            }
        ]
    }
    path = export_cut_list_csv(evidence, tmp_path / "cut-list.csv")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{
        "index": "1",
        "name": "切割清单项目1",
        "body_count": "2",
        "QUANTITY": "2",
        "SOURCE_SKU": "01760",
        "长度": "205.4",
    }]


def test_open_source_case_is_pinned_with_license_and_profile_dimensions():
    payload = json.loads(
        (Path(__file__).parents[1] / "examples" / "weldment" / "coremark_hss1x1x16ga.json").read_text(encoding="utf-8")
    )
    assert payload["source"]["license"] == "MIT"
    assert payload["profile"]["designation"] == "HSS1x1x16ga"
    assert payload["regressionGeometry"]["outer_mm"] == 25.4
