"""@brief Masaüstü prototipi için mock yürütücü."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Any, Callable

from .core import now_iso, read_json, write_json


LogCallback = Callable[[str], None]

STAGES = [
    ("preflight", "Ortam öz denetimi"),
    ("build_model", "Model üretimi"),
    ("export_model", "Model dışa aktarma"),
    ("build_drawing", "Çizim üretimi"),
    ("export_drawing", "Çizim dışa aktarma"),
    ("review", "Standart incelemesi"),
    ("package", "Teslimat paketi hazırlama"),
]

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _assert_inside(parent: Path, child: Path) -> None:
    """@brief Özyinelemeli işlem hedefinin proje dizini içinde olmasını sağlar."""
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved not in [child_resolved, *child_resolved.parents]:
        raise RuntimeError(f"Proje dizini dışındaki yol üzerinde işlem reddedildi: {child_resolved}")


def _log(callback: LogCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_parameters(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    """@brief MVP P0 parametre bütünlüğü için makine kontrolü yapar."""
    checks: list[dict[str, Any]] = []

    def add(check_id: str, status: str, target: str, message: str, suggestion: str = "") -> None:
        checks.append(
            {
                "id": check_id,
                "severity": "P0",
                "status": status,
                "target": target,
                "message": message,
                "suggestion": suggestion,
            }
        )

    shell = parameters.get("shell", {})
    for key, label in [
        ("outer_length", "dış uzunluk"),
        ("outer_width", "dış genişlik"),
        ("outer_height", "dış yükseklik"),
        ("wall_thickness", "duvar kalınlığı"),
        ("bottom_thickness", "taban kalınlığı"),
    ]:
        value = shell.get(key)
        if not _is_number(value) or value <= 0:
            add("model-main-dimensions", "fail", "model", f"{label} eksik veya pozitif bir sayı değil", "Kabuğun temel ölçülerini tamamlayın")
    if _is_number(shell.get("wall_thickness")) and shell["wall_thickness"] < 0.8:
        add("print-min-wall", "fail", "printing", "Duvar kalınlığı 0.8 mm katı alt sınırının altında", "Duvar kalınlığını artırın veya özel baskı prosesini doğrulayın")

    features = parameters.get("features", {})
    for group, label in [("holes", "delik"), ("cutouts", "arabirim açıklığı"), ("bosses", "vida bosu")]:
        for item in features.get(group, []):
            item_id = item.get("id") or "numarasız"
            for required in ["id", "face", "quantity", "center_x", "center_y"]:
                if item.get(required) in ("", None):
                    add(
                        f"{group}-position-complete",
                        "fail",
                        "drawing",
                        f"{label} {item_id} için {required} eksik",
                        "Spesifikasyonu, adedi ve X/Y konumlandırmayı tamamlayın; yalnızca kılavuz çizgisi açıklamasına güvenilemez",
                    )
            if group == "holes" and item.get("diameter") in ("", None, 0):
                add("hole-spec-complete", "fail", "drawing", f"Delik {item_id} için çap eksik", "Delik çapını ekleyin")
            if group == "cutouts":
                has_rect = item.get("cutout_width") not in ("", None, 0) and item.get("cutout_height") not in ("", None, 0)
                has_round = item.get("cutout_diameter") not in ("", None, 0)
                if not has_rect and not has_round:
                    add("cutout-spec-complete", "fail", "drawing", f"Arabirim açıklığı {item_id} için ölçü eksik", "Genişlik/yükseklik veya çap ekleyin")
            if group == "bosses":
                for required in ["screw_size", "boss_outer_diameter", "hole_diameter", "boss_height"]:
                    if item.get(required) in ("", None, 0):
                        add("boss-spec-complete", "fail", "drawing", f"Vida bosu {item_id} için {required} eksik", "Vida bosu spesifikasyonunu tamamlayın")

    if not any(check["status"] == "fail" for check in checks):
        checks.extend(
            [
                {
                    "id": "model-cut-through",
                    "severity": "P0",
                    "status": "pass",
                    "target": "model",
                    "message": "Parametre tablosu, delik ve kanalların gerçek kesimi için gereken spesifikasyon ve konumlandırmayı içeriyor",
                    "suggestion": "",
                },
                {
                    "id": "drawing-hole-position",
                    "severity": "P0",
                    "status": "pass",
                    "target": "drawing",
                    "message": "Delikler, arabirim açıklıkları ve vida bosları spesifikasyon, adet ve konumlandırma alanlarına sahip",
                    "suggestion": "",
                },
                {
                    "id": "drawing-frame-title",
                    "severity": "P0",
                    "status": "pass",
                    "target": "drawing",
                    "message": "GB/T tarzı çizim çerçevesi, antet, birim ve ölçek seçildi",
                    "suggestion": "",
                },
            ]
        )
    return checks


def run_mock(project_dir: Path, callback: LogCallback | None = None) -> dict[str, Any]:
    """@brief Mock teslimat paketi ve nihai inceleme raporu üretir."""
    project_dir = Path(project_dir)
    project = read_json(project_dir / "project.json")
    parameters = read_json(project_dir / "parameters.json")
    checks = validate_parameters(parameters)
    failed = any(item["status"] == "fail" for item in checks)

    for _, label in STAGES:
        _log(callback, f"{label} ...")

    name = project.get("project_name", "project")
    stem = Path(name).stem or "project"
    model_dir = project_dir / "outputs" / "model"
    drawing_dir = project_dir / "outputs" / "drawing"
    package_dir = project_dir / "outputs" / "package"
    reviews_dir = project_dir / "reviews"
    previews_dir = project_dir / "previews"

    outputs = {
        "sldprt": model_dir / f"{stem}.sldprt",
        "step": model_dir / f"{stem}.step",
        "stl": model_dir / f"{stem}.stl",
        "dwg": drawing_dir / f"{stem}.dwg",
        "dxf": drawing_dir / f"{stem}.dxf",
        "pdf": drawing_dir / f"{stem}.pdf",
        "preview": previews_dir / "drawing_preview.png",
    }

    if not failed:
        outputs["sldprt"].write_text("MOCK SLDPRT PLACEHOLDER - sonraki sürümlerde SolidWorks COM tarafından üretilecek.\n", encoding="utf-8")
        outputs["step"].write_text("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('MOCK STEP'),'1');\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
        outputs["stl"].write_text("solid mock_shell\nendsolid mock_shell\n", encoding="utf-8")
        outputs["dwg"].write_text("MOCK DWG PLACEHOLDER - sonraki sürümlerde AutoCAD COM tarafından üretilecek.\n", encoding="utf-8")
        outputs["dxf"].write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")
        outputs["pdf"].write_text("MOCK PDF PLACEHOLDER - sonraki sürümlerde gerçek PDF dışa aktarılacak.\n", encoding="utf-8")
        outputs["preview"].write_bytes(PNG_1X1)
        (previews_dir / "model_iso.png").write_bytes(PNG_1X1)
        (previews_dir / "package_cover.png").write_bytes(PNG_1X1)

    model_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "Şu an mock model incelemesi yapılıyor; gerçek geometri kontrolü SolidWorks entegrasyonundan sonra etkinleşecek.",
    }
    drawing_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "Şu an mock çizim incelemesi yapılıyor; gerçek DWG ölçü nesneleri ve görsel kontrol AutoCAD entegrasyonundan sonra etkinleşecek.",
    }
    print_review = {
        "schema_version": "0.1",
        "status": "warning" if not failed else "fail",
        "checked_at": now_iso(),
        "message": "Parametre düzeyinde 3D baskı katı kural kontrolü yürütüldü.",
    }
    write_json(reviews_dir / "model_review.json", model_review)
    write_json(reviews_dir / "drawing_review.json", drawing_review)
    write_json(reviews_dir / "printability_review.json", print_review)

    final_review = {
        "schema_version": "0.1",
        "overall_status": "fail" if failed else "warning",
        "project_id": project.get("project_id"),
        "checked_at": now_iso(),
        "checks": checks
        + [
            {
                "id": "mock-runner-not-real-cad",
                "severity": "P1",
                "status": "warning",
                "target": "package",
                "message": "Bu, masaüstü prototipinin mock yürütmesidir; CAD dosyaları yer tutucudur ve imalatta kullanılamaz.",
                "suggestion": "SolidWorks/AutoCAD entegrasyonundan sonra teslim edilebilir duruma geçirin",
            }
        ],
        "outputs": {key: str(path.relative_to(project_dir)) for key, path in outputs.items()},
    }
    write_json(reviews_dir / "final_review.json", final_review)

    manifest = {
        "schema_version": "0.1",
        "generated_at": now_iso(),
        "project_name": project.get("project_name", "CAD projesi"),
        "status": final_review["overall_status"],
        "files": [
            {"kind": key, "path": str(path.relative_to(project_dir)), "exists": path.exists()}
            for key, path in outputs.items()
        ]
        + [
            {"kind": "review", "path": "reviews/final_review.json", "exists": True},
            {"kind": "source", "path": "parameters.json", "exists": True},
            {"kind": "source", "path": "project.json", "exists": True},
        ],
    }
    write_json(project_dir / "outputs" / "manifest.json", manifest)

    readme = project_dir / "README_teslimat_notlari.md"
    readme.write_text(
        "\n".join(
            [
                f"# {project.get('project_name', 'CAD projesi')} teslimat notları",
                "",
                "- Birim: mm",
                "- Çizim tarzı: GB/T tarzı",
                "- Geçerli durum: mock prototip çıktısı; doğrudan imalatta kullanılamaz",
                "- İnceleme raporu: reviews/final_review.json",
                "- Sonraki adım: SolidWorks/AutoCAD entegrasyonundan sonra gerçek SLDPRT/STEP/STL/DWG/DXF/PDF çıktısı",
                "",
            ]
        ),
        encoding="utf-8",
    )

    delivery = package_dir / f"{stem}_delivery"
    if delivery.exists():
        _assert_inside(project_dir, delivery)
        shutil.rmtree(delivery)
    delivery.mkdir(parents=True)
    for rel in ["project.json", "parameters.json", "README_teslimat_notlari.md", "outputs/manifest.json"]:
        shutil.copy2(project_dir / rel, delivery / Path(rel).name)
    shutil.copytree(reviews_dir, delivery / "reviews")

    project["updated_at"] = now_iso()
    project["status"] = final_review["overall_status"]
    write_json(project_dir / "project.json", project)
    _log(callback, f"Mock teslimat dizini oluşturuldu: {delivery}")
    return final_review
