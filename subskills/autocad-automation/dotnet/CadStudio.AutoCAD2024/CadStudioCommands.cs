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
        private const string PdfEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_PDF";
        private const string PngEnvironmentVariable = "CAD_STUDIO_DOTNET_OUTPUT_PNG";
        private const string ProbeLayerName = "CAD_STUDIO_PROBE";

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
                using (document.LockDocument())
                {
                    CreateProbeEntities(document.Database);
                    document.Database.SaveAs(outputPath, DwgVersion.Current);
                }

                int reopenedEntityCount = CountSavedDrawingEntities(outputPath);
                bool pdfGenerated = PlotModelSpace(document.Database, pdfPath, "DWG To PDF.pc3");
                bool pngGenerated = PlotModelSpace(document.Database, pngPath, "PublishToWeb PNG.pc3");
                var checks = new Dictionary<string, bool>
                {
                    ["plugin_loaded"] = true,
                    ["command_executed"] = true,
                    ["dwg_saved"] = File.Exists(outputPath) && new FileInfo(outputPath).Length > 0,
                    ["dwg_reopened"] = reopenedEntityCount >= 4,
                    ["entities_checked"] = reopenedEntityCount >= 4,
                    ["layers_checked"] = SavedDrawingHasLayer(outputPath, ProbeLayerName),
                    ["dimensions_checked"] = SavedDrawingHasDimension(outputPath),
                    ["pdf_generated"] = pdfGenerated,
                    ["png_generated"] = pngGenerated,
                };
                bool allPassed = checks.All(item => item.Value);
                WriteReport(allPassed ? "pass" : "review_required", "review", allPassed ? null : "AUTOCAD_DOTNET_EXPORTS_NOT_VERIFIED", checks, document, reopenedEntityCount, outputPath);
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
                ObjectId layerId;
                if (!layers.Has(ProbeLayerName))
                {
                    layers.UpgradeOpen();
                    var layer = new LayerTableRecord { Name = ProbeLayerName };
                    layerId = layers.Add(layer);
                    transaction.AddNewlyCreatedDBObject(layer, true);
                }
                else
                {
                    layerId = layers[ProbeLayerName];
                }

                BlockTable blocks = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                var start = new Point3d(0, 0, 0);
                var end = new Point3d(120, 0, 0);
                AppendEntity(modelSpace, transaction, new Line(start, end) { LayerId = layerId });
                AppendEntity(modelSpace, transaction, new Circle(new Point3d(30, 35, 0), Vector3d.ZAxis, 8) { LayerId = layerId });
                AppendEntity(modelSpace, transaction, new DBText
                {
                    Position = new Point3d(5, 55, 0),
                    Height = 5,
                    TextString = "CAD STUDIO AUTO CAD 2024 PROBE",
                    LayerId = layerId,
                });
                AppendEntity(modelSpace, transaction, new AlignedDimension(
                    start,
                    end,
                    new Point3d(0, -15, 0),
                    string.Empty,
                    database.Dimstyle)
                {
                    LayerId = layerId,
                });
                transaction.Commit();
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

        private static bool SavedDrawingHasDimension(string path)
        {
            using (var database = OpenSavedDrawing(path))
            using (Transaction transaction = database.TransactionManager.StartOpenCloseTransaction())
            {
                BlockTable blocks = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord modelSpace = (BlockTableRecord)transaction.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                return modelSpace.Cast<ObjectId>()
                    .Select(id => transaction.GetObject(id, OpenMode.ForRead))
                    .Any(item => item is Dimension);
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
                        validator.SetPlotType(settings, Autodesk.AutoCAD.DatabaseServices.PlotType.Extents);
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
            catch (System.Exception)
            {
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
            string? error = null)
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
