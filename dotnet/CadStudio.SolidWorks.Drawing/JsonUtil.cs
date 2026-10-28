using System;
using System.Collections.Generic;

namespace CadStudio.SolidWorks.Drawing
{
    /// <summary>drawing_spec（JavaScriptSerializer 反序列化出的 Dictionary/ArrayList 结构）的安全读取辅助。</summary>
    internal static class JsonUtil
    {
        public static string GetString(Dictionary<string, object> dict, string key)
        {
            if (dict != null && dict.TryGetValue(key, out var value) && value != null)
                return Convert.ToString(value);
            return null;
        }

        public static Dictionary<string, object> GetDict(Dictionary<string, object> dict, string key)
        {
            if (dict != null && dict.TryGetValue(key, out var value) && value is Dictionary<string, object> d)
                return d;
            return null;
        }

        public static List<object> GetList(Dictionary<string, object> dict, string key)
        {
            if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
                return null;
            if (value is List<object> list) return list;
            if (value is object[] array) return new List<object>(array);
            if (value is System.Collections.ArrayList al)
            {
                var result = new List<object>();
                foreach (var item in al) result.Add(item);
                return result;
            }
            return null;
        }

        public static object GetValueOrNull(this Dictionary<string, object> dict, string key)
        {
            if (dict != null && dict.TryGetValue(key, out var value)) return value;
            return null;
        }
    }
}
