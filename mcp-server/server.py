"""
SolidWorks MCP Server.

This stdio MCP server wraps the existing solidworks-automation skill scripts so
MCP clients can operate a local Windows SolidWorks desktop session through
Python COM. It intentionally serializes all tool calls because SolidWorks COM is
a single-user desktop automation surface.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import threading
from contextlib import redirect_stdout
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator


_MCP_STDOUT = sys.stdout
for _stream in (_MCP_STDOUT, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
if __name__ == "__main__":
    sys.stdout = sys.stderr


SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.sw_preflight import missing_com_dependencies, solidworks_installed  # noqa: E402


pythoncom = None
_automation_loaded = False


def _load_automation_modules() -> None:
    """Lazy-load COM modules so the health tool can start without pywin32/comtypes."""
    global pythoncom, _automation_loaded
    if _automation_loaded:
        return

    connect = importlib.import_module("scripts.sw_connect")
    part = importlib.import_module("scripts.sw_part")
    appearance = importlib.import_module("scripts.sw_appearance")
    export = importlib.import_module("scripts.sw_export")
    review = importlib.import_module("scripts.sw_review")
    assembly = importlib.import_module("scripts.sw_assembly")
    motion = importlib.import_module("scripts.sw_motion")
    holes = importlib.import_module("scripts.sw_hole_features")
    document_data = importlib.import_module("scripts.sw_document_data")
    delivery = importlib.import_module("scripts.sw_delivery")
    drawing = importlib.import_module("scripts.sw_drawing")
    drawing_review = importlib.import_module("scripts.sw_drawing_review")
    drawing_spec = importlib.import_module("scripts.drawing_spec")

    exports = {
        "connect_solidworks": connect.connect_solidworks,
        "create_empty_dispatch_variant": connect.create_empty_dispatch_variant,
        "get_com_member": connect.get_com_member,
        "mm": connect.mm,
        "new_document": connect.new_document,
        "open_document": connect.open_document,
        "save_document": connect.save_document,
        "extrude_boss": part.extrude_boss,
        "sketch": part.sketch,
        "sketch_circle": part.sketch_circle,
        "sketch_rectangle": part.sketch_rectangle,
        "set_component_appearance": appearance.set_component_appearance,
        "set_document_appearance": appearance.set_document_appearance,
        "export_to_dxf": export.export_to_dxf,
        "export_to_iges": export.export_to_iges,
        "export_to_parasolid": export.export_to_parasolid,
        "export_to_pdf": export.export_to_pdf,
        "export_to_step": export.export_to_step,
        "export_to_stl": export.export_to_stl,
        "batch_export_formats": export.batch_export_formats,
        "inspect_configurations": document_data.inspect_configurations,
        "activate_configuration": document_data.activate_configuration,
        "create_configuration": document_data.create_configuration,
        "update_dimension_mm": document_data.update_dimension_mm,
        "set_custom_properties": document_data.set_custom_properties,
        "export_assembly_bom_csv": delivery.export_assembly_bom_csv,
        "pack_and_go": delivery.pack_and_go,
        "run_review": review.run_review,
        "collect_geometry_measurements": review.collect_geometry_measurements,
        "validate_hole_positions": review.validate_hole_positions,
        "drawing_generate_from_spec": drawing.generate_drawing_from_spec,
        "drawing_export_sheet_to_pdf": drawing.export_sheet_to_pdf,
        "drawing_save_review_previews": review.save_review_previews,
        "drawing_inspect_bmp_preview": review.inspect_bmp_preview,
        "drawing_inspect_structure": drawing.inspect_drawing_structure,
        "drawing_review_artifacts": drawing_review.review_drawing_artifacts,
        "drawing_load_spec": drawing_spec.load_drawing_spec,
        "drawing_validate_spec": drawing_spec.validate_drawing_spec,
        "SW_MATE_COINCIDENT": assembly.SW_MATE_COINCIDENT,
        "SW_MATE_DISTANCE": assembly.SW_MATE_DISTANCE,
        "assembly_add_component": assembly.add_component,
        "add_concentric_mate_by_cylinders": assembly.add_concentric_mate_by_cylinders,
        "add_mate5_checked": assembly.add_mate5_checked,
        "collect_mate_feature_summary": assembly.collect_mate_feature_summary,
        "find_component_by_name": assembly.find_component_by_name,
        "get_component_feature_entity": assembly.get_component_feature_entity,
        "get_components": assembly.get_components,
        "resolve_component": assembly.resolve_component,
        "select_entities_for_mate": assembly.select_entities_for_mate,
        "add_constant_speed_rotary_motor_by_cylinders": motion.add_constant_speed_rotary_motor_by_cylinders,
        "calculate_and_play": motion.calculate_and_play,
        "create_motion_study": motion.create_motion_study,
        "collect_motion_study_summary": motion.collect_motion_study_summary,
        "ensure_motion_type_library": motion.ensure_motion_type_library,
        "validate_motion_studies": motion.validate_motion_studies,
        "create_blind_hole": holes.create_blind_hole,
        "create_through_hole": holes.create_through_hole,
        "create_counterbore_hole": holes.create_counterbore_hole,
        "create_countersink_hole": holes.create_countersink_hole,
        "create_semicircular_slot": holes.create_semicircular_slot,
    }
    globals().update(exports)
    pythoncom = importlib.import_module("pythoncom")
    _automation_loaded = True


mcp = FastMCP(
    "solidworks_mcp",
    instructions=(
        "Local SolidWorks automation over Windows COM. Tools operate on the "
        "currently running SolidWorks desktop session and should be called "
        "serially."
    ),
)

_sw_lock = threading.RLock()


class ResponseFormat(str, Enum):
    """Tool response format."""

    JSON = "json"
    MARKDOWN = "markdown"


class DocType(str, Enum):
    """Supported SolidWorks document types."""

    PART = "part"
    ASSEMBLY = "assembly"
    DRAWING = "drawing"


class ExportFormat(str, Enum):
    """Supported export formats."""

    STEP = "step"
    STL = "stl"
    IGES = "iges"
    PARASOLID = "parasolid"
    PDF = "pdf"
    DXF = "dxf"


HEADLESS_OPEN_FORMATS = {"cadstudio", "step", "iges", "brep", "stl", "obj", "glb", "dxf", "svg", "pdf", "png"}
DFM_PROCESSES = {"auto", "machining", "sheet_metal", "laser_cutting", "3d_printing", "CNC", "FDM", "SLA"}
FEA_SOLVERS = {"auto", "calculix", "elmer"}


class BasicPartShape(str, Enum):
    """Low-risk basic part primitives exposed over MCP."""

    CYLINDER = "cylinder"
    BOX = "box"


class AppearanceTarget(str, Enum):
    """Supported appearance targets."""

    DOCUMENT = "document"
    COMPONENT = "component"


class HoleFeatureKind(str, Enum):
    """Supported hole and slot feature kinds."""

    BLIND = "blind"
    THROUGH = "through"
    COUNTERBORE = "counterbore"
    COUNTERSINK = "countersink"
    SEMICIRCULAR_SLOT = "semicircular_slot"


class BaseInput(BaseModel):
    """Common Pydantic config."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class SolidWorksConnectInput(BaseInput):
    """Input for connecting to SolidWorks."""

    visible: bool = Field(default=True, description="Whether a newly started SolidWorks instance should be visible.")
    wait_seconds: int = Field(default=5, ge=0, le=60, description="Seconds to wait after starting SolidWorks.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class CadStudioBackendRouteInput(BaseInput):
    """Input for resolving a language/runtime backend from the capability matrix."""

    operation_id: str = Field(..., min_length=1, max_length=160)
    available_backends: list[str] = Field(default_factory=list, max_length=50)
    available_requirements: list[str] = Field(default_factory=list, max_length=50)
    solidworks_revision: Optional[str] = Field(default=None, max_length=40)
    exact_api: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class CadStudioOpenFormatInput(BaseInput):
    """Input for no-CAD open-format export from a NeutralCadDocument."""

    input_path: str = Field(..., min_length=1, description="Absolute .cadstudio.json NeutralCadDocument path.")
    output_dir: str = Field(..., min_length=1, description="Absolute output directory for open-format artifacts.")
    formats: list[str] = Field(default_factory=lambda: ["cadstudio", "step", "iges", "brep", "stl", "obj", "glb", "dxf", "svg", "pdf", "png"], min_length=1, max_length=12)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"Input must be an existing .cadstudio.json file: {value}")
        return value

    @field_validator("formats")
    @classmethod
    def formats_must_be_whitelisted(cls, values: list[str]) -> list[str]:
        normalized = [value.lower().lstrip(".") for value in values]
        unsupported = [value for value in normalized if value not in HEADLESS_OPEN_FORMATS]
        if unsupported:
            raise ValueError("Unsupported open formats: " + ", ".join(unsupported))
        return normalized


class CadStudioDxfPreviewInput(BaseInput):
    """Input for read-only DXF to PreviewScene conversion."""

    source_path: str = Field(..., min_length=1, description="Absolute existing DXF path.")
    output_path: str = Field(..., min_length=1, description="Absolute non-existing .scene.json output path.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("source_path")
    @classmethod
    def source_must_be_existing_dxf(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".dxf" or not path.is_file():
            raise ValueError(f"Source must be an existing DXF file: {value}")
        return value

    @field_validator("output_path")
    @classmethod
    def output_must_be_new_scene_json(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if not path.name.lower().endswith(".scene.json"):
            raise ValueError("Output must use the .scene.json suffix")
        if path.exists():
            raise ValueError(f"Refusing to overwrite existing PreviewScene: {path.name}")
        return value


class CadStudioDfmReviewInput(BaseInput):
    """Input for NeutralCadDocument DFM review."""

    input_path: str = Field(..., min_length=1, description="Absolute .cadstudio.json NeutralCadDocument path.")
    output_path: str = Field(..., min_length=1, description="Absolute JSON report path; existing files are versioned instead of overwritten.")
    process: str = Field(default="auto", description="auto, machining, sheet_metal, laser_cutting, 3d_printing, CNC, FDM, or SLA.")
    profile_paths: list[str] = Field(default_factory=list, max_length=8, description="Optional DFM profile JSON paths; merged as supplier capability intersection.")
    brep_evidence_path: Optional[str] = Field(default=None, description="Optional SolidWorks/OCCT B-Rep evidence JSON path.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"Input must be an existing .cadstudio.json file: {value}")
        return value

    @field_validator("output_path")
    @classmethod
    def output_path_must_be_json(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json":
            raise ValueError(f"Output must be a JSON report path: {value}")
        return value

    @field_validator("process")
    @classmethod
    def process_must_be_whitelisted(cls, value: str) -> str:
        if value not in DFM_PROCESSES:
            raise ValueError("Unsupported DFM process: " + value)
        return value

    @field_validator("profile_paths")
    @classmethod
    def profile_paths_must_exist(cls, values: list[str]) -> list[str]:
        missing = [value for value in values if not Path(os.path.expandvars(value)).expanduser().is_file()]
        if missing:
            raise ValueError("DFM profile files do not exist: " + ", ".join(missing[:5]))
        return values

    @field_validator("brep_evidence_path")
    @classmethod
    def brep_evidence_must_exist(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"B-Rep evidence must be an existing JSON file: {value}")
        return value


class CadStudioRoutingReviewInput(BaseInput):
    """Input for neutral Routing review."""

    input_path: str = Field(..., min_length=1, description="Absolute Routing JSON path.")
    output_path: str = Field(..., min_length=1, description="Absolute JSON report path; existing files are versioned instead of overwritten.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"Routing input must be an existing JSON file: {value}")
        return value

    @field_validator("output_path")
    @classmethod
    def output_path_must_be_json(cls, value: str) -> str:
        if Path(os.path.expandvars(value)).expanduser().suffix.lower() != ".json":
            raise ValueError(f"Output must be a JSON report path: {value}")
        return value


class CadStudioRoutingPreflightInput(BaseInput):
    """Input for SolidWorks Routing preflight."""

    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class CadStudioFeaPreflightInput(BaseInput):
    """Input for open solver FEA preflight."""

    solver: str = Field(default="auto", description="auto, calculix, or elmer.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("solver")
    @classmethod
    def solver_must_be_whitelisted(cls, value: str) -> str:
        if value not in FEA_SOLVERS:
            raise ValueError("Unsupported FEA solver: " + value)
        return value


class CadStudioFeaPrepareInput(BaseInput):
    """Input for preparing a whitelisted CalculiX FEA deck."""

    input_path: str = Field(..., min_length=1, description="Absolute FEA 1.0 request JSON path.")
    output_dir: str = Field(..., min_length=1, description="Output directory for versioned CalculiX .inp artifacts.")
    solver: str = Field(default="auto", description="auto, calculix, or elmer.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"FEA input must be an existing JSON file: {value}")
        return value

    @field_validator("solver")
    @classmethod
    def solver_must_be_whitelisted(cls, value: str) -> str:
        if value not in FEA_SOLVERS:
            raise ValueError("Unsupported FEA solver: " + value)
        return value


class CadStudioFeaRunInput(BaseInput):
    """Input for running an approved local FEA solver."""

    input_path: str = Field(..., min_length=1, description="Absolute FEA 1.0 request JSON path.")
    output_dir: str = Field(..., min_length=1, description="Output directory for versioned solver artifacts.")
    timeout_seconds: int = Field(default=600, ge=1, le=86400, description="Solver timeout in seconds.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"FEA input must be an existing JSON file: {value}")
        return value


class CadStudioFeaConvergenceInput(BaseInput):
    """Input for running a whitelisted CalculiX mesh convergence sequence."""

    input_path: str = Field(..., min_length=1, description="Absolute FEA convergence 1.0 request JSON path.")
    output_dir: str = Field(..., min_length=1, description="Output directory for versioned convergence artifacts.")
    timeout_seconds_per_case: int = Field(default=600, ge=1, le=86400, description="Timeout for each mesh case.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"FEA convergence input must be an existing JSON file: {value}")
        return value


class CadStudioAdvancedGeometryInput(BaseInput):
    """Input for advanced surface/mold plan preflight."""

    input_path: str = Field(..., min_length=1, description="Absolute advanced geometry plan JSON path.")
    output_path: str = Field(..., min_length=1, description="Absolute JSON report path; existing files are versioned instead of overwritten.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"Advanced geometry input must be an existing JSON file: {value}")
        return value

    @field_validator("output_path")
    @classmethod
    def output_path_must_be_json(cls, value: str) -> str:
        if Path(os.path.expandvars(value)).expanduser().suffix.lower() != ".json":
            raise ValueError(f"Output must be a JSON report path: {value}")
        return value


class CadStudioOcpLoftInput(BaseInput):
    """Input for creating a restricted OCP parametric loft."""

    input_path: str = Field(..., min_length=1, description="Absolute OCP Loft 1.0 JSON request path.")
    output_dir: str = Field(..., min_length=1, description="Output directory for versioned STEP/BREP/STL artifacts.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"OCP Loft input must be an existing JSON file: {value}")
        return value


class CadStudioOcpSurfaceInput(BaseInput):
    """Input for restricted OCP smooth loft, sweep, knit, or thicken."""

    input_path: str = Field(..., min_length=1, description="Absolute OCP advanced surface 1.0 JSON request path.")
    output_dir: str = Field(..., min_length=1, description="Output directory for versioned STEP/BREP/STL artifacts.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("input_path")
    @classmethod
    def input_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"OCP surface input must be an existing JSON file: {value}")
        return value


class SolidWorksHealthCheckInput(BaseInput):
    """Input for checking the local SolidWorks automation environment."""

    start_solidworks: bool = Field(default=False, description="Start/connect SolidWorks for a live COM check.")
    check_motion_type_library: bool = Field(default=True, description="Check for swmotionstudy.tlb availability.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksNewDocumentInput(BaseInput):
    """Input for creating a new document."""

    doc_type: DocType = Field(default=DocType.PART, description="Document type to create.")
    template_path: Optional[str] = Field(default=None, description="Optional explicit SolidWorks template path.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksCreateBasicPartInput(BaseInput):
    """Input for creating a simple box or cylinder part."""

    shape: BasicPartShape = Field(default=BasicPartShape.CYLINDER, description="Part primitive to create.")
    output_path: Optional[str] = Field(default=None, description="Optional absolute .SLDPRT Save As path.")
    plane_name: str = Field(default="Front Plane", min_length=1, description="Sketch plane name, English or Chinese.")
    width_mm: float = Field(default=80.0, gt=0.0, le=5000.0, description="Box width in mm.")
    height_mm: float = Field(default=60.0, gt=0.0, le=5000.0, description="Box height in mm.")
    radius_mm: float = Field(default=25.0, gt=0.0, le=2500.0, description="Cylinder radius in mm.")
    depth_mm: float = Field(default=50.0, gt=0.0, le=5000.0, description="Extrusion depth in mm.")
    color: Optional[str] = Field(default=None, description="Optional document appearance color, e.g. #BFC4C8.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksOpenDocumentInput(BaseInput):
    """Input for opening an existing document."""

    path: str = Field(..., min_length=1, description="Absolute path to .SLDPRT/.SLDASM/.SLDDRW or importable file.")
    read_only: bool = Field(default=False, description="Open document read-only.")
    silent: bool = Field(default=True, description="Use SolidWorks silent open option.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("path")
    @classmethod
    def path_must_exist(cls, value: str) -> str:
        if not Path(os.path.expandvars(value)).expanduser().exists():
            raise ValueError(f"File does not exist: {value}")
        return value


class SolidWorksSaveDocumentInput(BaseInput):
    """Input for saving the active document."""

    path: Optional[str] = Field(default=None, description="Optional Save As path. Omit to save current document.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksCloseDocumentsInput(BaseInput):
    """Input for closing SolidWorks documents."""

    close_all: bool = Field(default=False, description="Close all documents when true; otherwise close active document.")
    save_changes: bool = Field(default=False, description="Whether SolidWorks should save changed documents when closing all.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksAddComponentInput(BaseInput):
    """Input for adding a component to the active assembly."""

    path: str = Field(..., min_length=1, description="Absolute path to .SLDPRT or .SLDASM component.")
    x_mm: float = Field(default=0.0, description="Insertion X coordinate in mm.")
    y_mm: float = Field(default=0.0, description="Insertion Y coordinate in mm.")
    z_mm: float = Field(default=0.0, description="Insertion Z coordinate in mm.")
    config_name: str = Field(default="", description="Optional component configuration name.")
    fix_component: bool = Field(default=False, description="Fix the inserted component in the assembly.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("path")
    @classmethod
    def component_path_must_exist(cls, value: str) -> str:
        if not Path(os.path.expandvars(value)).expanduser().exists():
            raise ValueError(f"File does not exist: {value}")
        return value


class SolidWorksSetComponentFixedInput(BaseInput):
    """Input for fixing or floating a component in the active assembly."""

    component_keyword: str = Field(..., min_length=1, description="Keyword in the component name.")
    fixed: bool = Field(default=True, description="True=fix component, False=float component.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksExportInput(BaseInput):
    """Input for exporting the active document."""

    output_path: str = Field(..., min_length=1, description="Absolute output file path.")
    export_format: ExportFormat = Field(..., description="Export format.")
    stl_quality: str = Field(default="fine", description="STL quality: coarse or fine.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksDimensionUpdateInput(BaseInput):
    """Input for updating a named model dimension in millimeters."""

    dimension_name: str = Field(..., min_length=1, max_length=240, description="Exact dimension name, e.g. D1@Boss-Extrude1.")
    value_mm: float = Field(..., gt=0.0, le=100000.0, description="New dimension value in millimeters.")
    configuration_mode: str = Field(default="current", pattern="^(current|all|specific)$")
    configuration_names: list[str] = Field(default_factory=list, max_length=200)
    rebuild: bool = Field(default=True)
    save: bool = Field(default=False, description="Save the current document after a verified rebuild.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksConfigurationCreateInput(BaseInput):
    """Input for creating and optionally activating a SolidWorks configuration."""

    configuration_name: str = Field(..., min_length=1, max_length=240)
    comment: str = Field(default="", max_length=1024)
    alternate_name: str = Field(default="", max_length=240)
    options: int = Field(default=0, ge=0, description="swConfigurationOptions2_e bitmask; default 0.")
    if_exists: str = Field(default="reuse", pattern="^(reuse|error)$")
    activate: bool = Field(default=True)
    rebuild: bool = Field(default=True)
    save: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksConfigurationInspectInput(BaseInput):
    """Input for inspecting the active document configuration family."""

    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksConfigurationActivateInput(BaseInput):
    """Input for activating and verifying an existing SolidWorks configuration."""

    configuration_name: str = Field(..., min_length=1, max_length=240)
    rebuild: bool = Field(default=True)
    save: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksCustomPropertiesInput(BaseInput):
    """Input for setting file-level or configuration-level custom properties."""

    properties: Dict[str, str] = Field(..., min_length=1, max_length=100)
    configuration_name: str = Field(default="", max_length=240)
    property_type: str = Field(default="text", pattern="^(text|number|double|yes_no|date)$")
    save: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksBatchExportInput(BaseInput):
    """Input for exporting multiple SolidWorks files to multiple formats."""

    file_paths: list[str] = Field(..., min_length=1, max_length=200)
    output_dir: str = Field(..., min_length=1)
    formats: list[str] = Field(default_factory=lambda: ["step"], min_length=1, max_length=10)
    overwrite: bool = Field(default=False)
    close_documents: bool = Field(default=True)
    stl_quality: str = Field(default="fine", pattern="^(coarse|fine)$")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("file_paths")
    @classmethod
    def source_files_must_exist(cls, values: list[str]) -> list[str]:
        missing = [value for value in values if not Path(os.path.expandvars(value)).expanduser().is_file()]
        if missing:
            raise ValueError("Source files do not exist: " + ", ".join(missing[:5]))
        return values


class SolidWorksBomExportInput(BaseInput):
    """Input for exporting a reviewed assembly component BOM CSV."""

    output_path: str = Field(..., min_length=1)
    include_excluded: bool = Field(default=False)
    overwrite: bool = Field(default=False)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksPackAndGoInput(BaseInput):
    """Input for native Pack and Go plus the explicit dependency staging fallback."""

    output_dir: str = Field(..., min_length=1)
    include_drawings: bool = Field(default=True)
    include_simulation_results: bool = Field(default=False)
    include_toolbox_components: bool = Field(default=True)
    include_suppressed: bool = Field(default=False)
    flatten: bool = Field(default=False)
    overwrite: bool = Field(default=False)
    fallback_policy: Literal["stage_dependencies", "blocked"] = Field(
        default="stage_dependencies",
        description="原生依赖枚举缺失时生成可审计暂存包，或严格阻断",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksReviewInput(BaseInput):
    """Input for exporting previews and a review report."""

    output_dir: str = Field(..., min_length=1, description="Directory for BMP previews and JSON report.")
    basename: str = Field(default="mcp_review", min_length=1, max_length=80, description="Output filename prefix.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksGenerateDrawingInput(BaseInput):
    """Input for the structured SolidWorks engineering drawing workflow."""

    spec_path: str = Field(..., min_length=1, description="Existing DrawingSpec v1 JSON path.")
    output_dir: str = Field(..., min_length=1, description="Directory for SLDDRW, PDF, previews, and reports.")
    drawing_filename: str = Field(default="drawing.slddrw", min_length=1, max_length=120)
    overwrite: bool = Field(default=False, description="Allow replacing this run's requested drawing output.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("spec_path")
    @classmethod
    def drawing_spec_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"DrawingSpec must be an existing JSON file: {value}")
        return value

    @field_validator("drawing_filename")
    @classmethod
    def drawing_filename_must_be_slddrw(cls, value: str) -> str:
        if Path(value).name != value or Path(value).suffix.lower() != ".slddrw":
            raise ValueError("drawing_filename must be a filename ending in .slddrw")
        return value


class SolidWorksReviewDrawingInput(BaseInput):
    """Input for the full engineering drawing review gate."""

    drawing_path: str = Field(..., min_length=1, description="Existing .SLDDRW drawing path.")
    spec_path: str = Field(..., min_length=1, description="Existing DrawingSpec v1 JSON path.")
    output_dir: str = Field(..., min_length=1, description="Directory for review reports and previews.")
    pdf_path: Optional[str] = Field(default=None, description="Optional exported PDF for vector text evidence.")
    basename: str = Field(default="drawing_review", min_length=1, max_length=80)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("drawing_path")
    @classmethod
    def drawing_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".slddrw" or not path.is_file():
            raise ValueError(f"Drawing must be an existing .SLDDRW file: {value}")
        return value

    @field_validator("spec_path")
    @classmethod
    def review_spec_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"DrawingSpec must be an existing JSON file: {value}")
        return value

    @field_validator("pdf_path")
    @classmethod
    def review_pdf_must_exist(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".pdf" or not path.is_file():
            raise ValueError(f"PDF must be an existing file: {value}")
        return value


class SolidWorksInspectDrawingInput(BaseInput):
    """Input for read-only structural drawing inspection."""

    drawing_path: str = Field(..., min_length=1, description="Existing .SLDDRW drawing path.")
    output_dir: str = Field(..., min_length=1, description="Directory for structural report and previews.")
    basename: str = Field(default="drawing_inspect", min_length=1, max_length=80)
    paper_size_hint: Optional[str] = Field(default=None, pattern="^(A4|A3|A2|A1|A0)$")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("drawing_path")
    @classmethod
    def inspect_drawing_path_must_exist(cls, value: str) -> str:
        path = Path(os.path.expandvars(value)).expanduser()
        if path.suffix.lower() != ".slddrw" or not path.is_file():
            raise ValueError(f"Drawing must be an existing .SLDDRW file: {value}")
        return value


class SolidWorksHoleFeatureInput(BaseInput):
    """Input for creating a constrained hole or semicircular slot on the active part."""

    feature_kind: HoleFeatureKind = Field(..., description="Hole or slot kind.")
    center_x_mm: float = Field(default=0.0, description="Hole center X on the sketch plane, mm.")
    center_y_mm: float = Field(default=0.0, description="Hole center Y on the sketch plane, mm.")
    diameter_mm: float = Field(default=5.0, gt=0.0, le=1000.0, description="Main hole diameter, mm.")
    depth_mm: Optional[float] = Field(default=None, gt=0.0, le=5000.0, description="Blind depth, mm.")
    secondary_diameter_mm: Optional[float] = Field(default=None, gt=0.0, le=2000.0, description="Counterbore/countersink diameter, mm.")
    secondary_depth_mm: Optional[float] = Field(default=None, gt=0.0, le=5000.0, description="Counterbore depth, mm.")
    included_angle_deg: float = Field(default=90.0, ge=10.0, lt=170.0, description="Countersink included angle, degrees.")
    slot_end_x_mm: Optional[float] = Field(default=None, description="Slot end X on the sketch plane, mm.")
    slot_end_y_mm: Optional[float] = Field(default=None, description="Slot end Y on the sketch plane, mm.")
    plane_name: str = Field(default="Front Plane", min_length=1, max_length=120, description="Standard sketch plane.")
    feature_name: str = Field(default="MCP_孔槽", min_length=1, max_length=120, description="Feature tree name.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class HoleExpectationInput(BaseInput):
    """Expected B-Rep hole diameter and axis position in millimeters."""

    id: str = Field(..., min_length=1, max_length=80)
    diameter_mm: float = Field(..., gt=0.0, le=2000.0)
    position_mm: tuple[float, float, float]


class SolidWorksHoleInspectionInput(BaseInput):
    """Input for inspecting B-Rep holes and optional expected positions."""

    expected_holes: list[HoleExpectationInput] = Field(default_factory=list)
    position_tolerance_mm: float = Field(default=0.1, gt=0.0, le=10.0)
    diameter_tolerance_mm: float = Field(default=0.05, gt=0.0, le=10.0)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksPlaneCoincidentMateInput(BaseInput):
    """Input for adding a coincident mate between two component planes/features."""

    component_a_keyword: str = Field(..., min_length=1, description="Keyword in the first component name.")
    component_b_keyword: str = Field(..., min_length=1, description="Keyword in the second component name.")
    feature_a_name: str = Field(default="Front Plane", min_length=1, description="Feature/plane name inside component A.")
    feature_b_name: str = Field(default="Front Plane", min_length=1, description="Feature/plane name inside component B.")
    mate_name: Optional[str] = Field(default=None, max_length=120, description="Optional mate feature name.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksPlaneDistanceMateInput(BaseInput):
    """Input for adding a distance mate between two component planes/features."""

    component_a_keyword: str = Field(..., min_length=1, description="Keyword in the first component name.")
    component_b_keyword: str = Field(..., min_length=1, description="Keyword in the second component name.")
    feature_a_name: str = Field(default="Front Plane", min_length=1, description="Feature/plane name inside component A.")
    feature_b_name: str = Field(default="Front Plane", min_length=1, description="Feature/plane name inside component B.")
    distance_mm: float = Field(default=0.0, ge=0.0, le=5000.0, description="Mate distance in mm.")
    mate_name: Optional[str] = Field(default=None, max_length=120, description="Optional mate feature name.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksConcentricMateInput(BaseInput):
    """Input for adding a concentric mate by largest matching cylinder faces."""

    component_a_keyword: str = Field(..., min_length=1, description="Keyword in the first component name.")
    component_b_keyword: str = Field(..., min_length=1, description="Keyword in the second component name.")
    radius_a_min_mm: float = Field(default=0.0, ge=0.0, description="Minimum cylinder radius in component A, mm.")
    radius_a_max_mm: Optional[float] = Field(default=None, ge=0.0, description="Maximum cylinder radius in component A, mm.")
    radius_b_min_mm: float = Field(default=0.0, ge=0.0, description="Minimum cylinder radius in component B, mm.")
    radius_b_max_mm: Optional[float] = Field(default=None, ge=0.0, description="Maximum cylinder radius in component B, mm.")
    lock_rotation: bool = Field(default=False, description="Whether to lock concentric rotation. Keep false for motors.")
    mate_name: Optional[str] = Field(default=None, max_length=120, description="Optional mate feature name.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("radius_a_max_mm")
    @classmethod
    def radius_a_range_valid(cls, value: Optional[float], info):
        if value is not None and value < info.data.get("radius_a_min_mm", 0.0):
            raise ValueError("radius_a_max_mm must be >= radius_a_min_mm")
        return value

    @field_validator("radius_b_max_mm")
    @classmethod
    def radius_b_range_valid(cls, value: Optional[float], info):
        if value is not None and value < info.data.get("radius_b_min_mm", 0.0):
            raise ValueError("radius_b_max_mm must be >= radius_b_min_mm")
        return value


class SolidWorksSetAppearanceInput(BaseInput):
    """Input for setting document or component appearance color."""

    target: AppearanceTarget = Field(default=AppearanceTarget.DOCUMENT, description="Appearance target.")
    color: str = Field(..., min_length=1, description="Preset name or #RRGGBB color.")
    component_keyword: Optional[str] = Field(default=None, description="Required when target=component.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksRotaryMotorInput(BaseInput):
    """Input for adding a constant-speed rotary motor to the active assembly."""

    shaft_component_keyword: str = Field(..., min_length=1, description="Keyword in the stationary shaft/support component name.")
    rotor_component_keyword: str = Field(..., min_length=1, description="Keyword in the rotating component name.")
    shaft_radius_min_mm: float = Field(default=0.0, ge=0.0, description="Minimum shaft cylinder radius in mm.")
    shaft_radius_max_mm: Optional[float] = Field(default=None, ge=0.0, description="Maximum shaft cylinder radius in mm.")
    rotor_radius_min_mm: float = Field(default=0.0, ge=0.0, description="Minimum rotor cylinder radius in mm.")
    rotor_radius_max_mm: Optional[float] = Field(default=None, ge=0.0, description="Maximum rotor cylinder radius in mm.")
    rpm: float = Field(default=60.0, description="Constant motor speed in RPM.")
    study_name: str = Field(default="MCP_旋转马达算例", min_length=1, max_length=120, description="Motion Study name.")
    motor_name: str = Field(default="MCP_匀速旋转马达", min_length=1, max_length=120, description="Motor feature name.")
    duration_seconds: float = Field(default=4.0, gt=0.0, le=120.0, description="Motion Study duration in seconds.")
    calculate: bool = Field(default=True, description="Calculate the Motion Study after creating the motor.")
    play: bool = Field(default=False, description="Play the animation after calculation.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")

    @field_validator("shaft_radius_max_mm")
    @classmethod
    def shaft_radius_range_valid(cls, value: Optional[float], info):
        if value is not None and value < info.data.get("shaft_radius_min_mm", 0.0):
            raise ValueError("shaft_radius_max_mm must be >= shaft_radius_min_mm")
        return value

    @field_validator("rotor_radius_max_mm")
    @classmethod
    def rotor_radius_range_valid(cls, value: Optional[float], info):
        if value is not None and value < info.data.get("rotor_radius_min_mm", 0.0):
            raise ValueError("rotor_radius_max_mm must be >= rotor_radius_min_mm")
        return value


class SolidWorksMotionAuditInput(BaseInput):
    """Input for auditing Motion Study definitions and result freshness."""

    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksMotionValidationInput(BaseInput):
    """Input for enforcing Motion Study delivery requirements."""

    study_name: Optional[str] = Field(default=None, max_length=120)
    expected_study_type: Optional[int] = Field(default=None, ge=0, le=10)
    minimum_duration_seconds: float = Field(default=0.001, gt=0.0, le=3600.0)
    minimum_motor_count: int = Field(default=1, ge=0, le=1000)
    require_results: bool = Field(default=True)
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


def _coinitialize() -> None:
    """Initialize COM for the current MCP worker thread."""
    if pythoncom is not None:
        pythoncom.CoInitialize()


def _active_model_required():
    """Return the active SolidWorks document or raise a helpful error."""
    sw, model = connect_solidworks(wait_seconds=1)
    model = sw.ActiveDoc or model
    if model is None:
        raise RuntimeError("No active SolidWorks document. Use solidworks_open_document or solidworks_new_document first.")
    return sw, model


def _active_assembly_required():
    """Return the active SolidWorks assembly document or raise a helpful error."""
    sw, model = _active_model_required()
    if int(get_com_member(model, "GetType")) != 2:
        raise RuntimeError("Active document must be an assembly (.SLDASM).")
    return sw, model


def _active_part_required():
    """Return the active SolidWorks part document or raise a helpful error."""
    sw, model = _active_model_required()
    if int(get_com_member(model, "GetType")) != 1:
        raise RuntimeError("Active document must be a part (.SLDPRT).")
    return sw, model


def _model_summary(model) -> Dict[str, Any]:
    """Return a compact active document summary."""
    return {
        "title": get_com_member(model, "GetTitle"),
        "path": get_com_member(model, "GetPathName"),
        "type": get_com_member(model, "GetType"),
    }


def _component_summary(component) -> Dict[str, Any]:
    """Return a compact component summary."""
    return {
        "name": get_com_member(component, "Name2"),
        "path": get_com_member(component, "GetPathName"),
        "suppressed": bool(get_com_member(component, "IsSuppressed")),
        "visible": get_com_member(component, "Visible"),
    }


def _set_component_fixed(asm_model, component, fixed: bool = True) -> bool:
    """Fix or float an assembly component through the active selection."""
    asm_model.ClearSelection2(True)
    selected = False
    try:
        selected = bool(component.Select4(False, create_empty_dispatch_variant(), False))
    except Exception:
        selected = False
    if not selected:
        selected = bool(
            asm_model.Extension.SelectByID2(
                get_com_member(component, "Name2"),
                "COMPONENT",
                0,
                0,
                0,
                False,
                0,
                create_empty_dispatch_variant(),
                0,
            )
        )
    if not selected:
        raise RuntimeError(f"Failed to select component: {get_com_member(component, 'Name2')}")
    member_name = "FixComponent" if fixed else "UnfixComponent"
    result = get_com_member(asm_model, member_name)
    asm_model.ClearSelection2(True)
    return bool(result) if result is not None else True


def _result(payload: Dict[str, Any], response_format: ResponseFormat) -> str:
    """Format a tool response as JSON or Markdown."""
    if response_format == ResponseFormat.JSON:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    lines = [f"# {payload.get('status', 'result')}"]
    for key, value in payload.items():
        if key == "status":
            continue
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, indent=2)
            lines.append(f"- **{key}**:\n```json\n{rendered}\n```")
        else:
            lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def _tool_error(exc: Exception, response_format: ResponseFormat = ResponseFormat.JSON) -> str:
    """Return actionable tool error content."""
    payload = {
        "status": "error",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "suggestion": (
            "Confirm SolidWorks is installed/running, the active document is correct, "
            "components are resolved, and file paths are absolute Windows paths."
        ),
    }
    return _result(payload, response_format)


def _run_locked(operation, response_format: ResponseFormat, load_automation: bool = True):
    """Run one SolidWorks COM operation under the global lock."""
    with _sw_lock:
        try:
            if load_automation:
                _load_automation_modules()
            _coinitialize()
            with redirect_stdout(sys.stderr):
                payload = operation()
            return _result(payload, response_format)
        except Exception as exc:
            return _tool_error(exc, response_format)


@mcp.tool(
    name="cadstudio_resolve_backend",
    title="Resolve CAD Language Backend",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def cadstudio_resolve_backend(params: CadStudioBackendRouteInput) -> str:
    """Select Python, C#, C++, SWBasic, OCCT, AutoCAD .NET, or an external solver."""

    def op():
        from scripts.capabilities import resolve_operation_backend

        return resolve_operation_backend(
            params.operation_id,
            available_backends=params.available_backends or None,
            available_requirements=params.available_requirements,
            solidworks_revision=params.solidworks_revision,
            exact_api=params.exact_api,
        )

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_write_open_format",
    title="Write No-CAD Open Format Artifacts",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def cadstudio_write_open_format(params: CadStudioOpenFormatInput) -> str:
    """Write STEP/IGES/BREP/STL/OBJ/GLB/DXF/SVG/PDF/PNG without SolidWorks or AutoCAD."""

    def op():
        from scripts.headless_cad_writer import export_headless

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        return export_headless(input_path, output_dir, params.formats)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_build_dxf_preview_scene",
    title="Build Safe DXF Preview Scene",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_build_dxf_preview_scene(params: CadStudioDxfPreviewInput) -> str:
    """Convert an existing DXF into a whitelisted PreviewScene JSON without running scripts."""

    def op():
        from scripts.dxf_preview_scene import dxf_to_preview_scene

        source = Path(os.path.expandvars(params.source_path)).expanduser().resolve()
        output = Path(os.path.expandvars(params.output_path)).expanduser().resolve()
        scene = dxf_to_preview_scene(source, output)
        return {
            "status": "pass",
            "backend": "ezdxf-preview-scene",
            "source": source.name,
            "output": str(output),
            "entityCount": len(scene["entities"]),
            "layerCount": len(scene["layers"]),
            "limitations": scene["limitations"],
        }

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_check_dfm",
    title="Review Neutral CAD DFM Risks",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_check_dfm(params: CadStudioDfmReviewInput) -> str:
    """Run whitelisted DFM checks for machining, sheet metal, laser cutting, or 3D printing."""

    def op():
        from scripts.dfm_review import write_dfm_report

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_path = Path(os.path.expandvars(params.output_path)).expanduser().resolve()
        profile_paths = [Path(os.path.expandvars(value)).expanduser().resolve() for value in params.profile_paths]
        brep_evidence = Path(os.path.expandvars(params.brep_evidence_path)).expanduser().resolve() if params.brep_evidence_path else None
        return write_dfm_report(input_path, output_path, process=params.process, profiles=profile_paths, brep_evidence=brep_evidence)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_check_routing",
    title="Review Neutral Routing",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_check_routing(params: CadStudioRoutingReviewInput) -> str:
    """Review neutral routing topology, bend radius, clearance, supports, and BOM evidence."""

    def op():
        from scripts.routing_review import review_routing_file

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_path = Path(os.path.expandvars(params.output_path)).expanduser().resolve()
        return review_routing_file(input_path, output_path)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_routing_preflight",
    title="Probe SolidWorks Routing Backend",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def cadstudio_routing_preflight(params: CadStudioRoutingPreflightInput = CadStudioRoutingPreflightInput()) -> str:
    """Probe SolidWorks Routing type library, add-in registration, and license evidence."""

    def op():
        from scripts.routing_review import probe_solidworks_routing

        return probe_solidworks_routing()

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_fea_preflight",
    title="Probe Open FEA Solver",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def cadstudio_fea_preflight(params: CadStudioFeaPreflightInput = CadStudioFeaPreflightInput()) -> str:
    """Discover approved CalculiX or Elmer solver executables without running arbitrary commands."""

    def op():
        from scripts.fea_analysis import discover_solver

        return discover_solver(params.solver)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_prepare_fea",
    title="Prepare Whitelisted FEA Input",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_prepare_fea(params: CadStudioFeaPrepareInput) -> str:
    """Generate a versioned CalculiX .inp file from a structured FEA 1.0 request."""

    def op():
        from scripts.fea_analysis import build_calculix_input, validate_analysis

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        request = validate_analysis(input_path)
        if params.solver != "auto":
            request["solver"] = params.solver
        if request["solver"] == "elmer":
            return {
                "schemaVersion": "1.0",
                "status": "blocked",
                "stage": "generate_input",
                "checks": [],
                "artifacts": [],
                "manual_review_required": True,
                "retryable": False,
                "error_code": "fea_elmer_adapter_not_implemented",
                "message": "Elmer 安全输入适配器尚未实现；当前 prepare_fea 只生成 CalculiX .inp。",
            }
        output_dir.mkdir(parents=True, exist_ok=True)
        return build_calculix_input(request, output_dir / f"{request['analysisId']}.inp")

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_run_fea",
    title="Run Approved Local FEA Solver",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_run_fea(params: CadStudioFeaRunInput) -> str:
    """Run a structured FEA 1.0 request through an approved local solver without arbitrary command execution."""

    def op():
        from scripts.fea_analysis import run_analysis

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        return run_analysis(input_path, output_dir, timeout_seconds=params.timeout_seconds)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_run_fea_convergence",
    title="Run FEA Mesh Convergence Sequence",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_run_fea_convergence(params: CadStudioFeaConvergenceInput) -> str:
    """Run 3-8 approved CalculiX meshes and compare displacement/stress convergence."""

    def op():
        from scripts.fea_convergence import run_convergence_study

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        return run_convergence_study(
            input_path,
            output_dir,
            timeout_seconds_per_case=params.timeout_seconds_per_case,
        )

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_review_advanced_geometry",
    title="Review Advanced Geometry Plan",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_review_advanced_geometry(params: CadStudioAdvancedGeometryInput) -> str:
    """Validate advanced surface/mold plans and return pilot/blocked preflight evidence."""

    def op():
        from scripts.advanced_geometry import write_preflight_report

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_path = Path(os.path.expandvars(params.output_path)).expanduser().resolve()
        return write_preflight_report(input_path, output_path)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_create_ocp_loft",
    title="Create Restricted OCP Loft",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_create_ocp_loft(params: CadStudioOcpLoftInput) -> str:
    """Create and reopen a real parameterized OCP loft without arbitrary geometry code execution."""

    def op():
        from scripts.advanced_geometry_ocp import execute_ocp_loft

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        return execute_ocp_loft(input_path, output_dir)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="cadstudio_create_ocp_surface",
    title="Create Restricted OCP Advanced Surface",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def cadstudio_create_ocp_surface(params: CadStudioOcpSurfaceInput) -> str:
    """Create smooth loft, sweep, knit, or thicken geometry through a strict structured whitelist."""

    def op():
        from scripts.advanced_surface_ocp import execute_advanced_surface

        input_path = Path(os.path.expandvars(params.input_path)).expanduser().resolve()
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        return execute_advanced_surface(input_path, output_dir)

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="solidworks_connect",
    title="Connect to SolidWorks",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_connect(params: SolidWorksConnectInput = SolidWorksConnectInput()) -> str:
    """Connect to a running SolidWorks instance or start one, then return active document status."""

    def op():
        sw, model = connect_solidworks(wait_seconds=params.wait_seconds, visible=params.visible)
        return {
            "status": "ok",
            "revision": get_com_member(sw, "RevisionNumber"),
            "active_document": _model_summary(model) if model else None,
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_health_check",
    title="Check SolidWorks Automation Health",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_health_check(params: SolidWorksHealthCheckInput = SolidWorksHealthCheckInput()) -> str:
    """Check Python dependencies, SolidWorks COM registration, optional live connection, and Motion typelib."""

    def op():
        missing = missing_com_dependencies()
        checks: Dict[str, Any] = {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "missing_com_dependencies": missing,
            "solidworks_detected": solidworks_installed(),
            "server_path": str(SERVER_DIR / "server.py"),
        }
        if params.check_motion_type_library and not missing:
            _load_automation_modules()
            motion_tlb = ensure_motion_type_library(raise_on_error=False)
            checks["motion_type_library"] = motion_tlb
            checks["motion_type_library_ready"] = bool(motion_tlb)
        elif params.check_motion_type_library:
            checks["motion_type_library"] = None
            checks["motion_type_library_ready"] = False
        if params.start_solidworks and not missing:
            _load_automation_modules()
            sw, model = connect_solidworks(wait_seconds=1)
            checks["solidworks_revision"] = get_com_member(sw, "RevisionNumber")
            checks["active_document"] = _model_summary(model) if model else None
        issues = []
        if checks["missing_com_dependencies"]:
            issues.append("Missing Python COM dependencies.")
        if not checks["solidworks_detected"]:
            issues.append("SolidWorks COM registration or installation was not detected.")
        if params.check_motion_type_library and not checks.get("motion_type_library_ready"):
            issues.append("Motion Study type library was not found; rotary motor tools may fail.")
        return {
            "status": "ok" if not issues else "warning",
            "checks": checks,
            "issues": issues,
        }

    return _run_locked(op, params.response_format, load_automation=False)


@mcp.tool(
    name="solidworks_new_document",
    title="Create SolidWorks Document",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_new_document(params: SolidWorksNewDocumentInput) -> str:
    """Create a new part, assembly, or drawing document from a SolidWorks template."""

    def op():
        sw, _ = connect_solidworks(wait_seconds=1)
        model = new_document(sw, params.doc_type.value, template_path=params.template_path)
        return {"status": "ok", "document": _model_summary(model)}

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_create_basic_part",
    title="Create Basic SolidWorks Part",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_create_basic_part(params: SolidWorksCreateBasicPartInput) -> str:
    """Create a simple cylinder or box part with optional color and save path."""

    def op():
        sw, _ = connect_solidworks(wait_seconds=1)
        model = new_document(sw, "part")
        with sketch(model, params.plane_name) as sketch_name:
            if params.shape == BasicPartShape.CYLINDER:
                sketch_circle(model, 0.0, 0.0, mm(params.radius_mm))
            elif params.shape == BasicPartShape.BOX:
                sketch_rectangle(model, 0.0, 0.0, mm(params.width_mm), mm(params.height_mm))
            else:
                raise ValueError(f"Unsupported shape: {params.shape}")
        feature = extrude_boss(model, sketch_name, mm(params.depth_mm))
        appearance_ok = None
        if params.color:
            appearance_ok = set_document_appearance(model, params.color)
        save_ok = None
        if params.output_path:
            save_ok = save_document(model, params.output_path)
        model.ForceRebuild3(False)
        return {
            "status": "ok",
            "shape": params.shape.value,
            "feature_created": feature is not None,
            "feature_name": get_com_member(feature, "Name") if feature else None,
            "appearance_ok": appearance_ok,
            "saved": save_ok,
            "output_path": str(Path(os.path.expandvars(params.output_path)).expanduser().resolve()) if params.output_path else None,
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_open_document",
    title="Open SolidWorks Document",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_open_document(params: SolidWorksOpenDocumentInput) -> str:
    """Open a SolidWorks document by absolute path and make it available for later MCP tools."""

    def op():
        sw, _ = connect_solidworks(wait_seconds=1)
        model = open_document(
            sw,
            params.path,
            read_only=params.read_only,
            silent=params.silent,
            raise_on_error=True,
        )
        return {"status": "ok", "document": _model_summary(model)}

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_add_component",
    title="Add Component To Active Assembly",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_add_component(params: SolidWorksAddComponentInput) -> str:
    """Add an existing part/subassembly to the active assembly, optionally fixing it."""

    def op():
        sw, asm = _active_assembly_required()
        component = assembly_add_component(
            asm,
            params.path,
            mm(params.x_mm),
            mm(params.y_mm),
            mm(params.z_mm),
            config_name=params.config_name,
            sw=sw,
        )
        if component is None:
            raise RuntimeError(f"AddComponent4 failed: {params.path}")
        resolve_component(component)
        fixed = None
        if params.fix_component:
            fixed = _set_component_fixed(asm, component, fixed=True)
        return {
            "status": "ok",
            "component": _component_summary(component),
            "fixed": fixed,
            "component_count": len(get_components(asm)),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_set_component_fixed",
    title="Fix Or Float Assembly Component",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_set_component_fixed(params: SolidWorksSetComponentFixedInput) -> str:
    """Fix or float a component in the active assembly by component name keyword."""

    def op():
        _sw, asm = _active_assembly_required()
        component = find_component_by_name(asm, params.component_keyword)
        ok = _set_component_fixed(asm, component, fixed=params.fixed)
        return {
            "status": "ok" if ok else "failed",
            "fixed": params.fixed,
            "component": _component_summary(component),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_save_document",
    title="Save Active SolidWorks Document",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_save_document(params: SolidWorksSaveDocumentInput = SolidWorksSaveDocumentInput()) -> str:
    """Save the active SolidWorks document, optionally using Save As."""

    def op():
        _sw, model = _active_model_required()
        success = save_document(model, params.path)
        return {
            "status": "ok" if success else "failed",
            "success": bool(success),
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_close_documents",
    title="Close SolidWorks Documents",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_close_documents(params: SolidWorksCloseDocumentsInput = SolidWorksCloseDocumentsInput()) -> str:
    """Close the active document or all documents in the current SolidWorks session."""

    def op():
        sw, model = _active_model_required()
        if params.close_all:
            sw.CloseAllDocuments(bool(params.save_changes))
            return {"status": "ok", "closed": "all", "save_changes": params.save_changes}
        title = get_com_member(model, "GetTitle")
        sw.CloseDoc(title)
        return {"status": "ok", "closed": title}

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_add_coincident_mate",
    title="Add Plane Coincident Mate",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_add_coincident_mate(params: SolidWorksPlaneCoincidentMateInput) -> str:
    """Add a coincident mate between named planes/features inside two assembly components."""

    def op():
        _sw, asm = _active_assembly_required()
        component_a = find_component_by_name(asm, params.component_a_keyword)
        component_b = find_component_by_name(asm, params.component_b_keyword)
        entity_a = get_component_feature_entity(component_a, params.feature_a_name)
        entity_b = get_component_feature_entity(component_b, params.feature_b_name)
        select_entities_for_mate(asm, entity_a, entity_b, mark=1)
        mate = add_mate5_checked(
            asm,
            SW_MATE_COINCIDENT,
            name=params.mate_name,
        )
        return {
            "status": "ok",
            "mate_created": mate is not None,
            "mate_name": params.mate_name or (get_com_member(mate, "Name") if mate else None),
            "component_a": get_com_member(component_a, "Name2"),
            "component_b": get_com_member(component_b, "Name2"),
            "mate_features": collect_mate_feature_summary(asm),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_add_distance_mate",
    title="Add Plane Distance Mate",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_add_distance_mate(params: SolidWorksPlaneDistanceMateInput) -> str:
    """Add a distance mate between named planes/features inside two assembly components."""

    def op():
        _sw, asm = _active_assembly_required()
        component_a = find_component_by_name(asm, params.component_a_keyword)
        component_b = find_component_by_name(asm, params.component_b_keyword)
        entity_a = get_component_feature_entity(component_a, params.feature_a_name)
        entity_b = get_component_feature_entity(component_b, params.feature_b_name)
        select_entities_for_mate(asm, entity_a, entity_b, mark=1)
        mate = add_mate5_checked(
            asm,
            SW_MATE_DISTANCE,
            distance=mm(params.distance_mm),
            name=params.mate_name,
        )
        return {
            "status": "ok",
            "mate_created": mate is not None,
            "mate_name": params.mate_name or (get_com_member(mate, "Name") if mate else None),
            "distance_mm": params.distance_mm,
            "component_a": get_com_member(component_a, "Name2"),
            "component_b": get_com_member(component_b, "Name2"),
            "mate_features": collect_mate_feature_summary(asm),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_add_concentric_mate",
    title="Add Concentric Mate By Cylinders",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_add_concentric_mate(params: SolidWorksConcentricMateInput) -> str:
    """Add a concentric mate between two components by locating matching cylinder faces."""

    def op():
        _sw, asm = _active_assembly_required()
        component_a = find_component_by_name(asm, params.component_a_keyword)
        component_b = find_component_by_name(asm, params.component_b_keyword)
        mate = add_concentric_mate_by_cylinders(
            asm,
            component_a,
            component_b,
            radius_a=(mm(params.radius_a_min_mm), mm(params.radius_a_max_mm) if params.radius_a_max_mm is not None else None),
            radius_b=(mm(params.radius_b_min_mm), mm(params.radius_b_max_mm) if params.radius_b_max_mm is not None else None),
            name=params.mate_name,
            lock_rotation=params.lock_rotation,
        )
        return {
            "status": "ok",
            "mate_created": mate is not None,
            "mate_name": params.mate_name or (get_com_member(mate, "Name") if mate else None),
            "lock_rotation": params.lock_rotation,
            "component_a": get_com_member(component_a, "Name2"),
            "component_b": get_com_member(component_b, "Name2"),
            "mate_features": collect_mate_feature_summary(asm),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_set_appearance",
    title="Set SolidWorks Appearance",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_set_appearance(params: SolidWorksSetAppearanceInput) -> str:
    """Set appearance color on the active document or an assembly component."""

    def op():
        _sw, model = _active_model_required()
        if params.target == AppearanceTarget.DOCUMENT:
            ok = set_document_appearance(model, params.color)
            component = None
        elif params.target == AppearanceTarget.COMPONENT:
            if not params.component_keyword:
                raise ValueError("component_keyword is required when target=component.")
            if int(get_com_member(model, "GetType")) != 2:
                raise RuntimeError("Component appearance requires an active assembly.")
            component = find_component_by_name(model, params.component_keyword)
            ok = set_component_appearance(component, params.color)
        else:
            raise ValueError(f"Unsupported target: {params.target}")
        model.ForceRebuild3(False)
        return {
            "status": "ok" if ok else "failed",
            "target": params.target.value,
            "color": params.color,
            "component": _component_summary(component) if component else None,
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_export_active",
    title="Export Active SolidWorks Document",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_export_active(params: SolidWorksExportInput) -> str:
    """Export the active SolidWorks document to STEP, STL, IGES, Parasolid, PDF, or DXF."""

    def op():
        _sw, model = _active_model_required()
        exporters = {
            ExportFormat.STEP: lambda: export_to_step(model, params.output_path),
            ExportFormat.STL: lambda: export_to_stl(model, params.output_path, quality=params.stl_quality),
            ExportFormat.IGES: lambda: export_to_iges(model, params.output_path),
            ExportFormat.PARASOLID: lambda: export_to_parasolid(model, params.output_path),
            ExportFormat.PDF: lambda: export_to_pdf(model, params.output_path),
            ExportFormat.DXF: lambda: export_to_dxf(model, params.output_path),
        }
        success = bool(exporters[params.export_format]())
        return {
            "status": "ok" if success else "failed",
            "success": success,
            "output_path": str(Path(os.path.expandvars(params.output_path)).expanduser().resolve()),
            "format": params.export_format.value,
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_inspect_configurations",
    title="Inspect SolidWorks Configurations",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def solidworks_inspect_configurations(
    params: SolidWorksConfigurationInspectInput = SolidWorksConfigurationInspectInput(),
) -> str:
    """Inspect configuration names and the active configuration without modifying the document."""

    def op():
        _sw, model = _active_model_required()
        result = inspect_configurations(model)
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_create_configuration",
    title="Create SolidWorks Configuration",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def solidworks_create_configuration(params: SolidWorksConfigurationCreateInput) -> str:
    """Create, optionally activate, rebuild, save, and read back a configuration."""

    def op():
        _sw, model = _active_model_required()
        result = create_configuration(
            model,
            params.configuration_name,
            comment=params.comment,
            alternate_name=params.alternate_name,
            options=params.options,
            if_exists=params.if_exists,
            activate=params.activate,
            rebuild=params.rebuild,
            save=params.save,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_activate_configuration",
    title="Activate SolidWorks Configuration",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def solidworks_activate_configuration(params: SolidWorksConfigurationActivateInput) -> str:
    """Activate an existing configuration and verify the active configuration by readback."""

    def op():
        _sw, model = _active_model_required()
        result = activate_configuration(
            model,
            params.configuration_name,
            rebuild=params.rebuild,
            save=params.save,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_update_dimension",
    title="Update Named SolidWorks Dimension",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def solidworks_update_dimension(params: SolidWorksDimensionUpdateInput) -> str:
    """Update an exact named dimension, rebuild, optionally save, and return before/after evidence."""

    def op():
        _sw, model = _active_model_required()
        result = update_dimension_mm(
            model,
            params.dimension_name,
            params.value_mm,
            configuration_mode=params.configuration_mode,
            configuration_names=params.configuration_names,
            rebuild=params.rebuild,
            save=params.save,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_set_custom_properties",
    title="Set SolidWorks Custom Properties",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def solidworks_set_custom_properties(params: SolidWorksCustomPropertiesInput) -> str:
    """Set and read back file-level or configuration-level custom properties."""

    def op():
        _sw, model = _active_model_required()
        result = set_custom_properties(
            model,
            params.properties,
            configuration_name=params.configuration_name,
            property_type=params.property_type,
            save=params.save,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_batch_export_files",
    title="Batch Export SolidWorks Files",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
def solidworks_batch_export_files(params: SolidWorksBatchExportInput) -> str:
    """Export multiple local SolidWorks files and verify every output was produced this run."""

    def op():
        sw, _model = connect_solidworks(wait_seconds=1)
        return batch_export_formats(
            sw,
            params.file_paths,
            params.output_dir,
            params.formats,
            overwrite=params.overwrite,
            close_documents=params.close_documents,
            stl_quality=params.stl_quality,
        )

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_export_assembly_bom",
    title="Export Reviewed Assembly BOM CSV",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
def solidworks_export_assembly_bom(params: SolidWorksBomExportInput) -> str:
    """Export a component/property BOM CSV; the result always requires native BOM review."""

    def op():
        _sw, model = _active_assembly_required()
        result = export_assembly_bom_csv(
            model,
            params.output_path,
            include_excluded=params.include_excluded,
            overwrite=params.overwrite,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_pack_and_go",
    title="Native SolidWorks Pack and Go",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
def solidworks_pack_and_go_tool(params: SolidWorksPackAndGoInput) -> str:
    """Run the native Pack and Go API into a protected output directory."""

    def op():
        _sw, model = _active_model_required()
        result = pack_and_go(
            model,
            params.output_dir,
            include_drawings=params.include_drawings,
            include_simulation_results=params.include_simulation_results,
            include_toolbox_components=params.include_toolbox_components,
            include_suppressed=params.include_suppressed,
            flatten=params.flatten,
            overwrite=params.overwrite,
            fallback_policy=params.fallback_policy,
        )
        result["document"] = _model_summary(model)
        return result

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_review_active",
    title="Review Active SolidWorks Document",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_review_active(params: SolidWorksReviewInput) -> str:
    """Export preview BMPs and a JSON review report for the active SolidWorks document."""

    def op():
        _sw, model = _active_model_required()
        report, report_path = run_review(model, params.output_dir, basename=params.basename)
        return {
            "status": "ok",
            "report_path": report_path,
            "evaluation": report.get("evaluation"),
            "checks": report.get("checks"),
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


def _drawing_report_path(output_dir: Path, basename: str) -> Path:
    """@brief 返回工程图子技能报告路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{basename}.json"


@mcp.tool(
    name="solidworks_generate_drawing",
    title="Generate SolidWorks Engineering Drawing",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_generate_drawing(params: SolidWorksGenerateDrawingInput) -> str:
    """按 DrawingSpec v1 创建工程图、PDF、预览和机器审视报告。"""

    def op():
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        drawing_path = output_dir / params.drawing_filename
        pdf_path = drawing_path.with_suffix(".pdf")
        report_path = output_dir / f"{drawing_path.stem}_review_report.json"
        if not params.overwrite and any(path.exists() for path in (drawing_path, pdf_path, report_path)):
            raise ValueError("输出文件已存在；请更换 output_dir、设置 overwrite=true，或保留旧交付物并另起运行目录")

        spec_validation = drawing_validate_spec(params.spec_path)
        if spec_validation.get("status") == "blocked":
            return spec_validation
        spec = spec_validation["spec"]
        source_path = Path(os.path.expandvars(str(spec["sourceModel"]))).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"DrawingSpec.sourceModel 不存在: {source_path}")
        sw, _active = connect_solidworks(wait_seconds=1, visible=True)
        source_model = open_document(sw, str(source_path), read_only=False, silent=True, raise_on_error=True)
        drawing_model = new_document(sw, "drawing")
        generation = drawing_generate_from_spec(
            drawing_model,
            spec,
            str(source_path),
            template_candidates=spec.get("templateCandidates"),
        )
        if generation.get("status") in {"blocked", "failed"}:
            return generation
        if not save_document(drawing_model, str(drawing_path)):
            raise RuntimeError(f"工程图保存失败: {drawing_path}")
        pdf_ok = drawing_export_sheet_to_pdf(drawing_model, str(pdf_path), sw_app=sw)
        previews = drawing_save_review_previews(
            drawing_model,
            output_dir / "previews",
            basename=drawing_path.stem,
            views=("front", "top", "right"),
        )
        preview_evidence = [drawing_inspect_bmp_preview(path) for path in previews]
        geometry_evidence = collect_geometry_measurements(source_model) if spec.get("holeRequirements") else None
        review = drawing_review_artifacts(
            spec,
            structure=generation.get("structure"),
            pdf_path=pdf_path if pdf_ok and pdf_path.is_file() else None,
            preview_evidence=preview_evidence,
            model_evidence=geometry_evidence,
        )
        payload = {
            "status": review.get("status", "review_required"),
            "capability": "solidworks-engineering-drawing",
            "sourceModel": str(source_path),
            "outputs": {
                "slddrw": {"path": str(drawing_path), "exists": drawing_path.is_file(), "size_bytes": drawing_path.stat().st_size if drawing_path.is_file() else 0},
                "pdf": {"path": str(pdf_path), "exists": pdf_path.is_file(), "size_bytes": pdf_path.stat().st_size if pdf_path.is_file() else 0},
                "previews": preview_evidence,
            },
            "generation": generation,
            "review": review,
            "manual_review_required": bool(review.get("manual_review_required", True)),
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["reportPath"] = str(report_path)
        return payload

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_review_drawing",
    title="Review SolidWorks Engineering Drawing",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_review_drawing(params: SolidWorksReviewDrawingInput) -> str:
    """打开工程图并执行 DrawingSpec、布局、尺寸、孔槽和 PDF 证据审视。"""

    def op():
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        report_path = _drawing_report_path(output_dir, params.basename)
        sw, _active = connect_solidworks(wait_seconds=1, visible=True)
        drawing_model = open_document(sw, params.drawing_path, read_only=True, silent=True, raise_on_error=True)
        structure = drawing_inspect_structure(drawing_model)
        previews = drawing_save_review_previews(
            drawing_model,
            output_dir / "previews",
            basename=params.basename,
            views=("front", "top", "right"),
        )
        preview_evidence = [drawing_inspect_bmp_preview(path) for path in previews]
        review = drawing_review_artifacts(
            params.spec_path,
            structure=structure,
            pdf_path=params.pdf_path,
            preview_evidence=preview_evidence,
        )
        payload = {"status": review.get("status"), "drawingPath": str(Path(params.drawing_path).resolve()), "structure": structure, "previews": preview_evidence, "review": review, "manual_review_required": bool(review.get("manual_review_required", True))}
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["reportPath"] = str(report_path)
        return payload

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_inspect_drawing",
    title="Inspect SolidWorks Drawing Structure",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_inspect_drawing(params: SolidWorksInspectDrawingInput) -> str:
    """只读读取工程图页、视图、尺寸、注释和表格结构，并生成预览证据。"""

    def op():
        output_dir = Path(os.path.expandvars(params.output_dir)).expanduser().resolve()
        report_path = _drawing_report_path(output_dir, params.basename)
        sw, _active = connect_solidworks(wait_seconds=1, visible=True)
        drawing_model = open_document(sw, params.drawing_path, read_only=True, silent=True, raise_on_error=True)
        structure = drawing_inspect_structure(drawing_model, paper_size_hint=params.paper_size_hint)
        previews = drawing_save_review_previews(
            drawing_model,
            output_dir / "previews",
            basename=params.basename,
            views=("front", "top", "right"),
        )
        payload = {"status": structure.get("status"), "drawingPath": str(Path(params.drawing_path).resolve()), "structure": structure, "previews": [drawing_inspect_bmp_preview(path) for path in previews], "manual_review_required": True}
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["reportPath"] = str(report_path)
        return payload

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_create_hole_feature",
    title="Create SolidWorks Hole or Semicircular Slot",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_create_hole_feature(params: SolidWorksHoleFeatureInput) -> str:
    """Create a constrained blind/through/compound hole or semicircular slot on the active part."""

    def op():
        _sw, model = _active_part_required()
        center = (mm(params.center_x_mm), mm(params.center_y_mm))
        common = {"plane_name": params.plane_name, "name": params.feature_name}
        if params.feature_kind == HoleFeatureKind.BLIND:
            if params.depth_mm is None:
                raise ValueError("depth_mm is required for a blind hole")
            evidence = create_blind_hole(model, center, mm(params.diameter_mm), mm(params.depth_mm), **common)
        elif params.feature_kind == HoleFeatureKind.THROUGH:
            evidence = create_through_hole(model, center, mm(params.diameter_mm), **common)
        elif params.feature_kind == HoleFeatureKind.COUNTERBORE:
            if params.secondary_diameter_mm is None or params.secondary_depth_mm is None:
                raise ValueError("secondary_diameter_mm and secondary_depth_mm are required for a counterbore")
            evidence = create_counterbore_hole(
                model,
                center,
                mm(params.diameter_mm),
                mm(params.secondary_diameter_mm),
                mm(params.secondary_depth_mm),
                **common,
            )
        elif params.feature_kind == HoleFeatureKind.COUNTERSINK:
            if params.secondary_diameter_mm is None:
                raise ValueError("secondary_diameter_mm is required for a countersink")
            evidence = create_countersink_hole(
                model,
                center,
                mm(params.diameter_mm),
                mm(params.secondary_diameter_mm),
                included_angle_deg=params.included_angle_deg,
                **common,
            )
        else:
            if params.slot_end_x_mm is None or params.slot_end_y_mm is None:
                raise ValueError("slot_end_x_mm and slot_end_y_mm are required for a semicircular slot")
            evidence = create_semicircular_slot(
                model,
                center,
                (mm(params.slot_end_x_mm), mm(params.slot_end_y_mm)),
                width=mm(params.diameter_mm),
                depth=mm(params.depth_mm) if params.depth_mm is not None else 0.0,
                **common,
            )
        get_com_member(model, "ForceRebuild3", False)
        return {"status": "ok", "feature_evidence": evidence, "document": _model_summary(model)}

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_inspect_hole_features",
    title="Inspect SolidWorks Hole Geometry",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_inspect_hole_features(params: SolidWorksHoleInspectionInput = SolidWorksHoleInspectionInput()) -> str:
    """Read B-Rep holes, compound segments, slot arcs, and optional hole-position acceptance."""

    def op():
        _sw, model = _active_part_required()
        measurements = collect_geometry_measurements(model)
        expected = [item.model_dump() for item in params.expected_holes]
        position_checks = None
        if expected:
            position_checks = validate_hole_positions(
                measurements,
                expected,
                position_tolerance_mm=params.position_tolerance_mm,
                diameter_tolerance_mm=params.diameter_tolerance_mm,
            )
        return {
            "status": "ok" if position_checks is None or position_checks["status"] == "pass" else "failed",
            "measurements": measurements,
            "position_checks": position_checks,
            "document": _model_summary(model),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_add_rotary_motor",
    title="Add Motion Study Rotary Motor",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def solidworks_add_rotary_motor(params: SolidWorksRotaryMotorInput) -> str:
    """Create a Motion Study on the active assembly and add a constant-speed rotary motor by cylinder faces."""

    def op():
        _sw, asm = _active_model_required()
        if int(get_com_member(asm, "GetType")) != 2:
            raise RuntimeError("Active document must be an assembly (.SLDASM) to add a Motion Study motor.")
        shaft_comp = find_component_by_name(asm, params.shaft_component_keyword)
        rotor_comp = find_component_by_name(asm, params.rotor_component_keyword)
        study = create_motion_study(
            asm,
            name=params.study_name,
            duration=params.duration_seconds,
        )
        feature = add_constant_speed_rotary_motor_by_cylinders(
            study,
            shaft_component=shaft_comp,
            rotor_component=rotor_comp,
            shaft_radius=(mm(params.shaft_radius_min_mm), mm(params.shaft_radius_max_mm) if params.shaft_radius_max_mm is not None else None),
            rotor_radius=(mm(params.rotor_radius_min_mm), mm(params.rotor_radius_max_mm) if params.rotor_radius_max_mm is not None else None),
            rpm=params.rpm,
            name=params.motor_name,
        )
        calculated = None
        if params.calculate:
            calculated = calculate_and_play(study, play=params.play)
        return {
            "status": "ok",
            "study_name": params.study_name,
            "motor_name": params.motor_name,
            "motor_feature_created": feature is not None,
            "calculated": calculated,
            "rpm": params.rpm,
            "shaft_component": get_com_member(shaft_comp, "Name2"),
            "rotor_component": get_com_member(rotor_comp, "Name2"),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_inspect_motion_studies",
    title="Inspect Motion Studies",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_inspect_motion_studies(params: SolidWorksMotionAuditInput = SolidWorksMotionAuditInput()) -> str:
    """Inspect Motion Study definitions, motor/force counts, and whether results are stale."""

    def op():
        _sw, asm = _active_assembly_required()
        return {
            "status": "ok",
            "motion": collect_motion_study_summary(asm),
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


@mcp.tool(
    name="solidworks_validate_motion_study",
    title="Validate Motion Study Delivery Evidence",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def solidworks_validate_motion_study(params: SolidWorksMotionValidationInput = SolidWorksMotionValidationInput()) -> str:
    """Enforce Motion Study type, duration, motor count, result presence, and freshness requirements."""

    def op():
        _sw, asm = _active_assembly_required()
        audit = validate_motion_studies(
            asm,
            study_name=params.study_name,
            expected_study_type=params.expected_study_type,
            minimum_duration_seconds=params.minimum_duration_seconds,
            minimum_motor_count=params.minimum_motor_count,
            require_results=params.require_results,
        )
        return {
            "status": audit["validation"]["status"],
            "motion": audit,
            "document": _model_summary(asm),
        }

    return _run_locked(op, params.response_format)


def main() -> None:
    """Run the SolidWorks MCP server over stdio."""
    if sys.stdout is not _MCP_STDOUT:
        sys.stdout = _MCP_STDOUT
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
