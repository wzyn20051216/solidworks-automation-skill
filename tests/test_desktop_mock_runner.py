from pathlib import Path

from apps.desktop.cad_workbench.core import create_project, read_json, write_json
from apps.desktop.cad_workbench.mock_runner import run_mock, validate_parameters


def test_mock_runner_creates_review_and_delivery(tmp_path: Path) -> None:
    project_dir, _, _ = create_project("demo_shell", tmp_path)

    review = run_mock(project_dir)

    assert review["overall_status"] == "warning"
    assert (project_dir / "reviews" / "final_review.json").exists()
    assert (project_dir / "outputs" / "manifest.json").exists()
    assert (project_dir / "outputs" / "package" / "demo_shell_delivery").exists()
    assert (project_dir / "outputs" / "package" / "demo_shell_delivery" / "manifest.json").exists()


def test_validate_parameters_fails_missing_hole_position(tmp_path: Path) -> None:
    project_dir, _, params = create_project("bad_shell", tmp_path)
    params["features"]["holes"][0]["center_x"] = ""
    write_json(project_dir / "parameters.json", params)

    checks = validate_parameters(read_json(project_dir / "parameters.json"))

    assert any(check["status"] == "fail" for check in checks)
