using System;
using System.Runtime.InteropServices;
using SolidWorks.Interop.swpublished;

namespace CadStudio.SolidWorks.AddinHost
{
    /// <summary>SW2026 IPropertyManagerPage2Handler9 的完整托管回调实现。</summary>
    [ComVisible(true)]
    [Guid("8F33287B-C62A-4E05-85E6-3D7339A7F74B")]
    [ClassInterface(ClassInterfaceType.AutoDispatch)]
    public sealed class PropertyPageHandler : IPropertyManagerPage2Handler9
    {
        private readonly Action<string> activity;

        /// <summary>创建带活动记录器的 PMP 处理器。</summary>
        internal PropertyPageHandler(Action<string> activityRecorder)
        {
            activity = activityRecorder;
        }

        public void AfterActivation() { activity("pmp_after_activation"); }
        public void AfterClose() { activity("pmp_after_close"); }
        public int OnActiveXControlCreated(int id, bool status) { return status ? 1 : 0; }
        public void OnButtonPress(int id) { activity("pmp_button_" + id); }
        public void OnCheckboxCheck(int id, bool isChecked) { activity("pmp_checkbox_" + id); }
        public void OnClose(int reason) { activity("pmp_close_" + reason); }
        public void OnComboboxEditChanged(int id, string text) { activity("pmp_combo_edit_" + id); }
        public void OnComboboxSelectionChanged(int id, int item) { activity("pmp_combo_select_" + id); }
        public void OnGainedFocus(int id) { activity("pmp_focus_" + id); }
        public void OnGroupCheck(int id, bool isChecked) { activity("pmp_group_check_" + id); }
        public void OnGroupExpand(int id, bool expanded) { activity("pmp_group_expand_" + id); }
        public bool OnHelp() { activity("pmp_help"); return true; }
        public bool OnKeystroke(int wparam, int message, int lparam, int id) { return true; }
        public void OnListboxRMBUp(int id, int positionX, int positionY) { }
        public void OnListboxSelectionChanged(int id, int item) { activity("pmp_list_select_" + id); }
        public void OnLostFocus(int id) { }
        public bool OnNextPage() { return true; }
        public void OnNumberboxChanged(int id, double value) { activity("pmp_number_" + id); }
        public void OnNumberBoxTrackingCompleted(int id, double value) { }
        public void OnOptionCheck(int id) { activity("pmp_option_" + id); }
        public void OnPopupMenuItem(int id) { activity("pmp_popup_" + id); }
        public void OnPopupMenuItemUpdate(int id, ref int retval) { retval = 1; }
        public bool OnPreview() { activity("pmp_preview"); return true; }
        public bool OnPreviousPage() { return true; }
        public void OnRedo() { activity("pmp_redo"); }
        public void OnSelectionboxCalloutCreated(int id) { }
        public void OnSelectionboxCalloutDestroyed(int id) { }
        public void OnSelectionboxFocusChanged(int id) { }
        public void OnSelectionboxListChanged(int id, int count) { activity("pmp_selection_" + id); }
        public void OnSliderPositionChanged(int id, double value) { }
        public void OnSliderTrackingCompleted(int id, double value) { }
        public bool OnSubmitSelection(int id, object selection, int selectionType, ref string itemText) { return true; }
        public bool OnTabClicked(int id) { activity("pmp_tab_" + id); return true; }
        public void OnTextboxChanged(int id, string text) { activity("pmp_text_" + id); }
        public void OnUndo() { activity("pmp_undo"); }
        public void OnWhatsNew() { activity("pmp_whats_new"); }
        public int OnWindowFromHandleControlCreated(int id, bool status) { return status ? 1 : 0; }
    }
}
