using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.PlottingServices;
using Autodesk.AutoCAD.Runtime;
using AcApplication = Autodesk.AutoCAD.ApplicationServices.Application;

[assembly: ExtensionApplication(typeof(CadStudio.AutoCAD2024.CadStudioExtension))]
[assembly: CommandClass(typeof(CadStudio.AutoCAD2024.CadStudioCommands))]

namespace CadStudio.AutoCAD2024
{
    /// <summary>提供插件加载和卸载入口。</summary>
    public sealed class CadStudioExtension : IExtensionApplication
    {
        /// <summary>初始化插件；不注册任意脚本或代码执行入口。</summary>
        public void Initialize()
        {
            AcApplication.DocumentManager.MdiActiveDocument?.Editor.WriteMessage(
                "\nCAD Studio .NET bridge loaded. Commands: CADSTUDIOPROBE, CADSTUDIOCREATE\n");
        }

        /// <summary>卸载插件。</summary>
        public void Terminate()
        {
        }
    }

    /// <summary>AutoCAD 2024 白名单探测与黄金样件命令。</summary>
    public sealed class CadStudioCommands
    {
        private const string ReportEnvironmentVariable = "CAD_STUDIO_DOTNET_REPORT_PATH";
        private const string OutputEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_DWG";
        private const string DxfEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_DXF";
        private const string PdfEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_PDF";
        private const string PngEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_PNG";
        private const string ProbeLayerName = "CAD_STUDIO_PROBE";
        private const string CjkStyleName = "CAD_STUDIO_CJK";
        private const string CjkTypeface = "SimSun";
        private const string DrawingTitle = "安装板";

        /// <summary>回读活动文档、数据库和本机版本，并生成结构化证据。</summary>
        [CommandMethod("CADSTUDIOPROBE", CommandFlags.Session)]
        public void Probe()
        {
            Document? document = AcApplication.DocumentManager.MdiActiveDocument;
            if (document == null)
            {
                WriteReport("failed", "connect", "AUTOCAD_ACTIVE_DOCUMENT_MISSING", new Dictionary<string, bool>());
                return;
            }

            int entityCount = CountModelSpaceEntities(document.Database);
            var checks = new Dictionary<string, bool>
            {
                ["plugin_loaded"] = true,
                ["command_executed"] = true,
                ["active_document"] = true,
                ["database_readable"] = entityCount >= 0,
            };
            WriteReport("review_required", "connect", null, checks, document, entityCount);
            document.Editor.WriteMessage("\nCADSTUDIOPROBE PASS\n");
        }

        /// <summary>创建固定图层、图元和真实尺寸，保存并重新打开 DWG 进行复核。</summary>
        [CommandMethod("CADSTUDIOCREATE", CommandFlags.Session)]
        public void CreateGoldenDrawing()
        {
            Document? document = AcApplication.DocumentManager.MdiActiveDocument;
            if (document == null)
            {
                WriteReport("failed", "create", "AUTOCAD_ACTIVE_DOCUMENT_MISSING", new Dictionary<string, bool>());
                return;
            }

            string outputPath = Environment.GetEnvironmentVariable(OutputEnvironmentVariable)
                ?? Path.Combine(Path.GetTempPath(), "cad-studio-dotnet-probe.dwg");
            outputPath = Path.GetFullPath(outputPath);
            string pdfPath = Path.GetFullPath(Environment.GetEnvironmentVariable(PdfEnvironmentVariable)
                ?? Path.ChangeExtension(outputPath, ".pdf"));
            string pngPath = Path.GetFullPath(Environment.GetEnvironmentVariable(PngEnvironmentVariable)
                ?? Path.ChangeExtension(outputPath, ".png"));
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? Path.GetTempPath());

            try
            {
                bool viewportChecked;
                using (document.LockDocument())
                {
                    CreateProbeEntities(document.Database);
                    viewportChecked = FitAndCheckViewport(document.Editor, document.Database);
                    document.Database.SaveAs(outputPath, DwgVersion.Current);
                    string? dxfPath = Environment.GetEnvironmentVariable(DxfEnvironmentVariable);
                    if (!string.IsNullOrWhiteSpace(dxfPath))
                    {
                        document.Database.DxfOut(Path.GetFullPath(dxfPath), 16, DwgVersion.Current);
                    }
                }

                int reopenedEntityCount = CountSavedDrawingEntities(outputPath);
                var drawingChecks = InspectSavedDrawing(outputPath);
                bool pdfGenerated = viewportChecked && PlotModelSpace(document.Database, pdfPath, "DWG To PDF.pc3");
                bool pngGenerated = viewportChecked && PlotModelSpace(document.Database, pngPath, "PublishToWeb PNG.pc3");
                var checks = new Dictionary<string, bool>
                {
                    ["plugin_loaded"] = true,
                    ["command_executed"] = true,
                    ["dwg_saved"] = File.Exists(outputPath) && new FileInfo(outputPath).Length > 0,
                    ["dwg_reopened"] = reopenedEntityCount >= 4,
                    ["entities_checked"] = reopenedEntityCount >= 4,
                    ["layers_checked"] = SavedDrawingHasLayer(outputPath, ProbeLayerName),
                    ["dimensions_checked"] = drawingChecks.Dimensions,
                    ["cjk_title_checked"] = drawingChecks.Title,
                    ["cjk_font_checked"] = drawingChecks.Font,
                    ["viewport_checked"] = viewportChecked,
                    ["pdf_generated"] = pdfGenerated,
                    ["png_generated"] = pngGenerated,
                };
                bool allPassed = checks.All(item => item.Value);
                WriteReport(allPassed ? "pass" : "review_required", "review", allPassed ? null : "AUTOCAD_DOTNET_EXPORTS_NOT_VERIFIED",
                    checks, document, reopenedEntityCount, outputPath, fontTypeface: drawingChecks.Typeface);
                document.Editor.WriteMessage(allPassed
                    ? "\nCADSTUDIOCREATE DWG/PDF/PNG PASS\n"
                    : "\nCADSTUDIOCREATE DWG PASS; PDF/PNG REVIEW REQUIRED\n");
            }
            catch (System.Exception exception)
            {
                WriteReport("failed", "create", "AUTOCAD_DOTNET_CREATE_FAILED", new Dictionary<string, bool>(), document, -1, outputPath, exception.Message);
                document.Editor.WriteMessage("\nCADSTUDIOCREATE FAILED: " + exception.Message + "\n");
            }
        }

        private static void CreateProbeEntities(Database database)
        {
            using (Transaction transaction = database.TransactionManager.StartTransaction())
            {
                LayerTable layers = (LayerTable)transaction.GetObject(database.LayerTableId, OpenMode.ForRead);
                ObjectId layerId = EnsureLayer(layers, transaction, ProbeLayerName, LineWeight.ByLineWeightDefault);
                ObjectId frameLayer = EnsureLayer(layers, transaction, "FRAME", LineWeight.LineWeight050);
                ObjectId titleLayer = EnsureLayer(layers, transaction, "TITLE", LineWeight.LineWeight025);
                ObjectId dimensionLayer = EnsureLayer(layers, transaction, "DIM", LineWeight.LineWeight025);
                database.Insunits = UnitsValue.Millimeters;

                BlockTable blocks = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                ObjectId textStyleId = CreateCjkTextStyle(database, transaction);
                AppendRectangle(modelSpace, transaction, frameLayer, 0, 0, 297, 210);
                AppendRectangle(modelSpace, transaction, titleLayer, 224, 0, 297, 19);
                AppendRectangle(modelSpace, transaction, layerId, 85, 100, 205, 148);
                foreach (var label in new[] { (DrawingTitle, 11.0), ("图号 AC-024  单位 毫米", 4.0) })
                {
                    AppendEntity(modelSpace, transaction, new DBText
                    {
                        Position = new Point3d(228, label.Item2, 0),
                        Height = 3.5,
                        TextString = label.Item1,
                        TextStyleId = textStyleId,
                        LayerId = titleLayer,
                    });
                }
                AppendEntity(modelSpace, transaction, new AlignedDimension(
                    new Point3d(85, 100, 0),
                    new Point3d(205, 100, 0),
                    new Point3d(85, 88, 0),
                    string.Empty,
                    database.Dimstyle)
                {
                    LayerId = dimensionLayer,
                });
                AppendEntity(modelSpace, transaction, new AlignedDimension(
                    new Point3d(85, 100, 0), new Point3d(85, 148, 0), new Point3d(72, 100, 0),
                    string.Empty, database.Dimstyle) { LayerId = dimensionLayer });
                transaction.Commit();
            }
        }

        private static ObjectId EnsureLayer(LayerTable layers, Transaction transaction, string name, LineWeight weight)
        {
            if (layers.Has(name))
            {
                return layers[name];
            }
            if (!layers.IsWriteEnabled)
            {
                layers.UpgradeOpen();
            }
            var layer = new LayerTableRecord { Name = name, LineWeight = weight };
            ObjectId id = layers.Add(layer);
            transaction.AddNewlyCreatedDBObject(layer, true);
            return id;
        }

        private static ObjectId CreateCjkTextStyle(Database database, Transaction transaction)
        {
            string fontPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Fonts), "simsun.ttc");
            if (!File.Exists(fontPath))
            {
                throw new FileNotFoundException("AutoCAD 2024 中文回归需要已安装的宋体。", fontPath);
            }
            var styles = (TextStyleTable)transaction.GetObject(database.TextStyleTableId, OpenMode.ForRead);
            if (styles.Has(CjkStyleName))
            {
                return styles[CjkStyleName];
            }
            styles.UpgradeOpen();
            var style = new TextStyleTableRecord
            {
                Name = CjkStyleName,
                Font = new Autodesk.AutoCAD.GraphicsInterface.FontDescriptor(CjkTypeface, false, false, 134, 2),
            };
            ObjectId id = styles.Add(style);
            transaction.AddNewlyCreatedDBObject(style, true);
            return id;
        }

        private static void AppendRectangle(BlockTableRecord owner, Transaction transaction, ObjectId layer,
            double left, double bottom, double right, double top)
        {
            var rectangle = new Polyline { LayerId = layer, Closed = true };
            rectangle.AddVertexAt(0, new Point2d(left, bottom), 0, 0, 0);
            rectangle.AddVertexAt(1, new Point2d(right, bottom), 0, 0, 0);
            rectangle.AddVertexAt(2, new Point2d(right, top), 0, 0, 0);
            rectangle.AddVertexAt(3, new Point2d(left, top), 0, 0, 0);
            AppendEntity(owner, transaction, rectangle);
        }

        private static bool FitAndCheckViewport(Editor editor, Database database)
        {
            database.UpdateExt(true);
            Point3d min = database.Extmin;
            Point3d max = database.Extmax;
            using (ViewTableRecord view = editor.GetCurrentView())
            {
                double aspect = view.Width / view.Height;
                if (aspect <= 0 || double.IsNaN(aspect) || double.IsInfinity(aspect))
                {
                    return false;
                }
                view.ViewDirection = Vector3d.ZAxis;
                view.ViewTwist = 0;
                view.Target = Point3d.Origin;
                view.CenterPoint = new Point2d((min.X + max.X) / 2, (min.Y + max.Y) / 2);
                view.Height = Math.Max(max.Y - min.Y, (max.X - min.X) / aspect) * 1.10;
                view.Width = view.Height * aspect;
                editor.SetCurrentView(view);
            }
            using (ViewTableRecord actual = editor.GetCurrentView())
            {
                return actual.ViewDirection.IsEqualTo(Vector3d.ZAxis) && Math.Abs(actual.ViewTwist) < 1e-6
                    && actual.Target.IsEqualTo(Point3d.Origin)
                    && actual.CenterPoint.X - actual.Width / 2 < min.X && actual.CenterPoint.X + actual.Width / 2 > max.X
                    && actual.CenterPoint.Y - actual.Height / 2 < min.Y && actual.CenterPoint.Y + actual.Height / 2 > max.Y;
            }
        }

        private static void AppendEntity(BlockTableRecord owner, Transaction transaction, Entity entity)
        {
            owner.AppendEntity(entity);
            transaction.AddNewlyCreatedDBObject(entity, true);
        }

        private static int CountModelSpaceEntities(Database database)
        {
            using (Transaction transaction = database.TransactionManager.StartOpenCloseTransaction())
            {
                BlockTable blocks = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                return modelSpace.Cast<ObjectId>().Count();
            }
        }

        private static int CountSavedDrawingEntities(string path)
        {
            using (var database = OpenSavedDrawing(path))
            {
                return CountModelSpaceEntities(database);
            }
        }

        private static bool SavedDrawingHasLayer(string path, string layerName)
        {
            using (var database = OpenSavedDrawing(path))
            using (Transaction transaction = database.TransactionManager.StartOpenCloseTransaction())
            {
                LayerTable layers = (LayerTable)transaction.GetObject(database.LayerTableId, OpenMode.ForRead);
                return layers.Has(layerName);
            }
        }

        private static (bool Dimensions, bool Title, bool Font, string? Typeface) InspectSavedDrawing(string path)
        {
            using (var database = OpenSavedDrawing(path))
            using (Transaction transaction = database.TransactionManager.StartOpenCloseTransaction())
            {
                BlockTable blocks = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                var entities = modelSpace.Cast<ObjectId>().Select(id => transaction.GetObject(id, OpenMode.ForRead)).ToList();
                var measurements = entities.OfType<AlignedDimension>()
                    .Where(item => string.IsNullOrEmpty(item.DimensionText) || item.DimensionText == "<>")
                    .Select(item => item.Measurement).ToList();
                var title = entities.OfType<DBText>().FirstOrDefault(item => item.TextString == DrawingTitle);
                var notes = entities.OfType<DBText>().FirstOrDefault(item => item.TextString == "图号 AC-024  单位 毫米");
                var style = title == null ? null : transaction.GetObject(title.TextStyleId, OpenMode.ForRead) as TextStyleTableRecord;
                string? typeface = style?.Font.TypeFace;
                bool font = style != null && style.Name == CjkStyleName && notes?.TextStyleId == title?.TextStyleId
                    && (string.Equals(typeface, CjkTypeface, StringComparison.OrdinalIgnoreCase) || typeface == "宋体");
                return (measurements.Any(value => Math.Abs(value - 120) < 1e-6)
                    && measurements.Any(value => Math.Abs(value - 48) < 1e-6), title != null && notes != null, font, typeface);
            }
        }

        private static Database OpenSavedDrawing(string path)
        {
            var database = new Database(false, true);
            database.ReadDwgFile(path, FileOpenMode.OpenForReadAndAllShare, false, null);
            database.CloseInput(true);
            return database;
        }

        private static bool PlotModelSpace(Database database, string outputPath, string deviceName)
        {
            try
            {
                if (File.Exists(outputPath))
                {
                    File.Delete(outputPath);
                }

                using (Transaction transaction = database.TransactionManager.StartTransaction())
                {
                    BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(
                        SymbolUtilityServices.GetBlockModelSpaceId(database),
                        OpenMode.ForRead);
                    Layout layout = (Layout)transaction.GetObject(modelSpace.LayoutId, OpenMode.ForRead);
                    using (var settings = new PlotSettings(layout.ModelType))
                    {
                        settings.CopyFrom(layout);
                        PlotSettingsValidator validator = PlotSettingsValidator.Current;
                        validator.SetPlotConfigurationName(settings, deviceName, null);
                        validator.RefreshLists(settings);
                        // The verified plan view has zero target and twist, so WCS XY and plot DCS coincide.
                        Point3d min = database.Extmin;
                        Point3d max = database.Extmax;
                        const double margin = 5;
                        var window = new Extents2d(min.X - margin, min.Y - margin, max.X + margin, max.Y + margin);
                        validator.SetPlotWindowArea(settings, window);
                        validator.SetPlotType(settings, Autodesk.AutoCAD.DatabaseServices.PlotType.Window);
                        Extents2d actual = settings.PlotWindowArea;
                        if (!actual.MinPoint.IsEqualTo(window.MinPoint) || !actual.MaxPoint.IsEqualTo(window.MaxPoint))
                        {
                            AcApplication.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nPlot window readback differs: " + deviceName);
                            return false;
                        }
                        validator.SetUseStandardScale(settings, true);
                        validator.SetStdScaleType(settings, StdScaleType.ScaleToFit);
                        validator.SetPlotCentered(settings, true);

                        var plotInfo = new PlotInfo
                        {
                            Layout = modelSpace.LayoutId,
                            OverrideSettings = settings,
                        };
                        new PlotInfoValidator { MediaMatchingPolicy = MatchingPolicy.MatchEnabled }.Validate(plotInfo);
                        using (PlotEngine engine = PlotFactory.CreatePublishEngine())
                        {
                            engine.BeginPlot(null, null);
                            engine.BeginDocument(plotInfo, database.Filename, null, 1, true, outputPath);
                            var pageInfo = new PlotPageInfo();
                            engine.BeginPage(pageInfo, plotInfo, true, null);
                            engine.BeginGenerateGraphics(null);
                            engine.EndGenerateGraphics(null);
                            engine.EndPage(null);
                            engine.EndDocument(null);
                            engine.EndPlot(null);
                        }
                    }
                    transaction.Commit();
                }
                return File.Exists(outputPath) && new FileInfo(outputPath).Length >= 32;
            }
            catch (System.Exception exception)
            {
                AcApplication.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nPlot failed for " + deviceName + ": " + exception.Message);
                return false;
            }
        }

        private static void WriteReport(
            string status,
            string stage,
            string? errorCode,
            IReadOnlyDictionary<string, bool> checks,
            Document? document = null,
            int entityCount = -1,
            string? drawingPath = null,
            string? error = null,
            string? fontTypeface = null)
        {
            string reportPath = Environment.GetEnvironmentVariable(ReportEnvironmentVariable)
                ?? Path.Combine(Path.GetTempPath(), "cad-studio-dotnet-report.json");
            reportPath = Path.GetFullPath(reportPath);
            Directory.CreateDirectory(Path.GetDirectoryName(reportPath) ?? Path.GetTempPath());
            string checkJson = string.Join(",", checks.Select(item => "\"" + Escape(item.Key) + "\":" + item.Value.ToString().ToLowerInvariant()));
            string json = "{"
                + "\"schemaVersion\":\"1.0\","
                + "\"backend\":\"autocad_dotnet\","
                + "\"status\":\"" + Escape(status) + "\","
                + "\"stage\":\"" + Escape(stage) + "\","
                + "\"generatedAt\":\"" + DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture) + "\","
                + "\"autocadVersion\":\"" + Escape(Convert.ToString(AcApplication.GetSystemVariable("ACADVER"), CultureInfo.InvariantCulture) ?? string.Empty) + "\","
                + "\"document\":\"" + Escape(document?.Name ?? string.Empty) + "\","
                + "\"drawingPath\":\"" + Escape(drawingPath ?? string.Empty) + "\","
                + "\"entityCount\":" + entityCount.ToString(CultureInfo.InvariantCulture) + ","
                + "\"fontTypeface\":" + JsonString(fontTypeface) + ","
                + "\"checks\":{" + checkJson + "},"
                + "\"error_code\":" + JsonString(errorCode) + ","
                + "\"error\":" + JsonString(error)
                + "}";
            File.WriteAllText(reportPath, json, new UTF8Encoding(false));
        }

        private static string JsonString(string? value)
        {
            return value == null ? "null" : "\"" + Escape(value) + "\"";
        }

        private static string Escape(string value)
        {
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
        }
    }
}
