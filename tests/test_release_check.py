from scripts.release_check import run_release_check


def test_release_check_passes_current_tree():
    result = run_release_check()
    assert result["status"] == "pass"
    assert result["capabilities"] >= 10
