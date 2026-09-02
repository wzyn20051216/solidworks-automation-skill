using System;
using System.Drawing;
using System.Windows.Forms;

namespace CadStudio.SolidWorks.AddinHost
{
    /// <summary>展示 Add-in 健康状态并提供诊断/PMP 快捷入口。</summary>
    internal sealed class TaskPaneControl : UserControl
    {
        private readonly Label stateLabel;

        /// <summary>创建 TaskPane 控件。</summary>
        internal TaskPaneControl(string revision, string diagnosticPath, Action showPropertyPage, Action refreshDiagnostics)
        {
            Dock = DockStyle.Fill;
            BackColor = Color.White;
            Padding = new Padding(12);

            var title = new Label
            {
                AutoSize = true,
                Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 12f, FontStyle.Bold),
                Text = "CAD Studio Add-in 宿主",
                Location = new Point(12, 14),
            };
            stateLabel = new Label
            {
                AutoSize = false,
                Size = new Size(280, 72),
                Location = new Point(12, 48),
                Text = "状态：已连接\r\nSolidWorks：" + revision + "\r\n诊断：" + diagnosticPath,
            };
            var propertyButton = new Button
            {
                Text = "打开 PropertyManagerPage",
                Size = new Size(220, 32),
                Location = new Point(12, 130),
            };
            var refreshButton = new Button
            {
                Text = "刷新诊断证据",
                Size = new Size(220, 32),
                Location = new Point(12, 170),
            };
            propertyButton.Click += delegate { showPropertyPage(); };
            refreshButton.Click += delegate
            {
                refreshDiagnostics();
                stateLabel.Text = "状态：诊断已刷新\r\nSolidWorks：" + revision + "\r\n诊断：" + diagnosticPath;
            };

            Controls.Add(title);
            Controls.Add(stateLabel);
            Controls.Add(propertyButton);
            Controls.Add(refreshButton);
        }
    }
}
