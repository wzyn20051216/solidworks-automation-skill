"""Serialize the new read-only CLI operations that share a SolidWorks instance."""
from pathlib import Path
import tempfile

try:
    from .sw_connect import _LaunchGuard
except ImportError:
    from sw_connect import _LaunchGuard


class SolidWorksReadGuard(_LaunchGuard):
    """A separate cross-process mutex; it does not protect other clients or the UI."""

    def __init__(self):
        super().__init__(name="CADStudio.SolidWorks.ReadOperations.v1")
        self.path = Path(tempfile.gettempdir()) / "cad-studio-solidworks-read-operations.lock"
