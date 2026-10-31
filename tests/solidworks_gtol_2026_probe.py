"""SW2026 新版 GTol 原生对象隔离探针，不构成完整工程图验收。"""
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import get_com_member
from scripts.sw_session import SolidWorksSession
from scripts import sw_drawing


def main():
    path = Path(tempfile.mkdtemp(prefix="sw_gtol_2026_probe_")) / "probe.slddrw"
    with SolidWorksSession(version=2026, visible=True) as session:
        model = session.new_drawing()
        symbol = get_com_member(model, "InsertGtol")
        if symbol is None:
            raise RuntimeError("无法插入 GTol")
        print("format", get_com_member(symbol, "GetFormat"), "convertible", get_com_member(symbol, "CanConvertFormat"), flush=True)
        if get_com_member(symbol, "CanConvertFormat"):
            print("conversion", get_com_member(symbol, "ConvertFormat"), flush=True)
        print("format after", get_com_member(symbol, "GetFormat"), flush=True)
        print("add frame", get_com_member(symbol, "AddFrame"), flush=True)
        frame = get_com_member(symbol, "GetFrame", 2)
        xml = ("<GtolFrame><ToleranceSymbol>IGTOL-POSI</ToleranceSymbol>"
               "<ToleranceRangeInfo><PrimaryToleranceValue>0.2</PrimaryToleranceValue>"
               "<PrimaryRangeSymbol>phi</PrimaryRangeSymbol></ToleranceRangeInfo>"
               "<DatumCompartment><DatumDetail><DatumLetter>A</DatumLetter></DatumDetail></DatumCompartment>"
               "<DatumCompartment><DatumDetail><DatumLetter>B</DatumLetter></DatumDetail></DatumCompartment>"
               "<DatumCompartment><DatumDetail><DatumLetter>C</DatumLetter></DatumDetail></DatumCompartment></GtolFrame>")
        print("set xml", get_com_member(frame, "SetSymbolXml", xml), flush=True)
        annotation = get_com_member(symbol, "GetAnnotation")
        print("position", get_com_member(annotation, "SetPosition", .1, .1, 0), flush=True)
        print("frame count", get_com_member(symbol, "GetFrameCount"), flush=True)
        for index in (0, 1, 2):
            try:
                frame = get_com_member(symbol, "GetFrame", index)
                print("frame", index, bool(frame), flush=True)
                if frame:
                    print("xml", repr(get_com_member(frame, "GetSymbolXml")), flush=True)
            except Exception as error:
                print("error", index, repr(error), flush=True)
        if not session.save(model, str(path)):
            raise RuntimeError("保存探针工程图失败")
        session.close(model=model)
        model = session.open(str(path), read_only=True, silent=True)
        view = get_com_member(model, "GetFirstView")
        found = []
        while view:
            for existing in get_com_member(view, "GetGTols") or ():
                records = sw_drawing._MODULE._gtol_frame_records(existing, int(get_com_member(existing, "GetFrameCount")))
                print("collected evidence", records, flush=True)
                assert any(item["symbols"] == ["IGTOL-POSI"] and item["values"] == ["0.2", "A", "B", "C"] for item in records)
                for index in range(1, int(get_com_member(existing, "GetFrameCount")) + 1):
                    frame = get_com_member(existing, "GetFrame", index)
                    if frame:
                        found.append(str(get_com_member(frame, "GetSymbolXml") or ""))
            view = get_com_member(view, "GetNextView")
        print("reopened frames", found, flush=True)
        if xml not in found:
            raise AssertionError("GTol XML 未在重开后完整回读")
        print(json.dumps({"path": str(path)}), flush=True)


if __name__ == "__main__":
    main()
