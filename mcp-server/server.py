"""
SolidWorks MCP Server.

This stdio MCP server wraps the existing solidworks-automation skill scripts so
MCP clients can operate a local Windows SolidWorks desktop session through
Python COM. It intentionally serializes all tool calls because SolidWorks COM is
a single-user desktop automation surface.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
from contextlib import redirect_stdout
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator


SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from sw_connect import (  # noqa: E402
    connect_solidworks,
    create_empty_dispatch_variant,
    get_com_member,
    mm,
    new_document,
    open_document,
    save_document,
)
from sw_preflight import missing_com_dependencies, solidworks_installed  # noqa: E402
from sw_part import (  # noqa: E402
    extrude_boss,
    sketch,
    sketch_circle,
    sketch_rectangle,
)
from sw_appearance import set_component_appearance, set_document_appearance  # noqa: E402
from sw_export import (  # noqa: E402
    export_to_dxf,
    export_to_iges,
    export_to_parasolid,
    export_to_pdf,
    export_to_step,
    export_to_stl,
)
from sw_review import run_review  # noqa: E402
from sw_assembly import (  # noqa: E402
    SW_MATE_COINCIDENT,
    SW_MATE_DISTANCE,
    add_component as assembly_add_component,
    add_concentric_mate_by_cylinders,
    add_mate5_checked,
    collect_mate_feature_summary,
    find_component_by_name,
    get_component_feature_entity,
    get_components,
    resolve_component,
    select_entities_for_mate,
)
from sw_motion import (  # noqa: E402
    add_constant_speed_rotary_motor_by_cylinders,
    calculate_and_play,
    create_motion_study,
    ensure_motion_type_library,
)

try:
    import pythoncom
except Exception:  # pragma: no cover - surfaced by preflight when tools run
    pythoncom = None


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


class BasicPartShape(str, Enum):
    """Low-risk basic part primitives exposed over MCP."""

    CYLINDER = "cylinder"
    BOX = "box"


class AppearanceTarget(str, Enum):
    """Supported appearance targets."""

    DOCUMENT = "document"
    COMPONENT = "component"


class BaseInput(BaseModel):
    """Common Pydantic config."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class SolidWorksConnectInput(BaseInput):
    """Input for connecting to SolidWorks."""

    visible: bool = Field(default=True, description="Whether a newly started SolidWorks instance should be visible.")
    wait_seconds: int = Field(default=5, ge=0, le=60, description="Seconds to wait after starting SolidWorks.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


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


class SolidWorksReviewInput(BaseInput):
    """Input for exporting previews and a review report."""

    output_dir: str = Field(..., min_length=1, description="Directory for BMP previews and JSON report.")
    basename: str = Field(default="mcp_review", min_length=1, max_length=80, description="Output filename prefix.")
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


def _run_locked(operation, response_format: ResponseFormat):
    """Run one SolidWorks COM operation under the global lock."""
    with _sw_lock:
        try:
            _coinitialize()
            with redirect_stdout(sys.stderr):
                payload = operation()
            return _result(payload, response_format)
        except Exception as exc:
            return _tool_error(exc, response_format)


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
        checks: Dict[str, Any] = {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "missing_com_dependencies": missing_com_dependencies(),
            "solidworks_detected": solidworks_installed(),
            "server_path": str(SERVER_DIR / "server.py"),
        }
        if params.check_motion_type_library:
            motion_tlb = ensure_motion_type_library(raise_on_error=False)
            checks["motion_type_library"] = motion_tlb
            checks["motion_type_library_ready"] = bool(motion_tlb)
        if params.start_solidworks:
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

    return _run_locked(op, params.response_format)


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
        _sw, asm = _active_assembly_required()
        component = assembly_add_component(
            asm,
            params.path,
            mm(params.x_mm),
            mm(params.y_mm),
            mm(params.z_mm),
            config_name=params.config_name,
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


def main() -> None:
    """Run the SolidWorks MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
