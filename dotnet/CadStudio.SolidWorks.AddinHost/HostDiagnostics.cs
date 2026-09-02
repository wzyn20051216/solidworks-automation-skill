using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;

namespace CadStudio.SolidWorks.AddinHost
{
    /// <summary>维护 Add-in 生命周期、UI 和事件的机器可读诊断证据。</summary>
    internal sealed class HostDiagnostics
    {
        private readonly object syncRoot = new object();
        private readonly JavaScriptSerializer serializer = new JavaScriptSerializer();
        private readonly Dictionary<string, int> eventCounts = new Dictionary<string, int>(StringComparer.Ordinal);
        private readonly List<string> errors = new List<string>();
        private DateTime connectedAtUtc;
        private string solidWorksRevision = string.Empty;
        private bool connected;
        private bool callbackRegistered;
        private bool commandGroupReady;
        private bool taskPaneReady;
        private bool propertyManagerPageReady;

        /// <summary>初始化诊断文件位置。</summary>
        internal HostDiagnostics()
        {
            string root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            DiagnosticDirectory = Path.Combine(root, "CAD Studio", "SolidWorksAddin");
            DiagnosticPath = Path.Combine(DiagnosticDirectory, "host-status.json");
        }

        /// <summary>诊断目录。</summary>
        internal string DiagnosticDirectory { get; }

        /// <summary>诊断 JSON 路径。</summary>
        internal string DiagnosticPath { get; }

        /// <summary>记录成功连接和宿主版本。</summary>
        internal void MarkConnection(string revision, bool callbackReady)
        {
            lock (syncRoot)
            {
                connectedAtUtc = DateTime.UtcNow;
                solidWorksRevision = revision ?? string.Empty;
                connected = callbackReady;
                callbackRegistered = callbackReady;
                WriteUnsafe();
            }
        }

        /// <summary>记录 UI 子系统状态。</summary>
        internal void MarkUi(bool commandReady, bool taskPane, bool propertyPage)
        {
            lock (syncRoot)
            {
                commandGroupReady = commandReady;
                taskPaneReady = taskPane;
                propertyManagerPageReady = propertyPage;
                WriteUnsafe();
            }
        }

        /// <summary>递增指定应用事件计数。</summary>
        internal void RecordEvent(string name)
        {
            lock (syncRoot)
            {
                int current;
                eventCounts.TryGetValue(name, out current);
                eventCounts[name] = current + 1;
                WriteUnsafe();
            }
        }

        /// <summary>记录非致命错误并限制历史长度。</summary>
        internal void RecordError(string area, Exception exception)
        {
            lock (syncRoot)
            {
                errors.Add(string.Format("{0:o} [{1}] {2}", DateTime.UtcNow, area, exception.Message));
                if (errors.Count > 20)
                {
                    errors.RemoveAt(0);
                }
                WriteUnsafe();
            }
        }

        /// <summary>刷新当前证据文件。</summary>
        internal void Flush()
        {
            lock (syncRoot)
            {
                WriteUnsafe();
            }
        }

        /// <summary>记录卸载状态。</summary>
        internal void MarkDisconnected()
        {
            lock (syncRoot)
            {
                connected = false;
                callbackRegistered = false;
                commandGroupReady = false;
                taskPaneReady = false;
                propertyManagerPageReady = false;
                WriteUnsafe();
            }
        }

        /// <summary>在持锁状态下原子替换诊断 JSON。</summary>
        private void WriteUnsafe()
        {
            Directory.CreateDirectory(DiagnosticDirectory);
            var payload = new Dictionary<string, object>
            {
                ["schemaVersion"] = "1.0",
                ["addinGuid"] = SwAddin.AddinGuid,
                ["status"] = connected ? "connected" : "disconnected",
                ["connectedAtUtc"] = connectedAtUtc == default(DateTime) ? null : connectedAtUtc.ToString("o"),
                ["lastUpdatedUtc"] = DateTime.UtcNow.ToString("o"),
                ["solidWorksRevision"] = solidWorksRevision,
                ["hostProcessId"] = Process.GetCurrentProcess().Id,
                ["hostProcessName"] = Process.GetCurrentProcess().ProcessName,
                ["callbackRegistered"] = callbackRegistered,
                ["commandGroupReady"] = commandGroupReady,
                ["taskPaneReady"] = taskPaneReady,
                ["propertyManagerPageReady"] = propertyManagerPageReady,
                ["eventCounts"] = new Dictionary<string, int>(eventCounts),
                ["errors"] = errors.ToArray(),
            };
            string json = serializer.Serialize(payload);
            string temporary = DiagnosticPath + ".tmp";
            File.WriteAllText(temporary, json, new UTF8Encoding(false));
            File.Copy(temporary, DiagnosticPath, true);
            File.Delete(temporary);
        }
    }
}
