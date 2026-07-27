use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::io::Write;
use std::process::{Child, Command, Output, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use std::{
    fs,
    fs::OpenOptions,
    path::{Path, PathBuf},
};
use tauri::{AppHandle, Manager, State};
use wait_timeout::ChildExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
use std::os::windows::ffi::OsStrExt;

#[cfg(windows)]
use windows_sys::Win32::Storage::FileSystem::{
    MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
};

#[cfg(windows)]
use winreg::{enums::HKEY_LOCAL_MACHINE, RegKey};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct WorkerState {
    child: Mutex<Option<Child>>,
}

fn queue_dir(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("CAD_STUDIO_QUEUE_DIR") {
        if !path.trim().is_empty() {
            let dir = PathBuf::from(path);
            fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
            return Ok(dir);
        }
    }
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("queue");
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir)
}

fn wallpaper_kind(path: &Path) -> Result<&'static str, String> {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if ["png", "jpg", "jpeg", "webp", "gif", "bmp"].contains(&extension.as_str()) {
        return Ok("image");
    }
    if ["mp4", "webm", "mov", "m4v", "avi"].contains(&extension.as_str()) {
        return Ok("video");
    }
    Err(
        "不支持该壁纸格式，请选择 PNG、JPG、WEBP、GIF、BMP、MP4、WEBM、MOV、M4V 或 AVI。"
            .to_string(),
    )
}

/// @brief 将 Windows 扩展路径转换为资源协议可匹配的普通路径。
fn asset_path(path: &Path) -> PathBuf {
    #[cfg(windows)]
    {
        let value = path.to_string_lossy();
        if let Some(stripped) = value.strip_prefix(r"\\?\UNC\") {
            return PathBuf::from(format!(r"\\{stripped}"));
        }
        if let Some(stripped) = value.strip_prefix(r"\\?\") {
            return PathBuf::from(stripped);
        }
    }
    path.to_path_buf()
}

fn atomic_write(path: &Path, payload: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("json");
    let temporary = path.with_extension(format!(
        "{}.{}.{}.tmp",
        extension,
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or_default()
    ));
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .and_then(|mut file| {
            file.write_all(payload)?;
            file.sync_all()
        })
        .map_err(|error| error.to_string())?;

    replace_with_retry(&temporary, path, true)?;

    Ok(())
}

fn atomic_create(path: &Path, payload: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("json");
    let temporary = path.with_extension(format!(
        "{}.{}.{}.tmp",
        extension,
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or_default()
    ));
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .and_then(|mut file| {
            file.write_all(payload)?;
            file.sync_all()
        })
        .map_err(|error| error.to_string())?;

    let result = create_link_with_retry(&temporary, path);
    let _ = fs::remove_file(&temporary);
    result
}

fn retry_delay(attempt: usize) -> Duration {
    Duration::from_millis(25 + (attempt as u64 * 25).min(250))
}

#[cfg(windows)]
fn move_file_ex(source: &Path, target: &Path, replace: bool) -> Result<(), std::io::Error> {
    let source_wide = source
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let target_wide = target
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let mut flags = MOVEFILE_WRITE_THROUGH;
    if replace {
        flags |= MOVEFILE_REPLACE_EXISTING;
    }
    let moved = unsafe { MoveFileExW(source_wide.as_ptr(), target_wide.as_ptr(), flags) };
    if moved == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn replace_with_retry(source: &Path, target: &Path, replace: bool) -> Result<(), String> {
    let mut last_error = String::new();
    for attempt in 0..24 {
        #[cfg(windows)]
        let result = move_file_ex(source, target, replace);
        #[cfg(not(windows))]
        let result = fs::rename(source, target);

        match result {
            Ok(()) => return Ok(()),
            Err(error) => {
                last_error = error.to_string();
                thread::sleep(retry_delay(attempt));
            }
        }
    }
    let _ = fs::remove_file(source);
    Err(format!(
        "队列文件写入失败，Windows 暂时拒绝访问 {}。请关闭重复运行的 CAD Studio/Worker，或稍后重试。底层错误: {}",
        target.display(),
        last_error
    ))
}

fn create_link_with_retry(source: &Path, target: &Path) -> Result<(), String> {
    let mut last_error = String::new();
    for attempt in 0..24 {
        if target.exists() {
            return Err("任务已存在，拒绝通过创建接口覆盖。".to_string());
        }
        match fs::hard_link(source, target) {
            Ok(()) => return Ok(()),
            Err(error) => {
                if target.exists() {
                    return Err("任务已存在，拒绝通过创建接口覆盖。".to_string());
                }
                last_error = error.to_string();
                thread::sleep(retry_delay(attempt));
            }
        }
    }
    Err(format!(
        "原子创建任务失败，Windows 暂时拒绝访问 {}。请关闭重复运行的 CAD Studio/Worker，或稍后重试。底层错误: {}",
        target.display(),
        last_error
    ))
}

/// @brief 删除可能被 Windows 短暂占用的队列元数据文件。
fn remove_file_with_retry(path: &Path) -> Result<(), String> {
    let mut last_error = String::new();
    for attempt in 0..16 {
        match fs::remove_file(path) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => {
                last_error = error.to_string();
                thread::sleep(retry_delay(attempt));
            }
        }
    }
    Err(format!(
        "任务记录删除失败，Windows 暂时拒绝访问 {}。请稍后重试。底层错误: {}",
        path.display(),
        last_error
    ))
}

fn job_path(app: &AppHandle, id: &str) -> Result<PathBuf, String> {
    Ok(queue_dir(app)?.join(format!("{}.json", safe_id(id)?)))
}

fn safe_id(id: &str) -> Result<String, String> {
    if id.is_empty() || id.len() > 96 {
        return Err("invalid job id length".to_string());
    }
    let safe_id = id
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric() || *ch == '-' || *ch == '_')
        .collect::<String>();
    if safe_id.is_empty() || safe_id != id {
        return Err("invalid job id".to_string());
    }
    Ok(safe_id)
}

fn validate_new_queue_job(job: &Value) -> Result<(), String> {
    let object = job
        .as_object()
        .ok_or_else(|| "任务必须是 JSON 对象。".to_string())?;
    if object.get("schemaVersion").and_then(Value::as_str) != Some("1.0") {
        return Err("任务 schemaVersion 必须为 1.0。".to_string());
    }
    let id = object
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing job id".to_string())?;
    safe_id(id)?;
    let run_id = object
        .get("runId")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing run id".to_string())?;
    if run_id.is_empty()
        || run_id.len() > 120
        || !run_id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
    {
        return Err("invalid run id".to_string());
    }
    let kind = object
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing job kind".to_string())?;
    if !matches!(
        kind,
        "create_shell" | "import_model" | "delivery_package" | "codex_task" | "agent_task"
    ) {
        return Err(format!("未知任务类型: {kind}"));
    }
    if object.get("status").and_then(Value::as_str) != Some("queued") {
        return Err("创建接口只接受 queued 新任务。".to_string());
    }
    let progress = object
        .get("progress")
        .and_then(Value::as_i64)
        .ok_or_else(|| "progress 必须是整数。".to_string())?;
    if !(0..=100).contains(&progress) {
        return Err("progress 必须位于 0..100。".to_string());
    }
    for field in ["title", "detail", "createdAt", "updatedAt"] {
        if object
            .get(field)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .is_none()
        {
            return Err(format!("任务缺少有效字段: {field}"));
        }
    }
    if let Some(executor) = object.get("executor") {
        if !matches!(executor.as_str(), Some("mock" | "codex" | "agent")) {
            return Err("executor 必须为 mock、codex 或 agent。".to_string());
        }
    }
    if let Some(policy) = object.get("policy") {
        let policy = policy
            .as_object()
            .ok_or_else(|| "policy 必须是对象。".to_string())?;
        if let Some(sandbox) = policy.get("sandbox") {
            if !matches!(
                sandbox.as_str(),
                Some("read-only" | "workspace-write" | "danger-full-access")
            ) {
                return Err("policy.sandbox 非法。".to_string());
            }
        }
        if let Some(approval) = policy.get("approval") {
            if !matches!(approval.as_str(), Some("never" | "manual-required")) {
                return Err("policy.approval 非法。".to_string());
            }
        }
    }
    if let Some(capabilities) = object.get("capabilities") {
        if !capabilities
            .as_array()
            .map(|items| items.iter().all(Value::is_string))
            .unwrap_or(false)
        {
            return Err("capabilities 必须是字符串数组。".to_string());
        }
    }
    if let Some(knowledge) = object
        .get("uiConfig")
        .and_then(|item| item.get("knowledgeBase"))
    {
        let knowledge = knowledge
            .as_object()
            .ok_or_else(|| "uiConfig.knowledgeBase 必须是对象。".to_string())?;
        if knowledge.get("cloudEnabled").and_then(Value::as_bool) == Some(true) {
            let endpoint = knowledge
                .get("endpoint")
                .and_then(Value::as_str)
                .unwrap_or_default();
            if !endpoint.starts_with("https://") {
                return Err("启用云知识库时 endpoint 必须是 HTTPS 地址。".to_string());
            }
            if knowledge
                .get("tokenEnv")
                .and_then(Value::as_str)
                .unwrap_or("CAD_STUDIO_RAG_TOKEN")
                != "CAD_STUDIO_RAG_TOKEN"
            {
                return Err("云知识库只允许使用 CAD_STUDIO_RAG_TOKEN。".to_string());
            }
        }
        if let Some(roots) = knowledge.get("localRoots") {
            if !roots
                .as_array()
                .map(|items| {
                    items.len() <= 8
                        && items.iter().all(|item| {
                            item.as_str()
                                .map(str::trim)
                                .filter(|value| !value.is_empty())
                                .is_some()
                        })
                })
                .unwrap_or(false)
            {
                return Err("knowledgeBase.localRoots 必须是最多 8 个非空路径。".to_string());
            }
        }
    }
    if let Some(artifacts) = object.get("artifacts") {
        let artifacts = artifacts
            .as_array()
            .ok_or_else(|| "artifacts 必须是数组。".to_string())?;
        if !artifacts.is_empty() {
            return Err("创建任务时不接受前端预置交付物证据。".to_string());
        }
    }
    for field in [
        "approvedAt",
        "approvedBy",
        "approvalReasons",
        "reviewedAt",
        "reviewedBy",
        "reviewDecision",
        "artifactLedgerPath",
        "reviewGatePath",
        "reviewGate",
        "runnerId",
        "workerPid",
        "heartbeatAt",
        "leaseUntil",
        "result",
    ] {
        if object.contains_key(field) {
            return Err(format!("创建任务时禁止提交服务端字段: {field}"));
        }
    }
    Ok(())
}

fn derive_dangerous_capabilities(job: &mut Value) {
    let mut capabilities = job
        .get("capabilities")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .filter(|item| {
            !matches!(
                *item,
                "git_push"
                    | "full_access"
                    | "cad_macro"
                    | "external_network"
                    | "cross_workspace"
                    | "delete_files"
            )
        })
        .map(str::to_string)
        .collect::<Vec<_>>();
    let local_cad = job
        .get("uiConfig")
        .and_then(|item| item.get("cadRuntime"))
        .and_then(|item| item.get("localCadAutomation"))
        .and_then(Value::as_bool)
        == Some(true);
    let cloud_rag = job
        .get("uiConfig")
        .and_then(|item| item.get("knowledgeBase"))
        .and_then(|item| item.get("cloudEnabled"))
        .and_then(Value::as_bool)
        == Some(true);
    let external_knowledge_roots = job
        .get("uiConfig")
        .and_then(|item| item.get("knowledgeBase"))
        .and_then(|item| item.get("localRoots"))
        .and_then(Value::as_array)
        .map(|items| !items.is_empty())
        .unwrap_or(false);
    let policy = job.get("policy").and_then(Value::as_object);
    let require_push = policy
        .and_then(|item| item.get("requirePush"))
        .and_then(Value::as_bool)
        == Some(true);
    let full_access = policy
        .and_then(|item| item.get("sandbox"))
        .and_then(Value::as_str)
        == Some("danger-full-access");
    for (enabled, capability) in [
        (local_cad, "cad_macro"),
        (cloud_rag, "external_network"),
        (external_knowledge_roots, "cross_workspace"),
        (require_push, "git_push"),
        (full_access, "full_access"),
    ] {
        if enabled && !capabilities.iter().any(|item| item == capability) {
            capabilities.push(capability.to_string());
        }
    }
    if let Some(object) = job.as_object_mut() {
        object.insert(
            "capabilities".to_string(),
            Value::Array(capabilities.into_iter().map(Value::String).collect()),
        );
    }
}

fn approval_reasons(job: &Value) -> Vec<String> {
    let mut reasons = Vec::new();
    let policy = job.get("policy").and_then(Value::as_object);

    if policy
        .and_then(|item| item.get("approval"))
        .and_then(Value::as_str)
        == Some("manual-required")
    {
        reasons.push("任务策略要求人工审批。".to_string());
    }
    if policy
        .and_then(|item| item.get("requirePush"))
        .and_then(Value::as_bool)
        == Some(true)
    {
        reasons.push("任务请求 Git push，需要人工审批。".to_string());
    }
    if policy
        .and_then(|item| item.get("sandbox"))
        .and_then(Value::as_str)
        == Some("danger-full-access")
    {
        reasons.push("任务请求 danger-full-access 沙箱，需要人工审批。".to_string());
    }

    if let Some(capabilities) = job.get("capabilities").and_then(Value::as_array) {
        for capability in capabilities.iter().filter_map(Value::as_str) {
            match capability {
                "git_push" => reasons.push("Git 推送会把本地改动外发到远端仓库".to_string()),
                "full_access" => reasons.push("全权限沙箱可访问工作区外文件".to_string()),
                "cad_macro" => {
                    reasons.push("CAD 宏/COM 自动化可能影响当前桌面会话和工程文件".to_string())
                }
                "external_network" => reasons.push("外部网络访问可能泄露工程上下文".to_string()),
                "cross_workspace" => reasons.push("跨工作区访问需要明确授权".to_string()),
                "delete_files" => reasons.push("删除或移动文件需要人工确认".to_string()),
                _ => {}
            }
        }
    }

    let commit_and_push = job
        .get("uiConfig")
        .and_then(|item| item.get("gates"))
        .and_then(|item| item.get("commitAndPush"))
        .and_then(Value::as_bool)
        == Some(true);
    if commit_and_push
        && !reasons
            .iter()
            .any(|item| item == "任务请求 Git push，需要人工审批。")
    {
        reasons.push("界面配置要求提交并推送，需要人工审批。".to_string());
    }

    reasons
}

fn unix_timestamp_label() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    format!("unix:{seconds}")
}

fn retry_run_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("retry-{nanos}")
}

/// @brief 将失败任务重置为可安全重新领取的队列状态。
fn prepare_job_for_retry(
    job: &mut Value,
    run_id: String,
    updated_at: String,
) -> Result<(), String> {
    if job.get("status").and_then(Value::as_str) != Some("failed") {
        return Err("只有失败任务可以重新执行。".to_string());
    }
    let object = job
        .as_object_mut()
        .ok_or_else(|| "job payload must be an object".to_string())?;
    object.insert("runId".to_string(), Value::String(run_id));
    object.insert("status".to_string(), Value::String("queued".to_string()));
    object.insert("progress".to_string(), Value::Number(0.into()));
    object.insert("updatedAt".to_string(), Value::String(updated_at));
    object.insert(
        "lastMessage".to_string(),
        Value::String("用户已重新执行失败任务，等待 Worker 接单。".to_string()),
    );
    object.insert("artifacts".to_string(), Value::Array(Vec::new()));
    for field in [
        "error",
        "result",
        "artifactLedgerPath",
        "reviewGatePath",
        "reviewGate",
        "reviewedAt",
        "reviewedBy",
        "reviewDecision",
        "reviewNote",
        "runnerId",
        "workerPid",
        "heartbeatAt",
        "leaseUntil",
        "cancelRequested",
        "workerLog",
    ] {
        object.remove(field);
    }
    Ok(())
}

fn can_delete_job(job: &Value) -> bool {
    matches!(
        job.get("status").and_then(Value::as_str),
        Some("passed" | "failed" | "cancelled" | "review_required")
    )
}

fn append_queue_event(
    app: &AppHandle,
    job: &Value,
    event_type: &str,
    message: &str,
    data: Value,
) -> Result<(), String> {
    let job_id = job
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing job id".to_string())?;
    let event_dir = queue_dir(app)?.join("events");
    fs::create_dir_all(&event_dir).map_err(|error| error.to_string())?;
    let event_path = event_dir.join(format!("{}.jsonl", safe_id(job_id)?));
    let event = json!({
        "type": event_type,
        "jobId": job_id,
        "runId": job.get("runId").cloned().unwrap_or(Value::Null),
        "status": job.get("status").cloned().unwrap_or(Value::Null),
        "progress": job.get("progress").cloned().unwrap_or(Value::Null),
        "message": message,
        "at": unix_timestamp_label(),
        "worker": "cad-studio-tauri-shell",
        "data": data
    });
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(event_path)
        .map_err(|error| error.to_string())?;
    writeln!(
        file,
        "{}",
        serde_json::to_string(&event).map_err(|error| error.to_string())?
    )
    .map_err(|error| error.to_string())
}

fn worker_status_from_child(child: &mut Child) -> Result<Value, String> {
    match child.try_wait().map_err(|error| error.to_string())? {
        Some(status) => Ok(json!({
            "running": false,
            "pid": null,
            "message": format!("worker 已退出: {}", status)
        })),
        None => Ok(json!({
            "running": true,
            "pid": child.id(),
            "message": "worker 正在运行"
        })),
    }
}

fn terminate_process_tree(child: &mut Child) -> Result<std::process::ExitStatus, String> {
    #[cfg(windows)]
    {
        let mut taskkill = Command::new("taskkill");
        taskkill
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW);
        let status = taskkill.status().map_err(|error| error.to_string())?;
        if !status.success() {
            let _ = child.kill();
        }
    }
    #[cfg(not(windows))]
    child.kill().map_err(|error| error.to_string())?;

    child.wait().map_err(|error| error.to_string())
}

fn command_output_with_timeout(command: &mut Command, timeout: Duration) -> Result<Output, String> {
    let label = command.get_program().to_string_lossy().to_string();
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("启动 {label} 失败: {error}"))?;
    match child
        .wait_timeout(timeout)
        .map_err(|error| format!("等待 {label} 失败: {error}"))?
    {
        Some(_) => child
            .wait_with_output()
            .map_err(|error| format!("读取 {label} 输出失败: {error}")),
        None => {
            let _ = terminate_process_tree(&mut child);
            Err(format!(
                "{label} 检测超过 {} 秒，进程已终止。",
                timeout.as_secs()
            ))
        }
    }
}

fn read_worker_health(app: &AppHandle) -> Option<Value> {
    let path = queue_dir(app).ok()?.join("worker_health.json");
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str::<Value>(&raw).ok()
}

fn is_queue_metadata_path(path: &Path) -> bool {
    matches!(
        path.file_name().and_then(|value| value.to_str()),
        Some("worker_health.json" | "provider_verifications.json")
    )
}

fn command_exists(program: &str, args: &[&str]) -> bool {
    let mut command = Command::new(program);
    command.args(args).arg("--version");
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command_output_with_timeout(&mut command, Duration::from_secs(5))
        .map(|output| output.status.success())
        .unwrap_or(false)
}

fn python_command() -> Result<(String, Vec<String>), String> {
    if command_exists("python", &[]) {
        return Ok(("python".to_string(), Vec::new()));
    }
    if command_exists("py", &["-3"]) {
        return Ok(("py".to_string(), vec!["-3".to_string()]));
    }
    Err(
        "没有找到 Python。请先安装 Python 3，或把 python/py 加入 PATH 后再启动本地执行器。"
            .to_string(),
    )
}

fn detected_skill_root(app: &AppHandle, requested: Option<&str>) -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    if let Some(path) = requested.filter(|value| !value.trim().is_empty()) {
        candidates.push(PathBuf::from(path));
    }
    // 发布版优先使用随应用携带的受控 skill，避免被用户目录中的旧版本覆盖。
    if let Ok(resources) = app.path().resource_dir() {
        candidates.push(resources.join("skill"));
    }
    if let Ok(codex_home) = std::env::var("CODEX_HOME") {
        candidates.push(
            PathBuf::from(codex_home)
                .join("skills")
                .join("solidworks-automation"),
        );
    }
    if let Ok(home) = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")) {
        candidates.push(
            PathBuf::from(home)
                .join(".codex")
                .join("skills")
                .join("solidworks-automation"),
        );
    }
    candidates
        .into_iter()
        .find(|path| path.join("SKILL.md").is_file() && path.join("apps").join("desktop").is_dir())
        .ok_or_else(|| {
            "没有找到内置或外部 solidworks-automation skill。请重新安装 CAD Studio，或安装对应技能后重试。".to_string()
        })
}

fn command_summary_with_prefix(command: &(String, Vec<String>), args: &[&str]) -> Value {
    let mut process = Command::new(&command.0);
    process.args(&command.1).args(args);
    #[cfg(windows)]
    process.creation_flags(CREATE_NO_WINDOW);
    match command_output_with_timeout(&mut process, Duration::from_secs(10)) {
        Ok(output) => json!({
            "ok": output.status.success(),
            "message": String::from_utf8_lossy(if output.status.success() { &output.stdout } else { &output.stderr }).trim()
        }),
        Err(error) => json!({ "ok": false, "message": error.to_string() }),
    }
}

fn node_codex_command(npm_root: &std::path::Path) -> Option<(String, Vec<String>)> {
    let script = npm_root
        .join("node_modules")
        .join("@openai")
        .join("codex")
        .join("bin")
        .join("codex.js");
    if !script.is_file() {
        return None;
    }
    let bundled_node = npm_root.join("node.exe");
    let node = if bundled_node.is_file() {
        bundled_node.to_string_lossy().to_string()
    } else if command_exists("node.exe", &[]) {
        "node.exe".to_string()
    } else if command_exists("node", &[]) {
        "node".to_string()
    } else {
        return None;
    };
    Some((node, vec![script.to_string_lossy().to_string()]))
}

fn executable_command(path: PathBuf) -> Option<(String, Vec<String>)> {
    let suffix = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(suffix.as_str(), "cmd" | "bat") {
        return path.parent().and_then(node_codex_command);
    }
    Some((path.to_string_lossy().to_string(), Vec::new()))
}

fn codex_command() -> Result<(String, Vec<String>), String> {
    if let Ok(path) = std::env::var("CODEX_BIN") {
        let candidate = PathBuf::from(path);
        if candidate.is_file() {
            if let Some(command) = executable_command(candidate) {
                return Ok(command);
            }
        }
    }

    if let Ok(app_data) = std::env::var("APPDATA") {
        if let Some(command) = node_codex_command(&PathBuf::from(&app_data).join("npm")) {
            return Ok(command);
        }
    }

    if command_exists("codex.exe", &[]) {
        return Ok(("codex.exe".to_string(), Vec::new()));
    }
    if command_exists("codex", &[]) {
        return Ok(("codex".to_string(), Vec::new()));
    }

    Err(
        "没有找到 Codex CLI。请先安装 Codex，或通过 CODEX_BIN 指定 codex.exe/codex.cmd。"
            .to_string(),
    )
}

fn npm_agent_command(provider: &str) -> Option<(String, Vec<String>)> {
    let app_data = std::env::var("APPDATA").ok()?;
    let npm_root = PathBuf::from(app_data).join("npm");
    match provider {
        "gemini" => {
            let script = npm_root
                .join("node_modules")
                .join("@google")
                .join("gemini-cli")
                .join("dist")
                .join("index.js");
            if !script.is_file() {
                return None;
            }
            let node = if npm_root.join("node.exe").is_file() {
                npm_root.join("node.exe").to_string_lossy().to_string()
            } else if command_exists("node.exe", &[]) {
                "node.exe".to_string()
            } else if command_exists("node", &[]) {
                "node".to_string()
            } else {
                return None;
            };
            Some((node, vec![script.to_string_lossy().to_string()]))
        }
        "opencode" => {
            let binary = npm_root
                .join("node_modules")
                .join("opencode-ai")
                .join("bin")
                .join("opencode.exe");
            binary
                .is_file()
                .then(|| (binary.to_string_lossy().to_string(), Vec::new()))
        }
        _ => None,
    }
}

fn local_agent_command(provider: &str) -> Result<(String, Vec<String>), String> {
    if provider == "codex" {
        return codex_command();
    }
    let env_name = format!("{}_BIN", provider.to_ascii_uppercase());
    if let Ok(path) = std::env::var(&env_name) {
        let candidate = PathBuf::from(path);
        if candidate.is_file() {
            return Ok((candidate.to_string_lossy().to_string(), Vec::new()));
        }
    }
    if provider == "claude" {
        let home = std::env::var("USERPROFILE")
            .or_else(|_| std::env::var("HOME"))
            .unwrap_or_default();
        let native = PathBuf::from(home)
            .join(".local")
            .join("bin")
            .join("claude.exe");
        if native.is_file() {
            return Ok((native.to_string_lossy().to_string(), Vec::new()));
        }
    }
    if let Some(command) = npm_agent_command(provider) {
        return Ok(command);
    }
    for executable in [format!("{provider}.exe"), provider.to_string()] {
        if command_exists(&executable, &[]) {
            return Ok((executable, Vec::new()));
        }
    }
    Err(format!(
        "没有找到 {provider} CLI。可通过 {env_name} 指定入口。"
    ))
}

fn agent_provider_health(id: &str, name: &str, auth_args: &[&str], live_verified: bool) -> Value {
    match local_agent_command(id) {
        Ok(command) => {
            let version = command_summary_with_prefix(&command, &["--version"]);
            let auth = if auth_args.is_empty() {
                json!({ "ok": Value::Null, "message": "CLI 已安装；认证状态将在首次任务时验证。" })
            } else {
                command_summary_with_prefix(&command, auth_args)
            };
            let installed = version.get("ok").and_then(Value::as_bool).unwrap_or(false);
            let auth_ok = auth.get("ok").and_then(Value::as_bool);
            let status = if !installed {
                "not_installed"
            } else if auth_ok == Some(false) {
                "auth_failed"
            } else if live_verified {
                "verified"
            } else {
                "verification_required"
            };
            json!({
                "id": id,
                "name": name,
                "installed": installed,
                "ready": installed && auth_ok.unwrap_or(true),
                "verified": installed && live_verified,
                "status": status,
                "version": version,
                "auth": auth,
                "entry": std::iter::once(command.0.clone()).chain(command.1.clone()).collect::<Vec<_>>().join(" ")
            })
        }
        Err(error) => json!({
            "id": id,
            "name": name,
            "installed": false,
            "ready": false,
            "verified": false,
            "status": "not_installed",
            "version": { "ok": false, "message": error },
            "auth": { "ok": false, "message": "CLI 未安装" },
            "entry": ""
        }),
    }
}

fn collect_agent_provider_health(app: &AppHandle) -> Vec<Value> {
    let provider_verifications = queue_dir(app)
        .ok()
        .and_then(|dir| fs::read_to_string(dir.join("provider_verifications.json")).ok())
        .and_then(|payload| serde_json::from_str::<Value>(&payload).ok())
        .and_then(|payload| payload.get("providers").cloned())
        .unwrap_or_else(|| json!({}));
    let is_live_verified = |id: &str, protocol: &str| {
        let provider = match provider_verifications.get(id) {
            Some(provider) => provider,
            None => return false,
        };
        provider.get("verified").and_then(Value::as_bool) == Some(true)
            && provider.get("protocol").and_then(Value::as_str) == Some(protocol)
    };
    vec![
        agent_provider_health(
            "codex",
            "Codex",
            &["login", "status"],
            is_live_verified("codex", "codex-exec-v1"),
        ),
        agent_provider_health(
            "claude",
            "Claude Code",
            &["auth", "status"],
            is_live_verified("claude", "claude-print-v1"),
        ),
        agent_provider_health(
            "gemini",
            "Gemini CLI",
            &[],
            is_live_verified("gemini", "gemini-headless-v1"),
        ),
        agent_provider_health(
            "opencode",
            "OpenCode",
            &[],
            is_live_verified("opencode", "opencode-jsonl-v1"),
        ),
    ]
}

#[tauri::command]
fn agent_provider_runtime_health(app: AppHandle) -> Result<Value, String> {
    Ok(json!({ "agentProviders": collect_agent_provider_health(&app) }))
}

#[cfg(windows)]
fn collect_autocad_registry_paths(key: &RegKey, depth: u8, candidates: &mut Vec<PathBuf>) {
    for value_name in ["AcadLocation", "InstallDir"] {
        if let Ok(value) = key.get_value::<String, _>(value_name) {
            let path = PathBuf::from(value);
            candidates.push(if path.is_file() {
                path
            } else {
                path.join("acad.exe")
            });
        }
    }
    if depth == 0 {
        return;
    }
    for child_name in key.enum_keys().flatten() {
        if let Ok(child) = key.open_subkey(child_name) {
            collect_autocad_registry_paths(&child, depth - 1, candidates);
        }
    }
}

#[cfg(windows)]
fn autocad_registry_candidates() -> Vec<PathBuf> {
    let registry = RegKey::predef(HKEY_LOCAL_MACHINE);
    let mut candidates = Vec::new();
    for key_path in [
        r"SOFTWARE\Autodesk\AutoCAD",
        r"SOFTWARE\WOW6432Node\Autodesk\AutoCAD",
    ] {
        if let Ok(key) = registry.open_subkey(key_path) {
            collect_autocad_registry_paths(&key, 3, &mut candidates);
        }
    }
    candidates
}

#[cfg(not(windows))]
fn autocad_registry_candidates() -> Vec<PathBuf> {
    Vec::new()
}

fn detect_autocad() -> Option<PathBuf> {
    let mut candidates = autocad_registry_candidates();
    for variable in ["ProgramFiles", "ProgramFiles(x86)"] {
        if let Ok(root) = std::env::var(variable) {
            let autodesk = PathBuf::from(root).join("Autodesk");
            if let Ok(entries) = fs::read_dir(autodesk) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    let is_autocad = path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .map(|name| name.to_ascii_lowercase().starts_with("autocad"))
                        .unwrap_or(false);
                    if is_autocad {
                        candidates.push(path.join("acad.exe"));
                    }
                }
            }
        }
    }
    candidates.sort_by(|left, right| right.cmp(left));
    candidates.into_iter().find(|path| path.is_file())
}

#[tauri::command]
fn runtime_health(app: AppHandle) -> Result<Value, String> {
    let skill_root = detected_skill_root(&app, None)?;
    let home = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .map(PathBuf::from)
        .unwrap_or_default();
    let (python, solidworks) = match python_command() {
        Ok((program, args)) => {
            let mut preflight = Command::new(&program);
            preflight
                .args(&args)
                .current_dir(&skill_root)
                .arg(skill_root.join("scripts").join("sw_preflight.py"))
                .arg("--no-install");
            #[cfg(windows)]
            preflight.creation_flags(CREATE_NO_WINDOW);
            let solidworks = command_output_with_timeout(&mut preflight, Duration::from_secs(10)).map(|output| json!({
                "ok": output.status.success(),
                "message": String::from_utf8_lossy(if output.status.success() { &output.stdout } else { &output.stderr }).trim()
            })).unwrap_or_else(|error| json!({ "ok": false, "message": error.to_string() }));
            (
                json!({
                    "ok": true,
                    "entry": std::iter::once(program).chain(args).collect::<Vec<_>>().join(" "),
                    "message": "Python 3 已就绪"
                }),
                solidworks,
            )
        }
        Err(error) => (
            json!({ "ok": false, "entry": "", "message": error }),
            json!({ "ok": false, "message": "未检测 SolidWorks：本地 CAD worker 需要 Python 3。" }),
        ),
    };
    let autocad_path = detect_autocad();

    let codex = codex_command();
    let (codex_version, codex_login, codex_entry) = match codex {
        Ok(command) => (
            command_summary_with_prefix(&command, &["--version"]),
            command_summary_with_prefix(&command, &["login", "status"]),
            std::iter::once(command.0.clone())
                .chain(command.1.clone())
                .collect::<Vec<_>>()
                .join(" "),
        ),
        Err(error) => {
            let unavailable = json!({ "ok": false, "message": error });
            (unavailable.clone(), unavailable, String::new())
        }
    };
    let agent_providers = collect_agent_provider_health(&app);

    Ok(json!({
        "skillRoot": skill_root.to_string_lossy(),
        "solidworksSkillPath": skill_root.join("SKILL.md").to_string_lossy(),
        "autocadSkillPath": skill_root.join("subskills").join("autocad-automation").join("SKILL.md").to_string_lossy(),
        "defaultOutputDir": home.join("Documents").join("CADAutomationWorkbench").to_string_lossy(),
        "python": python,
        "codex": {
            "version": codex_version,
            "login": codex_login,
            "entry": codex_entry
        },
        "agentProviders": agent_providers,
        "solidworks": solidworks,
        "autocad": {
            "ok": autocad_path.is_some(),
            "path": autocad_path.map(|path| path.to_string_lossy().to_string()).unwrap_or_default()
        }
    }))
}

fn redact_secret(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return "".to_string();
    }
    if trimmed.len() <= 8 {
        return "已配置".to_string();
    }
    format!("{}***{}", &trimmed[..4], &trimmed[trimmed.len() - 4..])
}

fn object_string_value<'a>(object: &'a Value, names: &[&str]) -> Option<&'a str> {
    for name in names {
        if let Some(value) = object.get(*name).and_then(Value::as_str) {
            if !value.trim().is_empty() {
                return Some(value);
            }
        }
    }
    None
}

fn provider_summary(id: &str, provider: &Value, current: Option<&str>) -> Value {
    let settings = provider.get("settingsConfig").unwrap_or(provider);
    let name = object_string_value(provider, &["name", "label"])
        .or_else(|| object_string_value(settings, &["name", "label"]))
        .unwrap_or(id);
    let endpoint = object_string_value(
        settings,
        &[
            "baseURL", "baseUrl", "base_url", "apiBase", "api_base", "endpoint", "url",
        ],
    );
    let model = object_string_value(
        settings,
        &["model", "modelName", "defaultModel", "default_model"],
    );
    let secret = object_string_value(
        settings,
        &[
            "apiKey",
            "api_key",
            "authToken",
            "auth_token",
            "token",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
        ],
    );

    json!({
        "id": id,
        "name": name,
        "active": current == Some(id),
        "endpoint": endpoint.unwrap_or(""),
        "model": model.unwrap_or(""),
        "hasApiKey": secret.is_some(),
        "redactedApiKey": secret.map(redact_secret).unwrap_or_default()
    })
}

fn providers_for(root: &Value, group: &str) -> Vec<Value> {
    let current = root
        .get(group)
        .and_then(|item| item.get("current"))
        .and_then(Value::as_str);
    let mut providers = Vec::new();
    if let Some(map) = root
        .get(group)
        .and_then(|item| item.get("providers"))
        .and_then(Value::as_object)
    {
        for (id, provider) in map {
            providers.push(provider_summary(id, provider, current));
        }
    }
    providers
}

fn provider_models(settings: &Value) -> Vec<String> {
    let mut models = Vec::new();
    for key in ["model", "modelName", "defaultModel", "default_model"] {
        if let Some(model) = settings.get(key).and_then(Value::as_str) {
            let model = model.trim();
            if !model.is_empty() && !models.iter().any(|item| item == model) {
                models.push(model.to_string());
            }
        }
    }

    if let Some(catalog) = settings
        .get("modelCatalog")
        .and_then(|value| value.get("models"))
        .and_then(Value::as_array)
    {
        for item in catalog {
            for key in ["model", "id", "name"] {
                if let Some(model) = item.get(key).and_then(Value::as_str) {
                    let model = model.trim();
                    if !model.is_empty() && !models.iter().any(|item| item == model) {
                        models.push(model.to_string());
                    }
                    break;
                }
            }
        }
    }

    if let Some(catalog) = settings.get("models").and_then(Value::as_object) {
        for model in catalog.keys() {
            if !model.trim().is_empty() && !models.iter().any(|item| item == model) {
                models.push(model.to_string());
            }
        }
    }

    if let Some(config) = settings.get("config").and_then(Value::as_str) {
        for line in config.lines() {
            let line = line.trim();
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };
            if key.trim() != "model" {
                continue;
            }
            let model = value.trim().trim_matches(['\'', '"']);
            if !model.is_empty() && !models.iter().any(|item| item == model) {
                models.push(model.to_string());
            }
        }
    }
    models
}

fn has_managed_credential(value: &Value) -> bool {
    match value {
        Value::Object(object) => object.iter().any(|(key, value)| {
            let normalized = key.to_ascii_lowercase().replace(['-', '_'], "");
            let is_credential = ["apikey", "authtoken", "accesstoken", "bearertoken"]
                .iter()
                .any(|suffix| normalized.ends_with(suffix));
            (is_credential
                && value
                    .as_str()
                    .map(str::trim)
                    .is_some_and(|item| !item.is_empty()))
                || has_managed_credential(value)
        }),
        Value::Array(items) => items.iter().any(has_managed_credential),
        _ => false,
    }
}

fn database_provider_groups(connection: &Connection) -> Result<Value, String> {
    let mut statement = connection
        .prepare(
            "SELECT p.id, p.app_type, p.name, COALESCE(p.website_url, ''), \
             COALESCE(p.category, ''), COALESCE(p.provider_type, ''), p.is_current, \
             p.settings_config, COALESCE((SELECT group_concat(e.url, ' · ') \
             FROM provider_endpoints e WHERE e.provider_id = p.id AND e.app_type = p.app_type), '') \
             FROM providers p WHERE p.app_type IN ('codex', 'claude', 'gemini', 'opencode') \
             ORDER BY p.app_type, p.is_current DESC, COALESCE(p.sort_index, 2147483647), p.name",
        )
        .map_err(|error| format!("读取 CC Switch provider 表失败: {error}"))?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, bool>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, String>(8)?,
            ))
        })
        .map_err(|error| format!("查询 CC Switch provider 失败: {error}"))?;

    let mut groups = serde_json::Map::new();
    for row in rows {
        let (id, app_type, name, website, category, provider_type, active, raw, route_endpoint) =
            row.map_err(|error| format!("解析 CC Switch provider 失败: {error}"))?;
        let settings = serde_json::from_str::<Value>(&raw).unwrap_or(Value::Null);
        let models = provider_models(&settings);
        let official = category.eq_ignore_ascii_case("official")
            || provider_type.eq_ignore_ascii_case("official")
            || id.ends_with("-official");
        let managed_credential = has_managed_credential(&settings);
        let (credential_status, auth_label) = if official {
            ("oauth", "OAuth / 官方登录态")
        } else if managed_credential {
            ("managed", "凭据由 CC Switch 托管")
        } else {
            ("route", "路由由 CC Switch 管理")
        };
        let endpoint = if route_endpoint.trim().is_empty() {
            website
        } else {
            route_endpoint
        };
        let summary = json!({
            "id": id,
            "appType": app_type,
            "name": name,
            "active": active,
            "endpoint": endpoint,
            "model": models.join(" · "),
            "models": models,
            "hasApiKey": managed_credential,
            "redactedApiKey": "",
            "credentialStatus": credential_status,
            "authLabel": auth_label
        });
        groups
            .entry(app_type)
            .or_insert_with(|| Value::Array(Vec::new()))
            .as_array_mut()
            .expect("provider group must remain an array")
            .push(summary);
    }
    Ok(Value::Object(groups))
}

fn required_review_checks(job: &Value) -> Vec<&'static str> {
    let mut checks = vec!["native-open", "dimensions", "features", "artifacts"];
    let descriptor = format!(
        "{} {}",
        job.get("expectedOutput")
            .and_then(Value::as_str)
            .unwrap_or_default(),
        job.get("target")
            .and_then(Value::as_str)
            .unwrap_or_default()
    )
    .to_uppercase();
    if ["DWG", "DXF", "PDF", "图纸"]
        .iter()
        .any(|token| descriptor.contains(token))
    {
        checks.push("drawing");
    }
    checks
}

#[tauri::command]
fn save_queue_job(app: AppHandle, mut job: Value) -> Result<(), String> {
    let id = job
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing job id".to_string())?;
    let path = job_path(&app, id)?;
    if path.exists() {
        return Err("任务已存在，拒绝通过创建接口覆盖。".to_string());
    }
    validate_new_queue_job(&job)?;
    derive_dangerous_capabilities(&mut job);
    let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
    atomic_create(&path, &payload)
}

fn transition_review_job(
    app: &AppHandle,
    id: &str,
    approved: bool,
    reason: String,
    checks: Vec<String>,
) -> Result<Value, String> {
    let path = job_path(app, id)?;
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    if job.get("status").and_then(Value::as_str) != Some("review_required") {
        return Err("只有待复核任务可以执行人工复核。".to_string());
    }

    let review_note = reason.trim().to_string();
    if review_note.chars().count() < if approved { 8 } else { 4 } {
        return Err("请填写具体复核说明，不能使用空白或默认结论。".to_string());
    }
    let review_checks = checks
        .into_iter()
        .map(|item| item.trim().to_string())
        .filter(|item| !item.is_empty())
        .collect::<Vec<_>>();
    if approved {
        let missing_checks = required_review_checks(&job)
            .into_iter()
            .filter(|required| !review_checks.iter().any(|item| item == required))
            .collect::<Vec<_>>();
        if !missing_checks.is_empty() {
            return Err(format!(
                "通过复核前必须完成当前任务的全部人工检查项，缺少: {}",
                missing_checks.join(", ")
            ));
        }
    }
    let artifact_evidence = job
        .get("artifacts")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|item| {
                    let object = item.as_object()?;
                    Some(json!({
                        "path": object.get("path"),
                        "sizeBytes": object.get("sizeBytes"),
                        "sha256": object.get("sha256"),
                        "producedThisRun": object.get("producedThisRun")
                    }))
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let warning_evidence = job
        .get("reviewGate")
        .and_then(|gate| gate.get("checks"))
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter(|item| item.get("status").and_then(Value::as_str) == Some("warning"))
                .cloned()
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let reviewed_at = unix_timestamp_label();
    let status = if approved { "passed" } else { "failed" };
    let decision = if approved { "approved" } else { "rejected" };
    let message = if approved {
        "人工复核已通过，任务可以交付。"
    } else {
        "人工复核未通过，任务已驳回。"
    };

    let object = job
        .as_object_mut()
        .ok_or_else(|| "job payload must be an object".to_string())?;
    object.insert("status".to_string(), Value::String(status.to_string()));
    object.insert("updatedAt".to_string(), Value::String(reviewed_at.clone()));
    object.insert("reviewedAt".to_string(), Value::String(reviewed_at.clone()));
    object.insert(
        "reviewedBy".to_string(),
        Value::String("local-user".to_string()),
    );
    object.insert(
        "reviewDecision".to_string(),
        Value::String(decision.to_string()),
    );
    object.insert("reviewNote".to_string(), Value::String(review_note.clone()));
    object.insert(
        "lastMessage".to_string(),
        Value::String(message.to_string()),
    );
    if approved {
        object.remove("error");
    } else {
        object.insert("error".to_string(), Value::String(review_note.clone()));
    }
    if let Some(gate) = object.get_mut("reviewGate").and_then(Value::as_object_mut) {
        gate.insert(
            "manualReview".to_string(),
            json!({
                "status": decision,
                "reviewedBy": "local-user",
                "reviewedAt": reviewed_at,
                "note": review_note.clone(),
                "checks": review_checks.clone(),
                "artifacts": artifact_evidence,
                "warnings": warning_evidence
            }),
        );
    }

    let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
    atomic_write(&path, &payload)?;
    append_queue_event(
        app,
        &job,
        if approved {
            "review.manual_approved"
        } else {
            "review.manual_rejected"
        },
        message,
        json!({ "reviewedBy": "local-user", "note": review_note, "checks": review_checks }),
    )?;
    Ok(job)
}

#[tauri::command]
fn approve_review_job(
    app: AppHandle,
    id: String,
    reason: String,
    checks: Vec<String>,
) -> Result<Value, String> {
    transition_review_job(&app, &id, true, reason, checks)
}

#[tauri::command]
fn reject_review_job(app: AppHandle, id: String, reason: String) -> Result<Value, String> {
    transition_review_job(&app, &id, false, reason, Vec::new())
}

#[tauri::command]
fn approve_queue_job(app: AppHandle, id: String) -> Result<Value, String> {
    let path = job_path(&app, &id)?;
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    if job.get("status").and_then(Value::as_str) != Some("approval_required") {
        return Err("只有待审批任务可以批准执行。".to_string());
    }

    let reasons = approval_reasons(&job);
    let approved_policy_reasons = Value::Array(reasons.into_iter().map(Value::String).collect());
    let object = job
        .as_object_mut()
        .ok_or_else(|| "job payload must be an object".to_string())?;
    object.insert(
        "approvedBy".to_string(),
        Value::String("local-user".to_string()),
    );
    object.insert(
        "approvedAt".to_string(),
        Value::String(unix_timestamp_label()),
    );
    object.insert("approvedPolicyReasons".to_string(), approved_policy_reasons);
    object.insert("status".to_string(), Value::String("queued".to_string()));
    object.insert(
        "updatedAt".to_string(),
        Value::String(unix_timestamp_label()),
    );
    object.insert(
        "lastMessage".to_string(),
        Value::String("人工审批已通过，任务重新进入队列。".to_string()),
    );

    let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
    atomic_write(&path, &payload)?;
    append_queue_event(
        &app,
        &job,
        "policy.approved",
        "人工审批已通过",
        json!({ "approvedBy": "local-user" }),
    )?;
    Ok(job)
}

#[tauri::command]
fn retry_queue_job(app: AppHandle, id: String) -> Result<Value, String> {
    let path = job_path(&app, &id)?;
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    let previous_run_id = job.get("runId").cloned().unwrap_or(Value::Null);
    let next_run_id = retry_run_id();
    prepare_job_for_retry(&mut job, next_run_id.clone(), unix_timestamp_label())?;

    let _ = fs::remove_file(path.with_extension("json.cancel"));
    let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
    atomic_write(&path, &payload)?;
    append_queue_event(
        &app,
        &job,
        "run.requeued_by_user",
        "用户已重新执行失败任务",
        json!({ "previousRunId": previous_run_id, "runId": next_run_id }),
    )?;
    Ok(job)
}

#[tauri::command]
fn delete_queue_job(app: AppHandle, id: String) -> Result<Value, String> {
    let safe_id = safe_id(&id)?;
    let queue = queue_dir(&app)?;
    let path = queue.join(format!("{safe_id}.json"));
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    if !can_delete_job(&job) {
        return Err("任务仍在排队、审批或执行中，请先取消任务再删除。".to_string());
    }

    for metadata_path in [
        queue.join("events").join(format!("{safe_id}.jsonl")),
        queue.join("logs").join(format!("{safe_id}.stdout.log")),
        queue.join("logs").join(format!("{safe_id}.stderr.log")),
        queue.join("ledgers").join(format!("{safe_id}.ledger.json")),
        queue.join("reviews").join(format!("{safe_id}.review.json")),
        path.with_extension("json.cancel"),
        PathBuf::from(format!("{}.lock", path.display())),
    ] {
        remove_file_with_retry(&metadata_path)?;
    }
    remove_file_with_retry(&path)?;
    Ok(json!({ "id": safe_id, "deleted": true }))
}

/// @brief 将用户选择的壁纸复制到应用数据目录，供受限资源协议稳定加载。
#[tauri::command]
fn import_wallpaper(app: AppHandle, source_path: String) -> Result<Value, String> {
    let source = PathBuf::from(source_path.trim());
    let kind = wallpaper_kind(&source)?;
    let metadata = fs::metadata(&source).map_err(|error| format!("壁纸文件无法读取: {error}"))?;
    if !metadata.is_file() {
        return Err("选择的壁纸不是文件。".to_string());
    }
    if metadata.len() > 256 * 1024 * 1024 {
        return Err("壁纸文件超过 256 MB，请先压缩后再导入。".to_string());
    }

    let cache_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("wallpapers");
    fs::create_dir_all(&cache_dir).map_err(|error| error.to_string())?;
    let canonical_source = source
        .canonicalize()
        .map_err(|error| format!("壁纸路径无效: {error}"))?;
    let canonical_cache = cache_dir
        .canonicalize()
        .map_err(|error| error.to_string())?;
    let file_name = canonical_source
        .file_name()
        .ok_or_else(|| "壁纸文件名无效。".to_string())?;
    let display_name = canonical_source
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("我的壁纸")
        .to_string();

    let cached_path = if canonical_source.starts_with(&canonical_cache) {
        canonical_source
    } else {
        let target = cache_dir.join(file_name);
        let extension = target
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("wallpaper");
        let temporary = target.with_extension(format!("{extension}.{}.tmp", std::process::id()));
        fs::copy(&canonical_source, &temporary)
            .map_err(|error| format!("壁纸复制失败: {error}"))?;
        replace_with_retry(&temporary, &target, true)?;
        target
    };

    Ok(json!({
        "path": asset_path(&cached_path).to_string_lossy(),
        "name": display_name,
        "kind": kind
    }))
}

#[tauri::command]
fn worker_status(app: AppHandle, state: State<'_, WorkerState>) -> Result<Value, String> {
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    if let Some(child) = guard.as_mut() {
        let pid = child.id();
        let mut status = worker_status_from_child(child)?;
        if let Some(object) = status.as_object_mut() {
            let health = read_worker_health(&app)
                .filter(|value| value.get("pid").and_then(Value::as_u64) == Some(pid.into()));
            object.insert("health".to_string(), health.unwrap_or(Value::Null));
        }
        if status.get("running").and_then(Value::as_bool) == Some(false) {
            let recovered = recover_jobs_owned_by_worker(&app, pid)?;
            if let Some(object) = status.as_object_mut() {
                object.insert("recoveredJobs".to_string(), Value::Number(recovered.into()));
            }
            *guard = None;
        }
        return Ok(status);
    }
    Ok(json!({
        "running": false,
        "pid": null,
        "message": "worker 未启动",
        "health": read_worker_health(&app)
    }))
}

#[tauri::command]
fn start_worker(
    app: AppHandle,
    state: State<'_, WorkerState>,
    repo_path: String,
    enable_codex: bool,
    codex_full_access: bool,
) -> Result<Value, String> {
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    if let Some(child) = guard.as_mut() {
        let pid = child.id();
        let status = worker_status_from_child(child)?;
        if status.get("running").and_then(Value::as_bool) == Some(true) {
            return Ok(status);
        }
        recover_jobs_owned_by_worker(&app, pid)?;
        *guard = None;
    }

    let queue = queue_dir(&app)?;
    let _ = fs::remove_file(queue.join("worker_health.json"));
    let repo_path = detected_skill_root(&app, Some(&repo_path))?;
    let (python, python_args) = python_command()?;
    let mut command = Command::new(python);
    command.args(python_args);
    command
        .current_dir(repo_path)
        .arg("-m")
        .arg("apps.desktop.cad_workbench.queue_worker")
        .arg("--watch")
        .arg("--queue-dir")
        .arg(queue);
    if enable_codex {
        command.arg("--enable-codex");
        command.arg("--enable-agent");
    }
    if codex_full_access {
        command.arg("--codex-full-access");
    }
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let child = command
        .spawn()
        .map_err(|error| format!("本地执行器启动失败: {error}"))?;
    let pid = child.id();
    *guard = Some(child);
    Ok(json!({
        "running": true,
        "pid": pid,
        "message": "worker 已启动"
    }))
}

#[tauri::command]
fn cancel_queue_job(app: AppHandle, id: String) -> Result<Value, String> {
    let path = job_path(&app, &id)?;
    atomic_write(&path.with_extension("json.cancel"), b"cancel\n")
        .map_err(|error| format!("取消标记写入失败: {error}"))?;
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    let current_status = job
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if !matches!(
        current_status.as_str(),
        "queued" | "running" | "approval_required"
    ) {
        let _ = fs::remove_file(path.with_extension("json.cancel"));
        return Ok(job);
    }
    let was_running = current_status == "running";
    let object = job
        .as_object_mut()
        .ok_or_else(|| "job payload must be an object".to_string())?;
    object.insert("cancelRequested".to_string(), Value::Bool(true));
    object.insert(
        "updatedAt".to_string(),
        Value::String(unix_timestamp_label()),
    );
    object.insert(
        "lastMessage".to_string(),
        Value::String(
            if was_running {
                "已请求取消，等待当前进程安全停止。"
            } else {
                "任务已取消。"
            }
            .to_string(),
        ),
    );
    if !was_running {
        object.insert("status".to_string(), Value::String("cancelled".to_string()));
        object.insert("progress".to_string(), Value::Number(0.into()));
    }
    if !was_running {
        let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
        atomic_write(&path, &payload)?;
    }
    append_queue_event(
        &app,
        &job,
        if was_running {
            "run.cancel_requested"
        } else {
            "run.cancelled"
        },
        if was_running {
            "用户已请求取消"
        } else {
            "用户已取消任务"
        },
        json!({}),
    )?;
    Ok(job)
}

fn recover_jobs_owned_by_worker(app: &AppHandle, worker_pid: u32) -> Result<u64, String> {
    let dir = queue_dir(app)?;
    let mut recovered = 0_u64;
    for entry in fs::read_dir(&dir).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json")
            || is_queue_metadata_path(&path)
        {
            continue;
        }
        let raw = match fs::read_to_string(&path) {
            Ok(raw) => raw,
            Err(_) => continue,
        };
        let mut job = match serde_json::from_str::<Value>(&raw) {
            Ok(job) => job,
            Err(_) => continue,
        };
        if job.get("status").and_then(Value::as_str) != Some("running")
            || job.get("workerPid").and_then(Value::as_u64) != Some(worker_pid as u64)
        {
            continue;
        }

        let cancel_marker = path.with_extension("json.cancel");
        let cancel_requested = cancel_marker.exists()
            || job
                .get("cancelRequested")
                .and_then(Value::as_bool)
                .unwrap_or(false);
        let status = if cancel_requested {
            "cancelled"
        } else {
            "queued"
        };
        let message = if cancel_requested {
            "Worker 已停止，取消请求已生效。"
        } else {
            "Worker 已停止，未完成任务已重新排队。"
        };
        let object = job
            .as_object_mut()
            .ok_or_else(|| "job payload must be an object".to_string())?;
        object.insert("status".to_string(), Value::String(status.to_string()));
        object.insert("progress".to_string(), Value::Number(0.into()));
        object.insert(
            "updatedAt".to_string(),
            Value::String(unix_timestamp_label()),
        );
        object.insert(
            "lastMessage".to_string(),
            Value::String(message.to_string()),
        );
        object.remove("runnerId");
        object.remove("workerPid");
        object.remove("heartbeatAt");
        object.remove("leaseUntil");
        if !cancel_requested {
            object.remove("cancelRequested");
            let _ = fs::remove_file(&cancel_marker);
        }

        let payload = serde_json::to_vec_pretty(&job).map_err(|error| error.to_string())?;
        atomic_write(&path, &payload)?;
        append_queue_event(
            app,
            &job,
            if cancel_requested {
                "run.cancelled"
            } else {
                "run.requeued_worker_stopped"
            },
            message,
            json!({ "workerPid": worker_pid }),
        )?;
        recovered += 1;
    }
    Ok(recovered)
}

fn stop_worker_process(app: &AppHandle) -> Result<Value, String> {
    let state = app.state::<WorkerState>();
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    if let Some(mut child) = guard.take() {
        let pid = child.id();
        match terminate_process_tree(&mut child) {
            Ok(status) => {
                let recovered = recover_jobs_owned_by_worker(app, pid)?;
                return Ok(json!({
                    "running": false,
                    "pid": null,
                    "recoveredJobs": recovered,
                    "message": format!("worker 已停止: {}；恢复任务 {} 个", status, recovered)
                }));
            }
            Err(error) => {
                *guard = Some(child);
                return Err(format!("worker 停止失败: {error}"));
            }
        }
    }
    Ok(json!({
        "running": false,
        "pid": null,
        "message": "worker 未启动"
    }))
}

#[tauri::command]
fn stop_worker(app: AppHandle) -> Result<Value, String> {
    stop_worker_process(&app)
}

#[tauri::command]
fn close_app(app: AppHandle) -> Result<(), String> {
    let _ = stop_worker_process(&app);
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn read_queue_jobs(app: AppHandle) -> Result<Vec<Value>, String> {
    let dir = queue_dir(&app)?;
    let mut jobs = Vec::new();

    for entry in fs::read_dir(dir).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json")
            || is_queue_metadata_path(&path)
        {
            continue;
        }
        let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
        if let Ok(job) = serde_json::from_str::<Value>(&raw) {
            jobs.push(job);
        }
    }

    Ok(jobs)
}

#[tauri::command]
fn read_queue_events(app: AppHandle, id: String) -> Result<Vec<Value>, String> {
    let path = queue_dir(&app)?
        .join("events")
        .join(format!("{}.jsonl", safe_id(&id)?));
    if !path.exists() {
        return Ok(Vec::new());
    }

    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut events = Vec::new();
    for line in raw.lines().rev().take(12) {
        if let Ok(event) = serde_json::from_str::<Value>(line) {
            events.push(event);
        }
    }
    events.reverse();
    Ok(events)
}

fn tail_text(path: PathBuf, max_chars: usize) -> String {
    let raw = fs::read_to_string(path).unwrap_or_default();
    if raw.chars().count() <= max_chars {
        return raw;
    }
    raw.chars()
        .rev()
        .take(max_chars)
        .collect::<String>()
        .chars()
        .rev()
        .collect()
}

#[tauri::command]
fn read_queue_log_tail(app: AppHandle, id: String) -> Result<Value, String> {
    let safe_id = safe_id(&id)?;
    let log_dir = queue_dir(&app)?.join("logs");
    let stdout_path = log_dir.join(format!("{safe_id}.stdout.log"));
    let stderr_path = log_dir.join(format!("{safe_id}.stderr.log"));
    Ok(json!({
        "stdoutPath": stdout_path.to_string_lossy(),
        "stderrPath": stderr_path.to_string_lossy(),
        "stdout": tail_text(stdout_path, 6000),
        "stderr": tail_text(stderr_path, 3000)
    }))
}

#[tauri::command]
fn sync_cc_switch_config() -> Result<Value, String> {
    let home = std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .map_err(|_| "无法定位用户目录，不能读取 CC Switch 配置。".to_string())?;
    let root = PathBuf::from(home).join(".cc-switch");
    let database_path = root.join("cc-switch.db");
    let config_path = root.join("config.json");
    let settings_path = root.join("settings.json");
    if database_path.exists() {
        let connection = Connection::open_with_flags(
            &database_path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|error| format!("无法只读打开 CC Switch 数据库: {error}"))?;
        let providers = database_provider_groups(&connection)?;
        let current_for = |group: &str| {
            providers
                .get(group)
                .and_then(Value::as_array)
                .and_then(|items| {
                    items
                        .iter()
                        .find(|item| item.get("active") == Some(&Value::Bool(true)))
                })
                .and_then(|item| item.get("id"))
                .and_then(Value::as_str)
                .unwrap_or("")
        };
        let settings = fs::read_to_string(&settings_path)
            .ok()
            .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
            .unwrap_or(Value::Null);
        return Ok(json!({
            "source": "CC Switch",
            "storage": "sqlite",
            "rootPath": root.to_string_lossy(),
            "configPath": database_path.to_string_lossy(),
            "databasePath": database_path.to_string_lossy(),
            "settingsPath": settings_path.to_string_lossy(),
            "syncedAt": unix_timestamp_label(),
            "codexCurrent": current_for("codex"),
            "claudeCurrent": current_for("claude"),
            "geminiCurrent": current_for("gemini"),
            "opencodeCurrent": current_for("opencode"),
            "codexProviders": providers.get("codex").cloned().unwrap_or_else(|| json!([])),
            "claudeProviders": providers.get("claude").cloned().unwrap_or_else(|| json!([])),
            "geminiProviders": providers.get("gemini").cloned().unwrap_or_else(|| json!([])),
            "opencodeProviders": providers.get("opencode").cloned().unwrap_or_else(|| json!([])),
            "providersByAgent": providers,
            "settings": {
                "currentProviderCodex": settings.get("currentProviderCodex").and_then(Value::as_str).unwrap_or(""),
                "currentProviderClaude": settings.get("currentProviderClaude").and_then(Value::as_str).unwrap_or(""),
                "enableLocalProxy": settings.get("enableLocalProxy").and_then(Value::as_bool).unwrap_or(false),
                "enableFailoverToggle": settings.get("enableFailoverToggle").and_then(Value::as_bool).unwrap_or(false),
                "skillSyncMethod": settings.get("skillSyncMethod").and_then(Value::as_str).unwrap_or("")
            }
        }));
    }
    if !config_path.exists() {
        return Err(
            "没有找到 .cc-switch/cc-switch.db 或 config.json。请先确认 CC Switch 已安装并完成配置。".to_string(),
        );
    }

    let config_raw = fs::read_to_string(&config_path).map_err(|error| error.to_string())?;
    let config = serde_json::from_str::<Value>(&config_raw).map_err(|error| error.to_string())?;
    let settings = fs::read_to_string(&settings_path)
        .ok()
        .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
        .unwrap_or(Value::Null);

    Ok(json!({
        "source": "CC Switch",
        "storage": "legacy-json",
        "rootPath": root.to_string_lossy(),
        "configPath": config_path.to_string_lossy(),
        "settingsPath": settings_path.to_string_lossy(),
        "syncedAt": unix_timestamp_label(),
        "codexCurrent": config.get("codex").and_then(|item| item.get("current")).and_then(Value::as_str).unwrap_or(""),
        "claudeCurrent": config.get("claude").and_then(|item| item.get("current")).and_then(Value::as_str).unwrap_or(""),
        "codexProviders": providers_for(&config, "codex"),
        "claudeProviders": providers_for(&config, "claude"),
        "geminiProviders": providers_for(&config, "gemini"),
        "opencodeProviders": providers_for(&config, "opencode"),
        "settings": {
            "currentProviderCodex": settings.get("currentProviderCodex").and_then(Value::as_str).unwrap_or(""),
            "currentProviderClaude": settings.get("currentProviderClaude").and_then(Value::as_str).unwrap_or(""),
            "enableLocalProxy": settings.get("enableLocalProxy").and_then(Value::as_bool).unwrap_or(false),
            "enableFailoverToggle": settings.get("enableFailoverToggle").and_then(Value::as_bool).unwrap_or(false),
            "skillSyncMethod": settings.get("skillSyncMethod").and_then(Value::as_str).unwrap_or("")
        }
    }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(WorkerState {
            child: Mutex::new(None),
        })
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            save_queue_job,
            approve_queue_job,
            approve_review_job,
            reject_review_job,
            retry_queue_job,
            delete_queue_job,
            import_wallpaper,
            worker_status,
            start_worker,
            stop_worker,
            close_app,
            cancel_queue_job,
            read_queue_jobs,
            read_queue_events,
            read_queue_log_tail,
            sync_cc_switch_config,
            agent_provider_runtime_health,
            runtime_health
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                let _ = stop_worker_process(app);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{
        asset_path, can_delete_job, database_provider_groups, derive_dangerous_capabilities,
        is_queue_metadata_path, prepare_job_for_retry, validate_new_queue_job, wallpaper_kind,
    };
    use rusqlite::{params, Connection};
    use serde_json::json;
    use std::path::Path;

    fn queued_job() -> serde_json::Value {
        json!({
            "schemaVersion": "1.0",
            "id": "job-test-1",
            "runId": "run-test-1",
            "kind": "codex_task",
            "executor": "codex",
            "title": "测试任务",
            "detail": "验证任务入口",
            "status": "queued",
            "progress": 0,
            "createdAt": "2026-07-26T00:00:00+08:00",
            "updatedAt": "2026-07-26T00:00:00+08:00",
            "policy": {
                "sandbox": "danger-full-access",
                "approval": "never",
                "requirePush": false
            },
            "uiConfig": {
                "cadRuntime": {"localCadAutomation": true},
                "knowledgeBase": {
                    "cloudEnabled": true,
                    "endpoint": "https://rag.example.test/retrieve",
                    "tokenEnv": "CAD_STUDIO_RAG_TOKEN",
                    "localRoots": ["D:/company-standards"]
                }
            },
            "artifacts": []
        })
    }

    #[test]
    fn queue_metadata_files_are_not_exposed_as_jobs() {
        assert!(is_queue_metadata_path(Path::new("worker_health.json")));
        assert!(is_queue_metadata_path(Path::new(
            "provider_verifications.json"
        )));
        assert!(!is_queue_metadata_path(Path::new("job-123.json")));
    }

    #[test]
    fn validates_new_job_and_derives_dangerous_capabilities() {
        let mut job = queued_job();
        validate_new_queue_job(&job).expect("valid queued job");
        derive_dangerous_capabilities(&mut job);
        let capabilities = job["capabilities"].as_array().expect("capabilities array");
        for expected in [
            "cad_macro",
            "external_network",
            "cross_workspace",
            "full_access",
        ] {
            assert!(capabilities
                .iter()
                .any(|item| item.as_str() == Some(expected)));
        }
    }

    #[test]
    fn rejects_frontend_supplied_review_evidence() {
        let mut job = queued_job();
        job["reviewGate"] = json!({"status": "pass"});
        let error = validate_new_queue_job(&job).expect_err("review evidence must be server-owned");
        assert!(error.contains("reviewGate"));
    }

    #[test]
    fn rejects_cloud_rag_with_arbitrary_token_environment() {
        let mut job = queued_job();
        job["uiConfig"]["knowledgeBase"]["tokenEnv"] = json!("AWS_SECRET_ACCESS_KEY");
        let error = validate_new_queue_job(&job).expect_err("arbitrary env token must be rejected");
        assert!(error.contains("CAD_STUDIO_RAG_TOKEN"));
    }

    #[test]
    fn retry_resets_failed_runtime_state_and_preserves_approval() {
        let mut job = queued_job();
        job["status"] = json!("failed");
        job["progress"] = json!(100);
        job["attempt"] = json!(2);
        job["error"] = json!("Windows 拒绝访问");
        job["result"] = json!({"message": "旧结果"});
        job["artifacts"] = json!([{"path": "old.step"}]);
        job["artifactLedgerPath"] = json!("old-ledger.json");
        job["reviewGate"] = json!({"status": "fail"});
        job["workerLog"] = json!([{"status": "failed"}]);
        job["runnerId"] = json!("old-runner");
        job["workerPid"] = json!(1234);
        job["approvedAt"] = json!("unix:1");
        job["approvedBy"] = json!("local-user");
        job["approvedPolicyReasons"] = json!(["已批准"]);

        prepare_job_for_retry(&mut job, "retry-test-1".to_string(), "unix:2".to_string())
            .expect("failed job should be retryable");

        assert_eq!(job["status"], "queued");
        assert_eq!(job["progress"], 0);
        assert_eq!(job["runId"], "retry-test-1");
        assert_eq!(job["attempt"], 2);
        assert_eq!(job["approvedBy"], "local-user");
        assert!(job.get("error").is_none());
        assert!(job.get("result").is_none());
        assert!(job.get("reviewGate").is_none());
        assert!(job.get("workerLog").is_none());
        assert_eq!(job["artifacts"], json!([]));
    }

    #[test]
    fn retry_rejects_non_failed_job() {
        let mut job = queued_job();

        let error =
            prepare_job_for_retry(&mut job, "retry-test-2".to_string(), "unix:2".to_string())
                .expect_err("queued job must not be retried");

        assert!(error.contains("只有失败任务"));
    }

    #[test]
    fn delete_only_accepts_terminal_or_reviewable_jobs() {
        let mut job = queued_job();
        for status in ["queued", "running", "approval_required"] {
            job["status"] = json!(status);
            assert!(!can_delete_job(&job), "{status} must be cancelled first");
        }
        for status in ["passed", "failed", "cancelled", "review_required"] {
            job["status"] = json!(status);
            assert!(can_delete_job(&job), "{status} should be deletable");
        }
    }

    #[test]
    fn wallpaper_formats_are_restricted_to_renderable_media() {
        assert_eq!(wallpaper_kind(Path::new("desk.WEBP")), Ok("image"));
        assert_eq!(wallpaper_kind(Path::new("loop.mp4")), Ok("video"));
        assert!(wallpaper_kind(Path::new("payload.exe")).is_err());
    }

    #[test]
    fn asset_paths_do_not_expose_windows_verbatim_prefixes() {
        let path = asset_path(Path::new(r"\\?\C:\Users\test\wallpaper.png"));
        assert_eq!(path, Path::new(r"C:\Users\test\wallpaper.png"));
    }

    #[test]
    fn reads_cc_switch_sqlite_groups_without_exposing_credentials() {
        let connection = Connection::open_in_memory().expect("in-memory sqlite");
        connection
            .execute_batch(
                "CREATE TABLE providers (
                    id TEXT NOT NULL, app_type TEXT NOT NULL, name TEXT NOT NULL,
                    settings_config TEXT NOT NULL, website_url TEXT, category TEXT,
                    provider_type TEXT, is_current BOOLEAN NOT NULL DEFAULT 0,
                    sort_index INTEGER, PRIMARY KEY (id, app_type)
                );
                CREATE TABLE provider_endpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, provider_id TEXT NOT NULL,
                    app_type TEXT NOT NULL, url TEXT NOT NULL
                );",
            )
            .expect("cc switch schema");
        connection
            .execute(
                "INSERT INTO providers VALUES (?1, 'codex', '工作路由', ?2, '', 'custom', '', 1, 0)",
                params![
                    "route-1",
                    r#"{"auth":{"OPENAI_API_KEY":"secret-must-not-leak"},"config":"model = \"gpt-5.5\""}"#
                ],
            )
            .expect("codex provider");
        connection
            .execute(
                "INSERT INTO providers VALUES ('claude-official', 'claude', 'Claude Official', '{}', 'https://claude.ai', 'official', '', 0, 0)",
                [],
            )
            .expect("claude provider");
        connection
            .execute(
                "INSERT INTO provider_endpoints (provider_id, app_type, url) VALUES ('route-1', 'codex', 'https://route.example/v1')",
                [],
            )
            .expect("provider endpoint");

        let groups = database_provider_groups(&connection).expect("provider groups");
        let codex = groups["codex"].as_array().expect("codex group");
        assert_eq!(codex.len(), 1);
        assert_eq!(codex[0]["active"], true);
        assert_eq!(codex[0]["model"], "gpt-5.5");
        assert_eq!(codex[0]["endpoint"], "https://route.example/v1");
        assert_eq!(codex[0]["authLabel"], "凭据由 CC Switch 托管");
        assert_eq!(groups["claude"][0]["authLabel"], "OAuth / 官方登录态");
        assert!(!groups.to_string().contains("secret-must-not-leak"));
    }
}
