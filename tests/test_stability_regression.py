from scripts.stability_regression import run_regression


def test_twenty_lifecycle_iterations_have_no_orphans():
    result = run_regression(20)
    assert result["status"] == "pass"
    assert result["iterations"] == 20
    assert result["unique_processes"] == 20
    assert result["orphan_process"] is False
