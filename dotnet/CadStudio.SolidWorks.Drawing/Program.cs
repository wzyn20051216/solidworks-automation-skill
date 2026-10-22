using System;
using System.Collections.Generic;
using System.IO;
using System.Web.Script.Serialization;

namespace CadStudio.SolidWorks.Drawing
{
    /// <summary>
    /// drawing_spec → SLDDRW 出图执行器入口。
    ///
    /// 定位：Python 负责一切“非原生精度”工作（自然语言规划、钻孔面板孔位/基准/GD&T 分析、
    /// DRC 审计、drawing_spec 生成与 review 证据回读）；本 C# 进程外执行器负责“原生精度”落图——
    /// 消费 Python 产出的、已通过 schema 校验的 drawing_spec JSON，用强类型 SolidWorks PIA
    /// 驱动 IDrawingDoc 建视图、插尺寸、GD&T、孔表、BOM、标题栏，并回写机器可读 evidence JSON。
    ///
    /// 能力等级：pilot。需 Windows + SolidWorks + PIA（SolidWorksApiDir）编译与真机运行；
    /// 真机回归通过后方可在 capabilities.yaml 升级 drawing_dotnet_generation。
    ///
    /// 用法：
    ///   CadStudio.SolidWorks.Drawing.exe --spec spec.json --evidence-out evidence.json \
    ///     [--source-model part.SLDPRT] [--pdf out.pdf] [--template sheet.drwdot] [--save out.SLDDRW]
    /// 退出码：0=ok/pass，1=blocked/failed。
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            var options = CliOptions.Parse(args);
            var serializer = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };

            Dictionary<string, object> evidence;
            try
            {
                if (string.IsNullOrWhiteSpace(options.SpecPath) || !File.Exists(options.SpecPath))
                    throw new ArgumentException("必须提供存在的 --spec drawing_spec JSON 路径。");
                if (string.IsNullOrWhiteSpace(options.EvidenceOut))
                    throw new ArgumentException("必须提供 --evidence-out 输出路径。");

                var specText = File.ReadAllText(options.SpecPath);
                var spec = serializer.Deserialize<Dictionary<string, object>>(specText)
                           ?? throw new ArgumentException("drawing_spec 不是 JSON 对象。");
                var executor = new DrawingExecutor(spec, options);
                evidence = executor.Run();
            }
            catch (Exception ex)
            {
                evidence = new Dictionary<string, object>
                {
                    ["schema"] = "cadstudio.drawing-evidence",
                    ["status"] = "blocked",
                    ["error"] = ex.Message,
                    ["stage"] = "startup",
                };
            }

            try
            {
                if (!string.IsNullOrWhiteSpace(options.EvidenceOut))
                {
                    var dir = Path.GetDirectoryName(Path.GetFullPath(options.EvidenceOut));
                    if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                    File.WriteAllText(options.EvidenceOut, serializer.Serialize(evidence));
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("写 evidence 失败: " + ex.Message);
            }

            var status = evidence.TryGetValue("status", out var s) ? Convert.ToString(s) : "blocked";
            Console.WriteLine(serializer.Serialize(evidence));
            return status == "ok" || status == "pass" ? 0 : 1;
        }
    }

    /// <summary>命令行参数。</summary>
    internal sealed class CliOptions
    {
        public string SpecPath;
        public string EvidenceOut;
        public string SourceModel;
        public string PdfPath;
        public string SavePath;
        public string TemplatePath;

        public static CliOptions Parse(string[] args)
        {
            var options = new CliOptions();
            for (int i = 0; i < args.Length - 1; i++)
            {
                switch (args[i])
                {
                    case "--spec": options.SpecPath = args[++i]; break;
                    case "--evidence-out": options.EvidenceOut = args[++i]; break;
                    case "--source-model": options.SourceModel = args[++i]; break;
                    case "--pdf": options.PdfPath = args[++i]; break;
                    case "--save": options.SavePath = args[++i]; break;
                    case "--template": options.TemplatePath = args[++i]; break;
                }
            }
            return options;
        }
    }
}
