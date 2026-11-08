"""@brief Artifact Ledger tabanlı teslimat inceleme kapısı."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .agent_contracts import safe_job_id
from .artifact_ledger import DELIVERY_FILE_EXTENSIONS, artifact_requires_current_run_proof
from .core import now_iso

KNOWN_FORMAT_EXTENSIONS = DELIVERY_FILE_EXTENSIONS
DIMENSION_TRIPLE_PATTERN = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米|milimetre)?",
    re.IGNORECASE,
)
DIAMETER_PATTERN = re.compile(r"(?:直径|孔径|çap[ıi]?|[Ø⌀Φφ])\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米|milimetre)?", re.IGNORECASE)


def review_dir(queue_dir: Path) -> Path:
    """@brief Reviewer Gate rapor dizinini döndürür."""
    directory = Path(queue_dir) / "reviews"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def review_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief Belirtilen görevin Reviewer Gate rapor yolunu döndürür."""
    return review_dir(queue_dir) / f"{safe_job_id(job_id)}.review.json"


def _read_file_sample(path: Path, limit: int = 1024 * 1024) -> bytes:
    """@brief Dosyanın baş kısmından örnek okur; biçim kontrolü için çok büyük CAD dosyalarının yüklenmesini önler."""
    with Path(path).open("rb") as handle:
        return handle.read(limit)


def _artifact_extension(kind: str, path: Path) -> str:
    """@brief Yol uzantısından veya kind değerinden teslimat biçimini çıkarır."""
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    normalized = kind.lower().lstrip(".")
    return f".{normalized}" if f".{normalized}" in KNOWN_FORMAT_EXTENSIONS else ""


def _text_sample(sample: bytes) -> str:
    """@brief İkili örneği esnek biçimde metne dönüştürür; STEP/DXF/STL metin özelliği kontrolü için kullanılır."""
    return sample.decode("utf-8", errors="ignore").upper()


def validate_known_format(kind: str, path: Path) -> dict[str, Any] | None:
    """@brief Yaygın CAD teslimat biçimleri için hafif açılabilirlik/biçim özelliği kontrolü yapar."""
    extension = _artifact_extension(kind, path)
    if extension not in KNOWN_FORMAT_EXTENSIONS:
        return None

    sample = _read_file_sample(path)
    text = _text_sample(sample)
    check_id = f"artifact-format-{kind}"

    if extension in {".step", ".stp"}:
        valid = "ISO-10303-21" in text and "END-ISO-10303-21" in text
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"STEP dosyası ISO-10303-21 yapı işaretini {'içeriyor' if valid else 'içermiyor'}: {path}",
        }

    if extension == ".stl":
        ascii_valid = text.lstrip().startswith("SOLID") and "ENDSOLID" in text
        binary_valid = len(sample) >= 84 and not text.lstrip().startswith("SOLID")
        valid = ascii_valid or binary_valid
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"STL dosyasında tanınabilir ASCII/Binary yapısı {'var' if valid else 'yok'}: {path}",
        }

    if extension == ".dxf":
        valid = "SECTION" in text and text.rstrip().endswith("EOF")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"DXF dosyası SECTION/EOF yapı işaretlerini {'içeriyor' if valid else 'içermiyor'}: {path}",
        }

    if extension == ".pdf":
        valid = sample.startswith(b"%PDF-")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"PDF dosyası %PDF başlığını {'içeriyor' if valid else 'içermiyor'}: {path}",
        }

    if extension == ".dwg":
        valid = sample.startswith(b"AC10")
        return {
            "id": check_id,
            "severity": "P0",
            "status": "pass" if valid else "fail",
            "message": f"DWG dosyası AutoCAD AC10 sürüm başlığını {'içeriyor' if valid else 'içermiyor'}: {path}",
        }

    if extension in {".sldprt", ".sldasm", ".slddrw"}:
        label = {
            ".sldprt": "SLDPRT",
            ".sldasm": "SLDASM",
            ".slddrw": "SLDDRW",
        }[extension]
        return {
            "id": check_id,
            "severity": "P1",
            "status": "warning",
            "message": f"{label} özel bir biçimdir; şu an yalnızca dosya düzeyinde kayıt yapıldı, daha sonra SolidWorks ile açılıp incelenmesi gerekir: {path}",
        }

    return None


def _close_measurement(left: float, right: float, tolerance: float = 1e-6) -> bool:
    """@brief Mekanik spesifikasyon değerlerini karşılaştırır; geçerli görevler tutarlı olarak mm cinsinden kaydedilir."""
    return abs(left - right) <= tolerance


def _same_envelope(left: tuple[float, float, float], right: tuple[float, float, float]) -> bool:
    """@brief Model koordinat ekseni yönünü yok sayarak dış sınır kutusu ölçülerini karşılaştırır."""
    return all(
        _close_measurement(left_value, right_value)
        for left_value, right_value in zip(sorted(left), sorted(right))
    )


def _unique_triplets(values: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """@brief Görev açıklamasında yinelenen üçlü ölçüleri ayıklar."""
    unique: list[tuple[float, float, float]] = []
    for value in values:
        if not any(_same_envelope(value, existing) for existing in unique):
            unique.append(value)
    return unique


def _dimension_triplets(text: str) -> list[tuple[float, float, float]]:
    """@brief Doğal dilden L x W x H/kalınlık üçlü ölçülerini çıkarır."""
    return [tuple(float(value) for value in match) for match in DIMENSION_TRIPLE_PATTERN.findall(text)]


def _diameters(text: str) -> list[float]:
    """@brief Doğal dilden açıkça belirtilmiş delik çaplarını çıkarır."""
    return [float(value) for value in DIAMETER_PATTERN.findall(text)]


def _json_measurements(value: Any) -> tuple[list[tuple[float, float, float]], list[float]]:
    """@brief Kabul JSON'undaki dış üçlü ölçü ve delik çapı kanıtlarını özyinelemeli okur."""
    triplets: list[tuple[float, float, float]] = []
    diameters: list[float] = []

    def visit(item: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(item, dict):
            normalized = {str(key).lower().replace("-", "_").replace(" ", "_"): child for key, child in item.items()}
            length = normalized.get("length", normalized.get("length_mm"))
            width = normalized.get("width", normalized.get("width_mm"))
            thickness = normalized.get(
                "thickness",
                normalized.get("thickness_mm", normalized.get("height", normalized.get("height_mm"))),
            )
            if not all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in (length, width, thickness)):
                length = normalized.get("size_x", normalized.get("size_x_mm", length))
                width = normalized.get("size_y", normalized.get("size_y_mm", width))
                thickness = normalized.get("size_z", normalized.get("size_z_mm", thickness))
            if all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in (length, width, thickness)):
                triplets.append((float(length), float(width), float(thickness)))
            for key, child in normalized.items():
                is_hole_evidence = (
                    key.startswith("hole_")
                    or any(segment in {"hole", "holes", "delik", "delikler", "孔", "孔洞"} for segment in path)
                    or normalized.get("internal") is True
                )
                if (
                    key in {"diameter", "diameter_mm", "hole_diameter", "hole_diameter_mm"}
                    and is_hole_evidence
                    and isinstance(child, (int, float))
                    and not isinstance(child, bool)
                ):
                    diameters.append(float(child))
                visit(child, (*path, key))
        elif isinstance(item, list):
            for child in item:
                visit(child, path)

    visit(value)
    return triplets, diameters


def _trusted_measurement_payload(value: Any) -> dict[str, Any] | None:
    """@brief Yalnızca CAD/B-Rep API geri okuması olarak bildirilen yapılandırılmış spesifikasyon raporlarını kabul eder."""
    if not isinstance(value, dict):
        return None
    cad_spec = value.get("cad_spec")
    if not isinstance(cad_spec, dict):
        return None
    source = str(cad_spec.get("measurement_source") or value.get("measurement_source") or "")
    trusted_prefixes = ("SolidWorks API ", "AutoCAD ActiveX ", "OpenCascade B-Rep ")
    return cad_spec if source.startswith(trusted_prefixes) else None


def _artifact_measurements(artifacts: list[dict[str, Any]]) -> tuple[list[tuple[float, float, float]], list[float]]:
    """@brief Bu turun JSON teslimatlarından, Codex özetinden bağımsız spesifikasyon kanıtlarını okur."""
    triplets: list[tuple[float, float, float]] = []
    diameters: list[float] = []
    for artifact in artifacts:
        path = Path(str(artifact.get("path") or ""))
        if (
            artifact.get("exists") is not True
            or artifact.get("isDirectory") is True
            or artifact.get("producedThisRun") is not True
            or path.suffix.lower() != ".json"
            or int(artifact.get("sizeBytes") or 0) > 1024 * 1024
        ):
            continue
        try:
            raw = path.read_bytes()
            expected_sha256 = str(artifact.get("sha256") or "")
            if not expected_sha256 or hashlib.sha256(raw).hexdigest() != expected_sha256:
                continue
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        payload = _trusted_measurement_payload(value)
        if payload is None:
            continue
        found_triplets, found_diameters = _json_measurements(payload)
        triplets.extend(found_triplets)
        diameters.extend(found_diameters)
    return triplets, diameters


def _spec_conformance_checks(ledger: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """@brief Görevin açık ölçülerini kabul JSON'undaki gerçek spesifikasyonla karşılaştırır; yanlış modelin insan onayına geçmesini engeller."""
    strict_rules = ledger.get("strictRules") if isinstance(ledger.get("strictRules"), list) else []
    requirement_text = "\n".join(
        [
            str(ledger.get("objective") or ""),
            str(ledger.get("detail") or ""),
            *(str(item) for item in strict_rules),
        ]
    )
    expected_triplets = _dimension_triplets(requirement_text)
    expected_diameters = _diameters(requirement_text)
    evidence_triplets, evidence_diameters = _artifact_measurements(artifacts)
    expected_triplets = _unique_triplets(expected_triplets)
    checks: list[dict[str, Any]] = []

    if expected_triplets:
        missing_envelopes = [
            expected
            for expected in expected_triplets
            if not any(_same_envelope(expected, actual) for actual in evidence_triplets)
        ]
        checks.append(
            {
                "id": "spec-envelope-dimensions",
                "severity": "P0",
                "status": "pass" if evidence_triplets and not missing_envelopes else "fail",
                "message": (
                    f"Dış ölçü kanıtı görevle tutarlı: {expected_triplets} mm."
                    if evidence_triplets and not missing_envelopes
                    else "Bağımsız makine tarafından okunabilir dış ölçü kanıtı eksik."
                    if not evidence_triplets
                    else f"Dış ölçüler görevle tutarsız; {missing_envelopes} mm eksik, kabul kanıtı {evidence_triplets} mm bildiriyor."
                ),
            }
        )

    if expected_diameters:
        unique_expected = sorted(set(expected_diameters))
        unique_actual = sorted(set(evidence_diameters))
        missing = [
            expected
            for expected in unique_expected
            if not any(_close_measurement(expected, actual) for actual in unique_actual)
        ]
        checks.append(
            {
                "id": "spec-hole-diameters",
                "severity": "P0",
                "status": "pass" if evidence_diameters and not missing else "fail",
                "message": (
                    f"Delik çapı kanıtı görevle tutarlı: {unique_expected} mm."
                    if evidence_diameters and not missing
                    else "Görev açık delik çapı içeriyor; ancak teslimatta bağımsız makine tarafından okunabilir delik çapı kanıtı eksik."
                    if not evidence_diameters
                    else f"Delik çapları görevle tutarsız; istenen çap {missing} mm eksik, kabul kanıtı {unique_actual} mm bildiriyor."
                ),
            }
        )
    return checks


def evaluate_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    """@brief Defter içeriğine göre teslimat inceleme sonucunu üretir."""
    artifacts = ledger.get("artifacts") if isinstance(ledger.get("artifacts"), list) else []
    checks: list[dict[str, Any]] = []
    delivery_artifacts = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and (str(artifact.get("kind") or "") != "codex_output"
                                         or artifact_requires_current_run_proof(artifact))
    ]
    checks.extend(_spec_conformance_checks(ledger, delivery_artifacts))

    executor = str(ledger.get("executor") or "mock")
    production_executor = executor != "mock"
    verification = ledger.get("verification") if isinstance(ledger.get("verification"), list) else []
    if ledger.get("executor") == "codex" and not verification:
        checks.append(
            {
                "id": "executor-verification-present",
                "severity": "P1",
                "status": "warning",
                "message": "Yürütücü doğrulama kaydı döndürmedi; üretim adımlarının hedefe yönelik kontrolleri tamamladığı doğrulanamıyor.",
            }
        )
    for index, item in enumerate(verification):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "skipped")
        review_status = "pass" if status == "passed" else "warning" if status == "skipped" else "fail"
        checks.append(
            {
                "id": f"executor-verification-{index}",
                "severity": "P0" if review_status == "fail" else "P1",
                "status": review_status,
                "message": f"Yürütme doğrulaması {status}: {item.get('command') or 'adsız kontrol'}; {item.get('note') or ''}",
            }
        )

    risks = ledger.get("risks") if isinstance(ledger.get("risks"), list) else []
    if risks:
        checks.append(
            {
                "id": "executor-residual-risks",
                "severity": "P1",
                "status": "warning",
                "message": "Yürütücü kalan riskler bildirdi: " + "; ".join(str(item) for item in risks),
            }
        )

    expected_output = str(ledger.get("expectedOutput") or "")
    expected_output_upper = expected_output.upper()
    expected_groups: list[tuple[str, set[str]]] = []
    format_groups = [
        ("SLDPRT", {".sldprt"}),
        ("SLDASM", {".sldasm"}),
        ("SLDDRW", {".slddrw"}),
        ("STEP", {".step", ".stp"}),
        ("IGES", {".iges", ".igs"}),
        ("BREP", {".brep"}),
        ("STL", {".stl"}),
        ("OBJ", {".obj"}),
        ("GLB", {".glb"}),
        ("GLTF", {".gltf"}),
        ("DWG", {".dwg"}),
        ("DXF", {".dxf"}),
        ("PDF", {".pdf"}),
        ("PNG", {".png"}),
        ("SVG", {".svg"}),
    ]
    for label, extensions in format_groups:
        if label in expected_output_upper:
            expected_groups.append((label, extensions))

    freshness_artifacts = [
        artifact
        for artifact in delivery_artifacts
        if artifact_requires_current_run_proof(artifact)
    ]
    if production_executor and (freshness_artifacts or expected_groups or ledger.get("localCadAutomation") is True):
        stale = [
            artifact for artifact in freshness_artifacts
            if artifact.get("producedThisRun") is False
        ]
        unknown = [
            artifact for artifact in freshness_artifacts
            if artifact.get("producedThisRun") is not True
            and artifact.get("producedThisRun") is not False
        ]
        if stale:
            stale_paths = "；".join(str(item.get("path")) for item in stale)
            checks.append({
                "id": "artifact-current-run",
                "severity": "P0",
                "status": "fail",
                "message": f"Bu turda değişmeyen veya yeniden kullanılan teslimat dosyaları bulundu: {stale_paths}",
            })
        elif unknown or not freshness_artifacts:
            unknown_paths = "；".join(str(item.get("path")) for item in unknown)
            checks.append({
                "id": "artifact-current-run",
                "severity": "P1",
                "status": "warning",
                "message": (
                    f"Şu dosyaların bu turda üretilip üretilmediği doğrulanamıyor; insan incelemesi gerekli: {unknown_paths}"
                    if unknown_paths
                    else "Bu turun teslimat dosyaları için doğrulanabilir taban çizgisi eksik; insan incelemesi gerekli."
                ),
            })
        else:
            checks.append({
                "id": "artifact-current-run",
                "severity": "P2",
                "status": "pass",
                "message": "Tüm teslimat dosyalarının bu turda eklendiği veya değiştirildiği doğrulandı.",
            })

    for label, expected_extensions in expected_groups:
        candidates = []
        for artifact in delivery_artifacts:
            if Path(str(artifact.get("path") or "")).suffix.lower() not in expected_extensions:
                continue
            if artifact.get("exists") is not True:
                continue
            candidates.append(artifact)
        matching = [
            artifact for artifact in candidates
            if not production_executor or artifact.get("producedThisRun") is True
        ]
        stale_candidates = [
            artifact for artifact in candidates
            if production_executor and artifact.get("producedThisRun") is False
        ]
        unknown_candidates = [
            artifact for artifact in candidates
            if production_executor
            and artifact.get("producedThisRun") is not True
            and artifact.get("producedThisRun") is not False
        ]
        if matching:
            check_status = "pass"
            severity = "P0"
            message = f"Bu turda üretilen {label} teslimatları bulundu; toplam {len(matching)} adet."
        elif unknown_candidates and not stale_candidates:
            check_status = "warning"
            severity = "P1"
            message = f"{label} dosyaları mevcut; ancak bu turda üretildikleri doğrulanamıyor, insan incelemesi gerekli."
        else:
            check_status = "fail"
            severity = "P0"
            message = f"Beklenen çıktı {label} içeriyor; ancak bu turda üretilmiş karşılık gelen dosya bulunamadı. AI JSON makbuzu veya eski dosyalar teslimatın yerine geçemez."
        checks.append(
            {
                "id": f"expected-cad-deliverable-{label.lower()}",
                "severity": severity,
                "status": check_status,
                "message": message,
            }
        )
    current_run_cad = [
        artifact
        for artifact in delivery_artifacts
        if Path(str(artifact.get("path") or "")).suffix.lower() in DELIVERY_FILE_EXTENSIONS
        and artifact.get("exists") is True
        and (not production_executor or artifact.get("producedThisRun") is True)
    ]
    target = str(ledger.get("target") or "")
    expects_non_cad = any(token in expected_output for token in ("调研报告", "araştırma raporu")) or "Skills" in target or any(token in target for token in ("规范", "standart", "şartname"))
    if not expected_groups and ledger.get("localCadAutomation") is True and not expects_non_cad and not current_run_cad:
        checks.append(
            {
                "id": "cad-deliverable-not-declared",
                "severity": "P1",
                "status": "warning",
                "message": "Bu turda yerel CAD otomasyonuna izin verildi; ancak bu turda üretilmiş CAD/çizim dosyası yok. TXT, Markdown ve AI makbuzları CAD teslimatı sayılamaz.",
            }
        )

    if not artifacts:
        checks.append(
            {
                "id": "artifact-present",
                "severity": "P1",
                "status": "warning",
                "message": "Görev herhangi bir teslimat bildirmedi; şu an yalnızca sürecin tamamlandığı doğrulanabilir, imalat dosyalarının eksiksiz olduğu doğrulanamaz.",
            }
        )

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        kind = str(artifact.get("kind") or f"artifact_{index}")
        if artifact.get("exists") is not True:
            checks.append(
                {
                    "id": f"artifact-exists-{kind}",
                    "severity": "P0",
                    "status": "fail",
                    "message": f"Teslimat mevcut değil: {artifact.get('path')}",
                }
            )
            continue
        if artifact.get("isDirectory") is True:
            checks.append(
                {
                    "id": f"artifact-directory-{kind}",
                    "severity": "P2",
                    "status": "warning",
                    "message": f"Teslimat bir dizin; şu an yalnızca yol kaydedildi, dizin içeriği özyinelemeli doğrulanmadı: {artifact.get('path')}",
                }
            )
            continue
        size_bytes = int(artifact.get("sizeBytes") or 0)
        if size_bytes <= 0:
            checks.append(
                {
                    "id": f"artifact-nonempty-{kind}",
                    "severity": "P0",
                    "status": "fail",
                    "message": f"Teslimat boş bir dosya: {artifact.get('path')}",
                }
            )
        elif not artifact.get("sha256"):
            checks.append(
                {
                    "id": f"artifact-hash-{kind}",
                    "severity": "P1",
                    "status": "warning",
                    "message": f"Teslimatta SHA-256 eksik: {artifact.get('path')}",
                }
            )
        else:
            checks.append(
                {
                    "id": f"artifact-file-{kind}",
                    "severity": "P2",
                    "status": "pass",
                    "message": f"Teslimat mevcut ve hash kaydedildi: {artifact.get('path')}",
                }
            )
            format_check = validate_known_format(kind, Path(str(artifact.get("path"))))
            if format_check:
                checks.append(format_check)

    statuses = {check["status"] for check in checks}
    overall = "fail" if "fail" in statuses else "warning" if "warning" in statuses else "pass"
    return {
        "schemaVersion": "1.0",
        "jobId": ledger.get("jobId"),
        "runId": ledger.get("runId"),
        "status": overall,
        "reviewedAt": now_iso(),
        "artifactCount": len(artifacts),
        "checks": checks,
    }


def write_reviewer_gate(queue_dir: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    """@brief Reviewer Gate raporunu yazar ve rapor nesnesini döndürür."""
    review = evaluate_ledger(ledger)
    path = review_path_for(queue_dir, ledger.get("jobId"))
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    review["reviewPath"] = str(path)
    return review
