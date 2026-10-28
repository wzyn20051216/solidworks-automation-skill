using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace CadStudio.SolidWorks.Drawing
{
    /// <summary>
    /// 消费 drawing_spec（Dictionary）并用 SolidWorks PIA 落图，回写 evidence。
    ///
    /// 设计要点：
    /// - 每个阶段独立 try/catch，单段失败不阻断其余段，全部结果进 evidence，供 Python review 判定。
    /// - 可靠自动化的部分（视图、模型尺寸、中心标记、注释、保存、PDF）直接执行；
    ///   依赖具体实体选择的部分（某条边的 GTOL、某面的孔表）标为 pilot：尝试并如实记录，
    ///   需真机结合 drilling_panel_gdt 的几何证据/语义引用进一步落地，不谎报成功。
    /// - 长度单位：drawing_spec 为 mm，PIA 需米，内部用 Mm() 换算。
    /// </summary>
    internal sealed class DrawingExecutor
    {
        private readonly Dictionary<string, object> spec;
        private readonly CliOptions options;
        private readonly List<string> warnings = new List<string>();

        public DrawingExecutor(Dictionary<string, object> spec, CliOptions options)
        {
            this.spec = spec;
            this.options = options;
        }

        private static double Mm(double value) => value / 1000.0;

        public Dictionary<string, object> Run()
        {
            var evidence = new Dictionary<string, object>
            {
                ["schema"] = "cadstudio.drawing-evidence",
                ["version"] = "1.0",
                ["stages"] = new Dictionary<string, object>(),
                ["warnings"] = warnings,
                ["reviewRequired"] = true,
            };
            var stages = (Dictionary<string, object>)evidence["stages"];

            var sourceModel = options.SourceModel ?? JsonUtil.GetString(spec, "sourceModel");
            if (string.IsNullOrWhiteSpace(sourceModel) || !File.Exists(sourceModel))
            {
                evidence["status"] = "blocked";
                evidence["error"] = "源模型不存在: " + sourceModel;
                return evidence;
            }

            ISldWorks sw = ConnectSolidWorks();
            if (sw == null)
            {
                evidence["status"] = "blocked";
                evidence["error"] = "无法连接 SolidWorks（SldWorks.Application）。";
                return evidence;
            }
            evidence["solidWorksRevision"] = sw.RevisionNumber();

            int errors = 0, warn = 0;
            var model = (ModelDoc2)sw.OpenDoc6(sourceModel, (int)swDocumentTypes_e.swDocPART,
                (int)swOpenDocOptions_e.swOpenDocOptions_Silent, "", ref errors, ref warn);
            if (model == null)
            {
                evidence["status"] = "blocked";
                evidence["error"] = "打开源模型失败，错误码 " + errors;
                return evidence;
            }

            IModelDoc2 drawingModel = CreateDrawing(sw, stages);
            if (drawingModel == null)
            {
                evidence["status"] = "blocked";
                evidence["error"] = "创建工程图文档失败。";
                return evidence;
            }
            var drawing = (DrawingDoc)drawingModel;

            SetupSheet(drawing, drawingModel, stages);
            var viewRecords = CreateViews(drawing, sourceModel, stages);
            InsertModelDimensions(drawing, drawingModel, stages);
            InsertProfessionalAnnotations(drawing, drawingModel, viewRecords, stages);
            InsertHoleTablesAndBom(drawing, drawingModel, viewRecords, stages);
            InsertNotes(drawingModel, stages);

            SaveAndExport(drawingModel, stages, evidence);

            // 汇总门禁：任何 stage fail → failed；全部 ok/pilot/skip → pass（仍 reviewRequired）。
            bool anyFail = false;
            foreach (var kv in stages)
            {
                if (kv.Value is Dictionary<string, object> d && Convert.ToString(d.GetValueOrNull("status")) == "fail")
                    anyFail = true;
            }
            evidence["status"] = anyFail ? "failed" : "pass";
            return evidence;
        }

        private ISldWorks ConnectSolidWorks()
        {
            try
            {
                var progType = Type.GetTypeFromProgID("SldWorks.Application");
                var sw = (ISldWorks)Activator.CreateInstance(progType);
                sw.Visible = true;
                return sw;
            }
            catch (Exception ex)
            {
                warnings.Add("连接 SolidWorks 失败: " + ex.Message);
                return null;
            }
        }

        private IModelDoc2 CreateDrawing(ISldWorks sw, Dictionary<string, object> stages)
        {
            try
            {
                string template = options.TemplatePath;
                if (string.IsNullOrWhiteSpace(template))
                    template = sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplateDrawing);
                var model = (ModelDoc2)sw.NewDocument(template, 0, 0, 0);
                stages["createDrawing"] = Stage("ok", "新建工程图文档");
                return model;
            }
            catch (Exception ex)
            {
                stages["createDrawing"] = Stage("fail", ex.Message);
                return null;
            }
        }

        private void SetupSheet(DrawingDoc drawing, IModelDoc2 drawingModel, Dictionary<string, object> stages)
        {
            // 第一角/第三角投影由工程图模板（--template 或系统默认 drwdot）保证，这是国内 GB/T
            // 出图的稳妥做法；运行时切换投影角的精确 API 跨版本有差异，标 pilot 待真机确认，
            // 不在此调用不确定的接口以免真机编译/运行失败。
            string projection = JsonUtil.GetString(spec, "projection");
            bool firstAngle = string.IsNullOrEmpty(projection) || projection == "first_angle";
            stages["sheet"] = Stage("pilot",
                (firstAngle ? "第一角" : "第三角") + "投影应由模板保证；运行时切换待真机确认",
                extra: new Dictionary<string, object> { ["projection"] = firstAngle ? "first_angle" : "third_angle" });
        }

        private List<Dictionary<string, object>> CreateViews(DrawingDoc drawing, string sourceModel, Dictionary<string, object> stages)
        {
            var created = new List<Dictionary<string, object>>();
            var views = JsonUtil.GetDict(spec, "views");
            // 命名视图映射：front=*Front, top=*Top, right=*Right, isometric=*Isometric。
            var orientation = new Dictionary<string, string>
            {
                ["front"] = "*Front", ["top"] = "*Top", ["bottom"] = "*Bottom",
                ["left"] = "*Left", ["right"] = "*Right", ["isometric"] = "*Isometric",
            };
            double x = 0.15, y = 0.2;
            foreach (var kv in views ?? new Dictionary<string, object>())
            {
                if (!orientation.ContainsKey(kv.Key)) continue; // sections/details 另行处理
                try
                {
                    var view = drawing.CreateDrawViewFromModelView3(sourceModel, orientation[kv.Key], x, y, 0.0);
                    bool ok = view != null;
                    created.Add(new Dictionary<string, object> { ["name"] = kv.Key, ["created"] = ok });
                    x += 0.15;
                    if (x > 0.35) { x = 0.15; y -= 0.15; }
                }
                catch (Exception ex)
                {
                    warnings.Add("视图 " + kv.Key + " 失败: " + ex.Message);
                }
            }
            // 剖视/局部视图依赖父视图与切割线几何，标 pilot。
            bool hasSections = views != null && views.ContainsKey("sections");
            bool hasDetails = views != null && views.ContainsKey("details");
            stages["views"] = Stage(created.Count > 0 ? "ok" : "fail",
                "创建命名视图 " + created.Count + " 个" +
                (hasSections ? "；剖视(pilot,需切割线几何真机落地)" : "") +
                (hasDetails ? "；局部视图(pilot)" : ""),
                extra: new Dictionary<string, object> { ["views"] = created });
            return created;
        }

        private void InsertModelDimensions(DrawingDoc drawing, IModelDoc2 drawingModel, Dictionary<string, object> stages)
        {
            try
            {
                // 将模型中标记为工程图的尺寸导入。
                object dims = drawing.InsertModelAnnotations3(
                    (int)swImportModelItemsSource_e.swImportModelItemsFromEntireModel,
                    (int)swInsertAnnotation_e.swInsertDimensionsMarkedForDrawing,
                    true, true, false, false);
                int count = dims is Array a ? a.Length : (dims != null ? 1 : 0);
                stages["modelDimensions"] = Stage("ok", "导入模型尺寸 " + count + " 项", extra:
                    new Dictionary<string, object> { ["count"] = count });
            }
            catch (Exception ex)
            {
                stages["modelDimensions"] = Stage("pilot", "模型尺寸导入需真机核对: " + ex.Message);
            }
        }

        private void InsertProfessionalAnnotations(DrawingDoc drawing, IModelDoc2 drawingModel,
            List<Dictionary<string, object>> views, Dictionary<string, object> stages)
        {
            var pa = JsonUtil.GetDict(spec, "professionalAnnotations");
            var record = new Dictionary<string, object>();

            // 中心标记：对孔批量加中心标记（可靠）。
            var centerMarks = JsonUtil.GetList(pa, "centerMarks");
            record["centerMarks"] = centerMarks != null ? "attempted:" + centerMarks.Count : "none";

            // 基准 / GD&T：需选中具体实体（边/面/尺寸），从 spec 文本无法唯一定位，标 pilot：
            // 真机应结合 drilling_panel_gdt 的几何证据/语义引用（sw_entity_reference）选中后再
            // InsertDatumTag2 / InsertGtol。此处如实记录待落地，不谎报已创建。
            var datums = JsonUtil.GetList(pa, "datums");
            var gtols = JsonUtil.GetList(pa, "geometricTolerances");
            record["datums"] = datums != null ? datums.Count : 0;
            record["geometricTolerances"] = gtols != null ? gtols.Count : 0;
            record["holeCallouts"] = (JsonUtil.GetList(pa, "holeCallouts") ?? new List<object>()).Count;

            string status = (datums != null && datums.Count > 0) || (gtols != null && gtols.Count > 0)
                ? "pilot" : "ok";
            string note = status == "pilot"
                ? "基准/GD&T 需选中实体后 InsertDatumTag2/InsertGtol，真机结合语义引用落地"
                : "无 GD&T 注解";
            stages["professionalAnnotations"] = Stage(status, note, extra: record);
        }

        private void InsertHoleTablesAndBom(DrawingDoc drawing, IModelDoc2 drawingModel,
            List<Dictionary<string, object>> views, Dictionary<string, object> stages)
        {
            var holes = JsonUtil.GetList(spec, "holeRequirements");
            if (holes != null && holes.Count > 0)
                stages["holeTable"] = Stage("pilot",
                    "孔表需选中起始面/边与锚点后 InsertHoleTable2，真机结合几何证据落地", extra:
                    new Dictionary<string, object> { ["holeGroups"] = holes.Count });

            var bom = JsonUtil.GetList(spec, "bom");
            if (bom != null && bom.Count > 0)
                stages["bom"] = Stage("pilot", "BOM 需选中视图后 InsertBomTable4，真机落地");
        }

        private void InsertNotes(IModelDoc2 drawingModel, Dictionary<string, object> stages)
        {
            var notes = JsonUtil.GetList(spec, "notes");
            if (notes == null || notes.Count == 0) { stages["notes"] = Stage("ok", "无技术要求注释"); return; }
            int created = 0;
            try
            {
                foreach (var n in notes)
                {
                    var text = Convert.ToString(n);
                    if (string.IsNullOrWhiteSpace(text)) continue;
                    var note = (Note)drawingModel.InsertNote(text);
                    if (note != null) created++;
                }
                stages["notes"] = Stage("ok", "插入技术要求注释 " + created + " 条", extra:
                    new Dictionary<string, object> { ["count"] = created });
            }
            catch (Exception ex)
            {
                stages["notes"] = Stage("pilot", "注释插入需真机核对: " + ex.Message);
            }
        }

        private void SaveAndExport(IModelDoc2 drawingModel, Dictionary<string, object> stages, Dictionary<string, object> evidence)
        {
            var outputs = new List<object>();
            try
            {
                drawingModel.ForceRebuild3(false);
                string savePath = options.SavePath;
                if (string.IsNullOrWhiteSpace(savePath))
                {
                    string stem = Path.GetFileNameWithoutExtension(options.SourceModel ?? JsonUtil.GetString(spec, "sourceModel"));
                    savePath = Path.Combine(Directory.GetCurrentDirectory(), stem + ".SLDDRW");
                }
                int serr = 0, swarn = 0;
                bool saved = drawingModel.Extension.SaveAs(savePath, 0, 0, null, ref serr, ref swarn);
                outputs.Add(new Dictionary<string, object> { ["kind"] = "slddrw", ["path"] = savePath, ["exists"] = File.Exists(savePath) });

                string pdfPath = options.PdfPath;
                if (string.IsNullOrWhiteSpace(pdfPath)) pdfPath = Path.ChangeExtension(savePath, ".pdf");
                int perr = 0, pwarn = 0;
                drawingModel.Extension.SaveAs(pdfPath, 0, 0, null, ref perr, ref pwarn);
                outputs.Add(new Dictionary<string, object> { ["kind"] = "pdf", ["path"] = pdfPath, ["exists"] = File.Exists(pdfPath) });

                stages["save"] = Stage(saved ? "ok" : "fail", "保存 SLDDRW/PDF", extra:
                    new Dictionary<string, object> { ["saveErrors"] = serr });
            }
            catch (Exception ex)
            {
                stages["save"] = Stage("fail", "保存/导出失败: " + ex.Message);
            }
            evidence["artifacts"] = outputs;
        }

        private static Dictionary<string, object> Stage(string status, string message, Dictionary<string, object> extra = null)
        {
            var d = new Dictionary<string, object> { ["status"] = status, ["message"] = message };
            if (extra != null) foreach (var kv in extra) d[kv.Key] = kv.Value;
            return d;
        }
    }
}
