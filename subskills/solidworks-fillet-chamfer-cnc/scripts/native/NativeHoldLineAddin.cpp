/**
 * @file NativeHoldLineAddin.cpp
 * @brief SolidWorks 进程内非托管 C++ 保持线写入桥接器。
 *
 * @details 官方 ISetHoldLines 只支持进程内非托管 C++。SWBasic 负责在 SolidWorks
 * 主线程准备面组和保持线对象；本 DLL 仅把对象保留到下一次 UI 消息循环，调用一次
 * ISetHoldLines 并写出结构化证据。特征创建、命名和重建仍由 SWBasic 完成。
 */

#include <Windows.h>
#include <OleAuto.h>

#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>

#import "sldworks.tlb" raw_interfaces_only, raw_native_types, named_guids, \
    rename_namespace("SldWorksNative"), rename("GetOpenFileName", "SWGetOpenFileName")

namespace
{
SldWorksNative::ISimpleFilletFeatureData2* g_prepared_data = nullptr;
IDispatch* g_prepared_hold_line = nullptr;
long g_job_scheduled = 0;

/** @brief 失败时抛出带 HRESULT 的窄字符异常。 */
void Check(HRESULT result, const char* operation)
{
    if (SUCCEEDED(result)) return;
    std::ostringstream message;
    message << operation << " failed: 0x" << std::hex << std::uppercase
            << static_cast<unsigned long>(result);
    throw std::runtime_error(message.str());
}

/** @brief 把 UTF-8 文本转换成 UTF-16。 */
std::wstring Wide(const std::string& value)
{
    if (value.empty()) return std::wstring();
    const int length = MultiByteToWideChar(
        CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()), nullptr, 0);
    if (length <= 0) throw std::runtime_error("UTF-8 path conversion failed");
    std::wstring result(static_cast<size_t>(length), L'\0');
    MultiByteToWideChar(
        CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()),
        &result[0], length);
    return result;
}

/** @brief 返回编排器与 SolidWorks 进程共享的一次性作业文件路径。 */
std::wstring JobFilePath()
{
    wchar_t temporary[MAX_PATH] = {};
    const DWORD length = GetTempPathW(MAX_PATH, temporary);
    if (length == 0 || length >= MAX_PATH)
        throw std::runtime_error("temporary path unavailable");
    return std::wstring(temporary) + L"cad-studio-hold-line-job.txt";
}

/** @brief 从 UTF-8 作业文件读取结果文件路径。 */
std::wstring ReadResultPath()
{
    const std::wstring path = JobFilePath();
    HANDLE file = CreateFileW(
        path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
        throw std::runtime_error("hold-line job file unavailable");
    LARGE_INTEGER size = {};
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 0 || size.QuadPart > 65536)
    {
        CloseHandle(file);
        throw std::runtime_error("hold-line job file size invalid");
    }
    std::string content(static_cast<size_t>(size.QuadPart), '\0');
    DWORD read = 0;
    const BOOL read_ok = ReadFile(
        file, &content[0], static_cast<DWORD>(content.size()), &read, nullptr);
    CloseHandle(file);
    if (!read_ok || read != content.size())
        throw std::runtime_error("hold-line job file read failed");
    const size_t newline = content.find_first_of("\r\n");
    const std::string result_path = content.substr(0, newline);
    if (result_path.empty())
        throw std::runtime_error("hold-line result path missing");
    return Wide(result_path);
}

/** @brief 对 JSON 字符串中的控制字符和引号做最小安全转义。 */
std::string JsonString(const std::string& value)
{
    std::ostringstream escaped;
    escaped << '"';
    for (const unsigned char character : value)
    {
        switch (character)
        {
        case '\\': escaped << "\\\\"; break;
        case '"': escaped << "\\\""; break;
        case '\n': escaped << "\\n"; break;
        case '\r': escaped << "\\r"; break;
        case '\t': escaped << "\\t"; break;
        default:
            if (character < 0x20)
            {
                escaped << "\\u" << std::hex << std::setw(4)
                        << std::setfill('0') << static_cast<int>(character);
            }
            else
            {
                escaped << static_cast<char>(character);
            }
        }
    }
    escaped << '"';
    return escaped.str();
}

/** @brief 以替换方式写入 UTF-8 JSON 结果。 */
void WriteResult(const std::wstring& path, const std::string& json)
{
    HANDLE file = CreateFileW(
        path.c_str(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    WriteFile(file, json.data(), static_cast<DWORD>(json.size()), &written, nullptr);
    FlushFileBuffers(file);
    CloseHandle(file);
}

/** @brief 释放已为延迟调用持有的 COM 引用并复位单任务门禁。 */
void ReleasePreparedObjects()
{
    if (g_prepared_hold_line != nullptr)
    {
        g_prepared_hold_line->Release();
        g_prepared_hold_line = nullptr;
    }
    if (g_prepared_data != nullptr)
    {
        g_prepared_data->Release();
        g_prepared_data = nullptr;
    }
    InterlockedExchange(&g_job_scheduled, 0);
}

/** @brief 在 SolidWorks UI 消息循环中执行唯一一次原生 ISetHoldLines。 */
VOID CALLBACK PreparedHoldLineTimerProc(HWND, UINT, UINT_PTR timer_id, DWORD)
{
    KillTimer(nullptr, timer_id);
    std::wstring result_path;
    try
    {
        result_path = ReadResultPath();
        if (g_prepared_data == nullptr || g_prepared_hold_line == nullptr)
            throw std::runtime_error("prepared COM objects missing");
        IDispatch* hold_lines[1] = {g_prepared_hold_line};
        Check(
            g_prepared_data->ISetHoldLines(1, hold_lines),
            "ISimpleFilletFeatureData2::ISetHoldLines");
        long hold_line_count = 0;
        Check(
            g_prepared_data->GetHoldLineCount(&hold_line_count),
            "ISimpleFilletFeatureData2::GetHoldLineCount");
        if (hold_line_count != 1)
            throw std::runtime_error("hold-line count did not persist as one");
        WriteResult(
            result_path,
            "{\"status\":\"stage\",\"stage\":\"hold-lines-set\","
            "\"backend\":\"native-cpp-swb\",\"holdLineCount\":1}");
    }
    catch (const std::exception& exception)
    {
        if (!result_path.empty())
        {
            WriteResult(
                result_path,
                "{\"status\":\"blocked\",\"backend\":\"native-cpp-swb\","
                "\"error\":" + JsonString(exception.what()) + "}");
        }
    }
    ReleasePreparedObjects();
}
}  // namespace

/**
 * @brief 调度进程内 ISetHoldLines 调用。
 * @param application_unknown 当前 SolidWorks 应用对象；用于验证调用者上下文完整。
 * @param feature_data_unknown 已 Initialize(2) 且写入两个面组的 FeatureData。
 * @param hold_line_unknown 选择标记 8 对应的保持线边。
 * @return 0 表示已成功调度；实际结果由回调写入结果 JSON。
 */
extern "C" __declspec(dllexport) int __stdcall RunPreparedHoldLine(
    IUnknown* application_unknown,
    IUnknown* feature_data_unknown,
    IUnknown* hold_line_unknown)
{
    std::wstring result_path;
    try
    {
        result_path = ReadResultPath();
        if (application_unknown == nullptr || feature_data_unknown == nullptr
            || hold_line_unknown == nullptr)
            throw std::runtime_error("SWBasic did not supply complete COM pointers");
        if (InterlockedCompareExchange(&g_job_scheduled, 1, 0) != 0)
            throw std::runtime_error("another hold-line probe is still scheduled");

        Check(
            feature_data_unknown->QueryInterface(
                __uuidof(SldWorksNative::ISimpleFilletFeatureData2),
                reinterpret_cast<void**>(&g_prepared_data)),
            "QueryInterface(ISimpleFilletFeatureData2)");
        Check(
            hold_line_unknown->QueryInterface(
                IID_IDispatch,
                reinterpret_cast<void**>(&g_prepared_hold_line)),
            "QueryInterface(hold line IDispatch)");
        if (SetTimer(nullptr, 0, 1, PreparedHoldLineTimerProc) == 0)
            throw std::runtime_error("unable to schedule SolidWorks UI callback");
        return 0;
    }
    catch (const std::exception& exception)
    {
        ReleasePreparedObjects();
        if (!result_path.empty())
        {
            WriteResult(
                result_path,
                "{\"status\":\"blocked\",\"backend\":\"native-cpp-swb\","
                "\"error\":" + JsonString(exception.what()) + "}");
        }
        return 1;
    }
}
