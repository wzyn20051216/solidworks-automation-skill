use serde_json::{json, Value};
use std::io::Write;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use std::{fs, fs::OpenOptions, path::PathBuf};
use tauri::{AppHandle, Manager, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct WorkerState {
    child: Mutex<Option<Child>>,
}

fn queue_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("queue");
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir)
}

fn job_path(app: &AppHandle, id: &str) -> Result<PathBuf, String> {
    Ok(queue_dir(app)?.join(format!("{}.json", safe_id(id)?)))
}

fn safe_id(id: &str) -> Result<String, String> {
    let safe_id = id
        .chars()
        .filter(|ch| ch.is_ascii_alphanumeric() || *ch == '-' || *ch == '_')
        .collect::<String>();
    if safe_id.is_empty() {
        return Err("invalid job id".to_string());
    }
    Ok(safe_id)
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
                "cross_workspace" => reasons.push("跨工作区写入需要明确授权".to_string()),
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
    format!("unix:{}", seconds)
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

fn read_worker_health(app: &AppHandle) -> Option<Value> {
    let path = queue_dir(app).ok()?.join("worker_health.json");
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str::<Value>(&raw).ok()
}

#[tauri::command]
fn save_queue_job(app: AppHandle, job: Value) -> Result<(), String> {
    let id = job
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing job id".to_string())?;
    let payload = serde_json::to_string_pretty(&job).map_err(|error| error.to_string())?;
    fs::write(job_path(&app, id)?, payload).map_err(|error| error.to_string())
}

#[tauri::command]
fn approve_queue_job(app: AppHandle, id: String) -> Result<Value, String> {
    let path = job_path(&app, &id)?;
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut job = serde_json::from_str::<Value>(&raw).map_err(|error| error.to_string())?;
    if job.get("status").and_then(Value::as_str) != Some("approval_required") {
        return Ok(job);
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

    let payload = serde_json::to_string_pretty(&job).map_err(|error| error.to_string())?;
    fs::write(path, payload).map_err(|error| error.to_string())?;
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
fn worker_status(app: AppHandle, state: State<'_, WorkerState>) -> Result<Value, String> {
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    if let Some(child) = guard.as_mut() {
        let mut status = worker_status_from_child(child)?;
        if let Some(object) = status.as_object_mut() {
            object.insert(
                "health".to_string(),
                read_worker_health(&app).unwrap_or(Value::Null),
            );
        }
        if status.get("running").and_then(Value::as_bool) == Some(false) {
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
        let status = worker_status_from_child(child)?;
        if status.get("running").and_then(Value::as_bool) == Some(true) {
            return Ok(status);
        }
        *guard = None;
    }

    let queue = queue_dir(&app)?;
    let mut command = Command::new("python");
    command
        .current_dir(repo_path)
        .arg("-m")
        .arg("apps.desktop.cad_workbench.queue_worker")
        .arg("--watch")
        .arg("--queue-dir")
        .arg(queue);
    if enable_codex {
        command.arg("--enable-codex");
    }
    if codex_full_access {
        command.arg("--codex-full-access");
    }
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let child = command.spawn().map_err(|error| error.to_string())?;
    let pid = child.id();
    *guard = Some(child);
    Ok(json!({
        "running": true,
        "pid": pid,
        "message": "worker 已启动"
    }))
}

#[tauri::command]
fn stop_worker(state: State<'_, WorkerState>) -> Result<Value, String> {
    let mut guard = state.child.lock().map_err(|error| error.to_string())?;
    if let Some(mut child) = guard.take() {
        child.kill().map_err(|error| error.to_string())?;
        let status = child.wait().map_err(|error| error.to_string())?;
        return Ok(json!({
            "running": false,
            "pid": null,
            "message": format!("worker 已停止: {}", status)
        }));
    }
    Ok(json!({
        "running": false,
        "pid": null,
        "message": "worker 未启动"
    }))
}

#[tauri::command]
fn read_queue_jobs(app: AppHandle) -> Result<Vec<Value>, String> {
    let dir = queue_dir(&app)?;
    let mut jobs = Vec::new();

    for entry in fs::read_dir(dir).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
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
    let stdout_path = log_dir.join(format!("{}.stdout.log", safe_id));
    let stderr_path = log_dir.join(format!("{}.stderr.log", safe_id));
    Ok(json!({
        "stdoutPath": stdout_path.to_string_lossy(),
        "stderrPath": stderr_path.to_string_lossy(),
        "stdout": tail_text(stdout_path, 6000),
        "stderr": tail_text(stderr_path, 3000)
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
            worker_status,
            start_worker,
            stop_worker,
            read_queue_jobs,
            read_queue_events,
            read_queue_log_tail
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
