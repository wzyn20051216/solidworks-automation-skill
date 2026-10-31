"""GTol 框格式和 XML 回读的边界。"""
from scripts import sw_drawing


class Frame:
    def __init__(self, xml):
        self.xml = xml

    def GetSymbolXml(self):
        return self.xml


class Symbol:
    def __init__(self, xml, fmt=2):
        self.xml, self.fmt = xml, fmt

    def GetFormat(self):
        return self.fmt

    def GetFrame(self, index):
        assert index == 1
        return Frame(self.xml)


def test_new_frame_evidence_extracts_tolerance_and_datums():
    xml = ("<GtolFrame><ToleranceSymbol>IGTOL-POSI</ToleranceSymbol>"
           "<ToleranceRangeInfo><PrimaryToleranceValue>0.2</PrimaryToleranceValue></ToleranceRangeInfo>"
           "<DatumCompartment><DatumDetail><DatumLetter>A</DatumLetter></DatumDetail></DatumCompartment>"
           "<DatumCompartment><DatumDetail><DatumLetter>B</DatumLetter></DatumDetail></DatumCompartment></GtolFrame>")
    frame = sw_drawing._MODULE._gtol_frame_records(Symbol(xml), 1)[0]
    assert frame["symbols"] == ["IGTOL-POSI"]
    assert frame["values"] == ["0.2", "A", "B"]


def test_untrusted_or_unreadable_xml_never_produces_values():
    for xml in ('<!DOCTYPE GtolFrame><GtolFrame/>', '<GtolFrame>', 'x' * 65537):
        frame = sw_drawing._MODULE._gtol_frame_records(Symbol(xml), 1)[0]
        assert frame["values"] == []
        assert frame["xml_error"] == "invalid_xml"
    frame = sw_drawing._MODULE._gtol_frame_records(Symbol("", fmt=None), 1)[0]
    assert frame["error"] == "unknown_gtol_format"
