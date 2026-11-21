"""SolidWorks 2026 真机预览验收。使用本轮临时零件和遮挡窗口。"""

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from PIL import Image
import win32con
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.desktop.cad_workbench.queue_worker import _solidworks_preview_environment
from scripts.sw_connect import get_com_member, mm, new_document
from scripts.sw_live_preview import preview_checkpoint
from scripts.sw_part import extrude_boss, extrude_cut, sketch, sketch_circle, sketch_rectangle
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch


def main():
    import tkinter as tk

    job = {
        "id": "job-live-preview",
        "runId": "run-live-preview",
        "uiConfig": {"cadRuntime": {"application": "solidworks", "localCadAutomation": True}},
    }
    with tempfile.TemporaryDirectory(prefix="solidworks_live_preview_") as directory:
        minimized_frame_cleared = False
        env = os.environ.copy()
        with _solidworks_preview_environment(env, Path(directory), job), patch.dict(os.environ, env):
            frame = Path(os.environ["CAD_STUDIO_SW_PREVIEW_PATH"])
            with SolidWorksSession(version=2026, visible=True) as session:
                revision = str(get_com_member(session.sw, "RevisionNumber"))
                assert revision.startswith("34."), revision
                before = {get_com_member(doc, "GetTitle") for doc in session._documents()}
                model = session.new_part()
                with sketch(model, "Front Plane") as base:
                    sketch_rectangle(model, 0, 0, mm(60), mm(40))
                    assert fully_define_sketch(model)["status"] == "pass"
                sketch_hash = sha256(frame.read_bytes()).hexdigest()
                assert extrude_boss(model, base, mm(8), direction=False) is not None
                model.ShowNamedView2("", 7)
                model.ViewZoomtofit2()
                preview_checkpoint(model)
                solid_hash = sha256(frame.read_bytes()).hexdigest()
                assert sketch_hash != solid_hash

                hwnd = int(get_com_member(get_com_member(model, "ActiveView"), "GetViewHWndx64"))
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                center = ((left + right) // 2, (top + bottom) // 2)
                overlay = tk.Tk()
                try:
                    overlay.overrideredirect(True)
                    overlay.configure(bg="#ff00ff")
                    overlay.attributes("-topmost", True)
                    overlay.geometry(f"280x220{center[0] - 140:+d}{center[1] - 110:+d}")
                    overlay.update()
                    assert win32process.GetWindowThreadProcessId(win32gui.WindowFromPoint(center))[1] == os.getpid()
                    assert os.getpid() != session.connection_info["process_id"]
                    preview_checkpoint(model)
                    with Image.open(frame) as image:
                        pixels = image.convert("RGB").tobytes()
                        assert not any(r > 235 and g < 30 and b > 235 for r, g, b in zip(pixels[::3], pixels[1::3], pixels[2::3]))
                finally:
                    overlay.destroy()

                if session.connection_info["started_by_cad_studio"]:
                    frame_hwnd = int(get_com_member(get_com_member(session.sw, "Frame"), "GetHWndx64"))
                    try:
                        win32gui.ShowWindow(frame_hwnd, win32con.SW_MINIMIZE)
                        assert win32gui.IsIconic(frame_hwnd)
                        preview_checkpoint(model)
                        assert not frame.exists()
                        minimized_frame_cleared = True
                    finally:
                        win32gui.ShowWindow(frame_hwnd, win32con.SW_RESTORE)
                    preview_checkpoint(model)
                    assert frame.exists()

                foreign = new_document(session.sw, doc_type="part")
                try:
                    assert get_com_member(session.sw.ActiveDoc, "GetTitle") == get_com_member(foreign, "GetTitle")
                    preview_checkpoint(model)
                    assert not frame.exists(), "切换到其他文档后必须清除上一帧"
                finally:
                    session.sw.CloseDoc(get_com_member(foreign, "GetTitle"))

                with sketch(model, "Front Plane") as hole:
                    sketch_circle(model, 0, 0, mm(3))
                    assert fully_define_sketch(model)["status"] == "pass"
                assert extrude_cut(model, hole, 0, direction=True) is not None
                cut_hash = sha256(frame.read_bytes()).hexdigest()
                assert cut_hash != solid_hash
                session.close(model)
                assert not frame.exists()
                assert {get_com_member(doc, "GetTitle") for doc in session._documents()} == before
        assert not frame.exists()
    print(json.dumps({"status": "pass", "revision": revision, "frames": [sketch_hash, solid_hash, cut_hash],
                      "foreign_window_pixels": 0, "foreign_document_clears_frame": True, "frame_removed_on_close": True,
                      "minimized_frame_cleared": minimized_frame_cleared}))


if __name__ == "__main__":
    main()
