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
    get_com_member,
    mm,
    new_document,
    open_document,
    save_document,
)
from sw_export import (  # noqa: E402
    export_to_dxf,
    export_to_iges,
    export_to_parasolid,
    export_to_pdf,
    export_to_step,
    export_to_stl,
)
from sw_review import run_review  # noqa: E402
from sw_assembly import find_component_by_name  # noqa: E402
from sw_motion import (  # noqa: E402
    add_constant_speed_rotary_motor_by_cylinders,
    calculate_and_play,
    create_motion_study,
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


class BaseInput(BaseModel):
    """Common Pydantic config."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class SolidWorksConnectInput(BaseInput):
    """Input for connecting to SolidWorks."""

    visible: bool = Field(default=True, description="Whether a newly started SolidWorks instance should be visible.")
    wait_seconds: int = Field(default=5, ge=0, le=60, description="Seconds to wait after starting SolidWorks.")
    response_format: ResponseFormat = Field(default=ResponseFormat.JSON, description="Return format.")


class SolidWorksNewDocumentInput(BaseInput):
    """Input for creating a new document."""

    doc_type: DocType = Field(default=DocType.PART, description="Document type to create.")
    template_path: Optional[str] = Field(default=None, description="Optional explicit SolidWorks template path.")
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


def _model_summary(model) -> Dict[str, Any]:
    """Return a compact active document summary."""
    return {
        "title": get_com_member(model, "GetTitle"),
        "path": get_com_member(model, "GetPathName"),
        "type": get_com_member(model, "GetType"),
    }


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
