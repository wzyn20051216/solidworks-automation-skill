using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swpublished;

namespace CadStudio.SolidWorks.AddinHost
{
    /// <summary>CAD Studio 的通用 SolidWorks 进程内 Add-in 宿主。</summary>
    [ComVisible(true)]
    [Guid(AddinGuid)]
    [ProgId("CadStudio.SolidWorks.AddinHost")]
    public sealed class SwAddin : ISwAddin
    {
        public const string AddinGuid = "8EE76E8D-9B47-4DE0-AFA2-B2E36621A134";
        private const int CommandGroupId = 55001;
        private const int PropertyPageLabelId = 100;
        private const int PropertyPageTextId = 101;
        private const int PropertyPageButtonId = 102;

        private readonly HostDiagnostics diagnostics = new HostDiagnostics();
        private ISldWorks swApp;
        private DSldWorksEvents_Event applicationEvents;
        private ICommandManager commandManager;
        private ICommandGroup commandGroup;
        private ITaskpaneView taskPane;
        private TaskPaneControl taskPaneControl;
        private IPropertyManagerPage2 propertyPage;
        private PropertyPageHandler propertyPageHandler;
        private int addinCookie;
        private bool commandGroupReady;
        private bool taskPaneReady;
        private bool propertyManagerPageReady;

        /// <summary>注册 COM 类和 SolidWorks Add-ins 元数据。</summary>
        [ComRegisterFunction]
        public static void Register(Type type)
        {
            string guid = "{" + AddinGuid + "}";
            using (RegistryKey addin = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\SOLIDWORKS\Addins\" + guid))
            {
                addin.SetValue(null, 0, RegistryValueKind.DWord);
                addin.SetValue("Title", "CAD Studio Add-in Host", RegistryValueKind.String);
                addin.SetValue("Description", "事件、PropertyManagerPage、TaskPane 与诊断宿主", RegistryValueKind.String);
            }
            using (RegistryKey startup = Registry.CurrentUser.CreateSubKey(@"Software\SOLIDWORKS\AddInsStartup\" + guid))
            {
                startup.SetValue(null, 1, RegistryValueKind.DWord);
            }
        }

        /// <summary>删除 Add-in 注册项。</summary>
        [ComUnregisterFunction]
        public static void Unregister(Type type)
        {
            string guid = "{" + AddinGuid + "}";
            Registry.LocalMachine.DeleteSubKeyTree(@"SOFTWARE\SOLIDWORKS\Addins\" + guid, false);
            Registry.CurrentUser.DeleteSubKeyTree(@"Software\SOLIDWORKS\AddInsStartup\" + guid, false);
        }

        /// <summary>由 SolidWorks 调用，建立回调、菜单、TaskPane 和事件订阅。</summary>
        public bool ConnectToSW(object thisSw, int cookie)
        {
            try
            {
                swApp = (ISldWorks)thisSw;
                addinCookie = cookie;
                bool callbackReady = swApp.SetAddinCallbackInfo2(0, this, addinCookie);
                diagnostics.MarkConnection(swApp.RevisionNumber(), callbackReady);
                if (!callbackReady)
                {
                    throw new InvalidOperationException("SetAddinCallbackInfo2 未注册有效回调。");
                }
                AttachApplicationEvents();
                commandGroupReady = CreateCommandGroup();
                if (!commandGroupReady)
                {
                    throw new InvalidOperationException("CommandGroup 激活失败。");
                }
                taskPaneReady = CreateTaskPane();
                if (!taskPaneReady)
                {
                    throw new InvalidOperationException("TaskPane 创建或显示失败。");
                }
                propertyManagerPageReady = CreatePropertyManagerPage();
                diagnostics.MarkUi(commandGroupReady, taskPaneReady, propertyManagerPageReady);
                return callbackReady && commandGroupReady && taskPaneReady;
            }
            catch (Exception exception)
            {
                ReleaseHostResources();
                diagnostics.MarkDisconnected();
                diagnostics.RecordError("connect", exception);
                return false;
            }
        }

        /// <summary>由 SolidWorks 调用，解除订阅并释放全部宿主资源。</summary>
        public bool DisconnectFromSW()
        {
            bool released = ReleaseHostResources();
            diagnostics.MarkDisconnected();
            GC.Collect();
            GC.WaitForPendingFinalizers();
            return released;
        }

        /// <summary>CommandManager 回调：显示 PropertyManagerPage。</summary>
        public void ShowPropertyPage()
        {
            try
            {
                if (propertyPage == null && !CreatePropertyManagerPage())
                {
                    throw new InvalidOperationException("PropertyManagerPage 创建失败。");
                }
                propertyManagerPageReady = true;
                diagnostics.MarkUi(commandGroupReady, taskPaneReady, propertyManagerPageReady);
                propertyPage.Show2(0);
                diagnostics.RecordEvent("property_page_show");
            }
            catch (Exception exception)
            {
                diagnostics.RecordError("property_page_show", exception);
            }
        }

        /// <summary>CommandManager 回调：显示 TaskPane。</summary>
        public void ShowTaskPane()
        {
            try
            {
                taskPane?.ShowView();
                diagnostics.RecordEvent("task_pane_show");
            }
            catch (Exception exception)
            {
                diagnostics.RecordError("task_pane_show", exception);
            }
        }

        /// <summary>CommandManager 回调：刷新诊断证据。</summary>
        public void RefreshDiagnostics()
        {
            diagnostics.Flush();
        }

        /// <summary>CommandManager 启用回调。</summary>
        public int EnableCommand()
        {
            return swApp == null ? 0 : 1;
        }

        /// <summary>创建并激活菜单与工具栏命令组。</summary>
        private bool CreateCommandGroup()
        {
            commandManager = swApp.GetCommandManager(addinCookie);
            int errors = 0;
            commandGroup = commandManager.CreateCommandGroup2(
                CommandGroupId,
                "CAD Studio",
                "CAD Studio Add-in 宿主",
                "CAD Studio",
                -1,
                true,
                ref errors);
            if (commandGroup == null || errors != (int)swCreateCommandGroupErrors.swCreateCommandGroup_Success)
            {
                throw new InvalidOperationException("CreateCommandGroup2 失败，错误码：" + errors);
            }

            commandGroup.MainIconList = CreateMainIcons();
            commandGroup.IconList = CreateCommandIconStrips();
            commandGroup.HasMenu = true;
            commandGroup.HasToolbar = true;
            int itemType = (int)swCommandItemType_e.swMenuItem | (int)swCommandItemType_e.swToolbarItem;
            commandGroup.AddCommandItem2("打开参数页", -1, "显示通用 PropertyManagerPage", "打开参数页", 0, nameof(ShowPropertyPage), nameof(EnableCommand), 1, itemType);
            commandGroup.AddCommandItem2("显示任务窗格", -1, "显示 CAD Studio TaskPane", "显示任务窗格", 1, nameof(ShowTaskPane), nameof(EnableCommand), 2, itemType);
            commandGroup.AddCommandItem2("刷新诊断", -1, "刷新 Add-in 诊断证据", "刷新诊断", 2, nameof(RefreshDiagnostics), nameof(EnableCommand), 3, itemType);
            return commandGroup.Activate();
        }

        /// <summary>创建兼容高 DPI 的命令图标列表。</summary>
        private string[] CreateMainIcons()
        {
            int[] sizes = { 20, 32, 40, 64, 96, 128 };
            string[] paths = new string[sizes.Length];
            for (int index = 0; index < sizes.Length; index++)
            {
                paths[index] = CreateIconFile("main-" + sizes[index] + ".png", sizes[index], 1);
            }
            return paths;
        }

        /// <summary>创建每种 DPI 尺寸对应的三命令横向图标条。</summary>
        private string[] CreateCommandIconStrips()
        {
            int[] sizes = { 20, 32, 40, 64, 96, 128 };
            string[] paths = new string[sizes.Length];
            for (int index = 0; index < sizes.Length; index++)
            {
                paths[index] = CreateIconFile("commands-" + sizes[index] + ".png", sizes[index], 3);
            }
            return paths;
        }

        /// <summary>创建 TaskPane 并托管 WinForms 控件句柄。</summary>
        private bool CreateTaskPane()
        {
            string icon = CreateIconFile("taskpane.bmp", 20, 1);
            taskPane = swApp.CreateTaskpaneView2(icon, "CAD Studio");
            if (taskPane == null)
            {
                return false;
            }
            taskPaneControl = new TaskPaneControl(swApp.RevisionNumber(), diagnostics.DiagnosticPath, ShowPropertyPage, RefreshDiagnostics);
            taskPaneControl.CreateControl();
            bool displayed = taskPane.DisplayWindowFromHandlex64(taskPaneControl.Handle.ToInt64());
            return displayed && taskPane.ShowView();
        }

        /// <summary>创建含标签、文本框和按钮的通用 PropertyManagerPage。</summary>
        private bool CreatePropertyManagerPage()
        {
            propertyPageHandler = new PropertyPageHandler(diagnostics.RecordEvent);
            int options = (int)swPropertyManagerPageOptions_e.swPropertyManagerOptions_OkayButton
                | (int)swPropertyManagerPageOptions_e.swPropertyManagerOptions_CancelButton
                | (int)swPropertyManagerPageOptions_e.swPropertyManagerOptions_PushpinButton;
            int errors = 0;
            propertyPage = swApp.ICreatePropertyManagerPage("CAD Studio Add-in 宿主", options, propertyPageHandler, ref errors);
            if (propertyPage == null || errors != 0)
            {
                return false;
            }
            int controlOptions = (int)swAddControlOptions_e.swControlOptions_Visible
                | (int)swAddControlOptions_e.swControlOptions_Enabled;
            var label = (IPropertyManagerPageLabel)propertyPage.AddControl2(
                PropertyPageLabelId,
                (short)swPropertyManagerPageControlType_e.swControlType_Label,
                "宿主状态",
                (short)swPropertyManagerPageControlLeftAlign_e.swControlAlign_LeftEdge,
                controlOptions,
                "显示当前 Add-in 连接状态");
            label.Caption = "已连接；事件、TaskPane 和诊断记录器可用。";
            var textbox = (IPropertyManagerPageTextbox)propertyPage.AddControl2(
                PropertyPageTextId,
                (short)swPropertyManagerPageControlType_e.swControlType_Textbox,
                "扩展载荷",
                (short)swPropertyManagerPageControlLeftAlign_e.swControlAlign_LeftEdge,
                controlOptions,
                "供后续受控扩展传入短文本参数");
            textbox.Text = "ready";
            var button = (IPropertyManagerPageButton)propertyPage.AddControl2(
                PropertyPageButtonId,
                (short)swPropertyManagerPageControlType_e.swControlType_Button,
                "记录诊断事件",
                (short)swPropertyManagerPageControlLeftAlign_e.swControlAlign_LeftEdge,
                controlOptions,
                "验证 PMP 回调链路");
            button.Caption = "记录诊断事件";
            return true;
        }

        /// <summary>订阅必要且低频的 SolidWorks 应用事件。</summary>
        private void AttachApplicationEvents()
        {
            applicationEvents = (DSldWorksEvents_Event)swApp;
            applicationEvents.ActiveModelDocChangeNotify += OnActiveModelDocChange;
            applicationEvents.FileOpenPostNotify += OnFileOpenPost;
            applicationEvents.FileNewNotify2 += OnFileNew;
            applicationEvents.FileCloseNotify += OnFileClose;
        }

        /// <summary>解除应用事件订阅。</summary>
        private void DetachApplicationEvents()
        {
            if (applicationEvents == null)
            {
                return;
            }
            applicationEvents.ActiveModelDocChangeNotify -= OnActiveModelDocChange;
            applicationEvents.FileOpenPostNotify -= OnFileOpenPost;
            applicationEvents.FileNewNotify2 -= OnFileNew;
            applicationEvents.FileCloseNotify -= OnFileClose;
            applicationEvents = null;
        }

        /// <summary>逐项释放资源，单项失败时继续清理其余对象。</summary>
        private bool ReleaseHostResources()
        {
            bool success = true;
            success &= TryRelease("detach_events", DetachApplicationEvents);
            success &= TryRelease("close_property_page", delegate
            {
                if (propertyPage != null) { propertyPage.Close(true); }
            });
            success &= TryRelease("delete_task_pane", delegate
            {
                if (taskPane != null) { taskPane.DeleteView(); }
            });
            success &= TryRelease("dispose_task_pane_control", delegate
            {
                if (taskPaneControl != null) { taskPaneControl.Dispose(); }
            });
            success &= TryRelease("remove_command_group", delegate
            {
                if (commandManager != null) { commandManager.RemoveCommandGroup2(CommandGroupId, true); }
            });
            propertyPage = null;
            propertyPageHandler = null;
            taskPane = null;
            taskPaneControl = null;
            commandGroup = null;
            commandManager = null;
            swApp = null;
            commandGroupReady = false;
            taskPaneReady = false;
            propertyManagerPageReady = false;
            return success;
        }

        /// <summary>执行单项释放动作并记录异常。</summary>
        private bool TryRelease(string area, Action release)
        {
            try
            {
                release();
                return true;
            }
            catch (Exception exception)
            {
                diagnostics.RecordError(area, exception);
                return false;
            }
        }

        private int OnActiveModelDocChange() { diagnostics.RecordEvent("active_model_doc_change"); return 0; }
        private int OnFileOpenPost(string fileName) { diagnostics.RecordEvent("file_open_post"); return 0; }
        private int OnFileNew(object newDocument, int documentType, string templateName)
        {
            diagnostics.RecordEvent("file_new");
            if (propertyPage == null)
            {
                propertyManagerPageReady = CreatePropertyManagerPage();
                diagnostics.MarkUi(commandGroupReady, taskPaneReady, propertyManagerPageReady);
            }
            return 0;
        }
        private int OnFileClose(string fileName, int reason) { diagnostics.RecordEvent("file_close"); return 0; }

        /// <summary>按名称创建运行时图标，避免部署额外二进制资源。</summary>
        private string CreateIconFile(string fileName, int size, int glyphCount)
        {
            string path = Path.Combine(diagnostics.DiagnosticDirectory, fileName);
            Directory.CreateDirectory(diagnostics.DiagnosticDirectory);
            if (File.Exists(path))
            {
                return path;
            }
            using (var bitmap = new Bitmap(size * glyphCount, size))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            using (var brush = new SolidBrush(Color.FromArgb(27, 89, 163)))
            using (var textBrush = new SolidBrush(Color.White))
            using (var font = new Font(FontFamily.GenericSansSerif, Math.Max(7f, size * 0.36f), FontStyle.Bold, GraphicsUnit.Pixel))
            {
                graphics.Clear(Color.Transparent);
                string[] glyphs = { "P", "T", "D" };
                for (int index = 0; index < glyphCount; index++)
                {
                    graphics.FillRectangle(brush, index * size, 0, size, size);
                    graphics.DrawString(glyphs[index], font, textBrush, new PointF(index * size + size * 0.16f, size * 0.1f));
                }
                if (Path.GetExtension(path).Equals(".bmp", StringComparison.OrdinalIgnoreCase))
                {
                    bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Bmp);
                }
                else
                {
                    bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
                }
            }
            return path;
        }
    }
}
