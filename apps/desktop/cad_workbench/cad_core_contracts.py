"""CAD Studio çift giriş/çift arka uç ortak veri sözleşmeleri.

Bu modül SolidWorks, AutoCAD veya masaüstü UI'ye bağımlı değildir; Skill, CLI, MCP, worker ve ön yüzün
NeutralCadDocument, PreviewManifest ve EvidenceGraph'ı ortak okuyup yazması için kullanılır.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


Unit = Literal["mm", "cm", "m", "inch", "unitless"]
PreviewMode = Literal["delivery-preview", "demo-showcase"]
PreferredBackend = Literal["auto", "headless", "solidworks", "autocad"]
FallbackPolicy = Literal["allow_open_formats", "native_only", "blocked"]


@dataclass(frozen=True)
class CoordinateSystem:
    """@brief Nötr CAD belgesinin koordinat sistemi sözleşmesi."""

    upAxis: str = "Z"
    frontAxis: str = "Y"
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class NeutralFeature:
    """@brief Arka uçlar arasında yönlendirilebilen parametrik unsur düğümü."""

    id: str
    type: str
    name: str = ""
    operation: str = "add"
    parameters: dict[str, Any] = field(default_factory=dict)
    evidenceRefs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NeutralCadDocument:
    """@brief Üretici CAD'ine bağlı olmayan parametrik kaynak belgesi."""

    documentId: str
    title: str = ""
    units: Unit = "mm"
    coordinateSystem: CoordinateSystem = field(default_factory=CoordinateSystem)
    parameters: dict[str, Any] = field(default_factory=dict)
    features: list[NeutralFeature] = field(default_factory=list)
    materials: list[dict[str, Any]] = field(default_factory=list)
    assemblies: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schemaVersion: str = "1.0"


@dataclass(frozen=True)
class PreviewManifest:
    """@brief Önizleme ürünleri ile gerçek kaynak ürünlerin izlenebilirlik listesi."""

    sourceArtifact: str
    previewArtifact: str
    units: Unit = "mm"
    fallbackImage: str = ""
    mode: PreviewMode = "delivery-preview"
    isDemo: bool = False
    bounds: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    layers: list[dict[str, Any]] = field(default_factory=list)
    evidenceRefs: list[str] = field(default_factory=list)
    generatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    sha256: str = ""
    limitations: list[str] = field(default_factory=list)
    previewVersion: str = "1.0"


@dataclass(frozen=True)
class EvidenceNode:
    """@brief Gereksinim, geometri, ölçü, dosya veya inceleme sonucu düğümü."""

    id: str
    type: str
    label: str = ""
    artifact: str = ""
    status: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceEdge:
    """@brief İki kanıt düğümü arasındaki köken veya doğrulama ilişkisi."""

    from_: str
    to: str
    relation: str

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.from_, "to": self.to, "relation": self.relation}


@dataclass(frozen=True)
class EvidenceGraph:
    """@brief CAD Studio teslimat kanıt grafiği."""

    nodes: list[EvidenceNode] = field(default_factory=list)
    edges: list[EvidenceEdge] = field(default_factory=list)
    schemaVersion: str = "1.0"


def _asdict(value: Any) -> dict[str, Any]:
    payload = asdict(value)
    if isinstance(value, EvidenceGraph):
        payload["edges"] = [edge.to_dict() for edge in value.edges]
    return payload


def sha256_file(path: str | Path) -> str:
    """@brief Ürünün SHA-256 değerini hesaplar; önizleme ile teslimat dosyasını bağlamak için kullanılır."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_contract(path: str | Path, value: Any) -> Path:
    """@brief Ortak sözleşme dosyasını kararlı UTF-8 JSON olarak yazar."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_asdict(value), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def read_json_contract(path: str | Path) -> dict[str, Any]:
    """@brief Ortak sözleşme JSON'unu okur."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def preview_manifest_for_artifact(
    source_artifact: str | Path,
    preview_artifact: str | Path,
    *,
    fallback_image: str | Path | None = None,
    units: Unit = "mm",
    mode: PreviewMode = "delivery-preview",
    is_demo: bool = False,
    evidence_refs: list[str] | None = None,
) -> PreviewManifest:
    """@brief Gerçek kaynak dosya ve JS tarafından okunabilir önizleme dosyası için izlenebilirlik listesi üretir."""
    preview_path = Path(preview_artifact)
    digest = sha256_file(preview_path) if preview_path.is_file() else ""
    return PreviewManifest(
        sourceArtifact=str(source_artifact),
        previewArtifact=str(preview_artifact),
        fallbackImage=str(fallback_image or ""),
        units=units,
        mode=mode,
        isDemo=is_demo,
        evidenceRefs=evidence_refs or [],
        sha256=digest,
        limitations=["Tanıtım verisi teslimat değerlendirmesine giremez"] if is_demo else [],
    )


def enrich_job_with_core_contracts(
    job: dict[str, Any],
    *,
    preferred_backend: PreferredBackend = "auto",
    required_outputs: list[str] | None = None,
    native_format_required: bool = False,
    fallback_policy: FallbackPolicy = "allow_open_formats",
    preview_manifest: str | None = None,
    evidence_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """@brief AutomationJob 2.0 için çift giriş/çift arka uç yönlendirme alanlarını tamamlar."""
    job["preferredBackend"] = preferred_backend
    job["requiredOutputs"] = required_outputs or list(job.get("requiredArtifacts") or [])
    job["nativeFormatRequired"] = native_format_required
    job["fallbackPolicy"] = fallback_policy
    if preview_manifest:
        job["previewManifest"] = preview_manifest
    if evidence_graph is not None:
        job["evidenceGraph"] = evidence_graph
    return job
