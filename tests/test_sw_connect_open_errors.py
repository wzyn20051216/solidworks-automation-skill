"""sw_connect 打开错误分类与异常类型无 COM 测试。"""
from __future__ import annotations

from scripts.sw_connect import (
    SolidWorksDocumentOpenError,
    classify_sw_file_load_errors,
)


def test_known_codes_map_to_enum_names():
    assert classify_sw_file_load_errors(0) == "无"
    assert classify_sw_file_load_errors(2097152) == "swFileRequiresRepairError"
    assert classify_sw_file_load_errors(65536) == "swFileWithSameTitleAlreadyOpen"
    assert classify_sw_file_load_errors(1024) == "swInvalidFileTypeError"


def test_bit_combined_codes_split_into_parts():
    assert classify_sw_file_load_errors(65536 | 2) == "swFileWithSameTitleAlreadyOpen | swFileNotFoundError"


def test_unknown_bits_are_kept_in_hex():
    text = classify_sw_file_load_errors(1 | (1 << 27))
    assert "swGenericError" in text
    assert "0x8000000" in text


def test_non_numeric_input_is_tolerated():
    assert classify_sw_file_load_errors(None) == "无"
    assert classify_sw_file_load_errors("not-a-number") == "未知"


def test_document_open_error_carries_code():
    exc = SolidWorksDocumentOpenError("打开失败", error_code=2097152)
    assert isinstance(exc, RuntimeError)
    assert exc.error_code == 2097152
    assert "打开失败" in str(exc)


def test_document_open_error_defaults_to_zero():
    assert SolidWorksDocumentOpenError("x").error_code == 0


def test_error_table_entries_are_unique_bit_flags():
    from scripts.sw_connect import SW_FILE_LOAD_ERRORS

    keys = list(SW_FILE_LOAD_ERRORS)
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert key > 0 and (key & (key - 1)) == 0, f"swFileLoadError_e 必须是位标志(2 的幂): {key}"


def test_error_table_matches_swconst_typelib_values():
    """与 SW2024 SP5 swconst.tlb 的 swFileLoadError_e 实测值对齐。"""
    from scripts.sw_connect import SW_FILE_LOAD_ERRORS

    expected = {
        1: "swGenericError",
        2: "swFileNotFoundError",
        8: "swReadOnlyWarn",
        8192: "swFutureVersion",
        65536: "swFileWithSameTitleAlreadyOpen",
        2097152: "swFileRequiresRepairError",
        8388608: "swApplicationBusy",
    }
    for value, prefix in expected.items():
        assert SW_FILE_LOAD_ERRORS[value].startswith(prefix), value
