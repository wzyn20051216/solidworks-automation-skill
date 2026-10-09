"""@brief 原始文件位码、警告语义与 Core 分类一致性。"""
from scripts.sw_file_load import SolidWorksDocumentOpenError, classify_sw_file_load_errors, classify_sw_file_load_warnings
from scripts.core.recovery import classify_error, ErrorKind


def test_warning_two_is_readonly_not_file_not_found():
    assert classify_sw_file_load_warnings(2) == "swFileLoadWarning_ReadOnly"
    assert classify_sw_file_load_errors(2) == "swFileNotFoundError"
    assert "swDrawingSFSymbolConvertWarn" in classify_sw_file_load_errors(32768)


def test_combined_and_unknown_bits_remain_visible():
    text = classify_sw_file_load_errors(2 | 2097152 | 33554432)
    assert "swFileNotFoundError" in text and "swFileRequiresRepairError" in text and "0x2000000" in text


def test_corrupt_file_preserves_original_bits_and_recovery_action():
    error = SolidWorksDocumentOpenError("fixture", 2097152, 2)
    assert error.error_code == 2097152 and error.warnings == 2
    assert error.code == "SW_FILE_REQUIRES_REPAIR"
    assert classify_error(exception=error) == ErrorKind.USER_ACTION_REQUIRED
