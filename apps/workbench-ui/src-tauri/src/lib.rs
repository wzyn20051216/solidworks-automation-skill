use serde_json::Value;
use std::{fs, path::PathBuf};
use tauri::{AppHandle, Manager};

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            save_queue_job,
            read_queue_jobs,
            read_queue_events
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
