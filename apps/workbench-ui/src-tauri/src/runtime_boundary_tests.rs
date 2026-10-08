//! @brief 四种 Agent、配置读取与链接边界的回归用例。
use super::{
    cc_switch_file_path, command_summary_with_prefix, read_cc_switch_file, supported_program_name,
};
use std::{
    fs,
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("cadstudio-boundary-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        // 递归清理前确认目标仍在本轮命名的临时根内。
        if let (Ok(target), Ok(parent)) =
            (self.0.canonicalize(), std::env::temp_dir().canonicalize())
        {
            if target.parent() == Some(parent.as_path())
                && target
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cadstudio-boundary-")
            {
                let _ = fs::remove_dir_all(target);
            }
        }
    }
}

#[test]
fn all_existing_agent_path_names_remain_supported() {
    for name in [
        "codex",
        "codex.exe",
        "claude",
        "claude.exe",
        "gemini",
        "gemini.exe",
        "opencode",
        "opencode.exe",
    ] {
        assert!(
            supported_program_name(name),
            "PATH fallback was lost: {name}"
        );
    }
    assert!(!supported_program_name("arbitrary-program"));
}

#[test]
fn fixed_json_and_database_paths_share_the_same_boundary() {
    let fixture = Fixture::new();
    for name in ["config.json", "settings.json", "cc-switch.db"] {
        fs::write(fixture.0.join(name), "fixture").unwrap();
        assert!(cc_switch_file_path(&fixture.0, name)
            .unwrap()
            .starts_with(fixture.0.canonicalize().unwrap()));
    }
    assert_eq!(
        read_cc_switch_file(&fixture.0, "config.json").unwrap(),
        "fixture"
    );
    assert!(cc_switch_file_path(&fixture.0, "../config.json").is_err());
    assert!(cc_switch_file_path(&fixture.0, "nested/config.json").is_err());
}

#[cfg(windows)]
#[test]
fn explicit_cli_with_spaces_and_chinese_path_still_runs() {
    let fixture = Fixture::new();
    let folder = fixture.0.join("CLI 工具");
    fs::create_dir_all(&folder).unwrap();
    let script = folder.join("probe.cmd");
    fs::write(
        &script,
        "@echo off\r\necho fixture-version\r\nexit /b 0\r\n",
    )
    .unwrap();
    let result = command_summary_with_prefix(
        &(script.to_string_lossy().into_owned(), vec![]),
        &["--version"],
    );
    assert_eq!(result["ok"], true, "{result}");
    assert!(result["message"]
        .as_str()
        .unwrap()
        .contains("fixture-version"));
}

#[cfg(windows)]
#[test]
fn config_symlink_outside_root_is_rejected() {
    let fixture = Fixture::new();
    let root = fixture.0.join("root");
    fs::create_dir_all(&root).unwrap();
    let outside = fixture.0.join("outside.json");
    fs::write(&outside, "outside-fixture").unwrap();
    match std::os::windows::fs::symlink_file(&outside, root.join("config.json")) {
        Ok(()) => assert!(cc_switch_file_path(&root, "config.json").is_err()),
        Err(error) if error.raw_os_error() == Some(1314) => {
            assert!(
                std::env::var("GITHUB_ACTIONS").ok().as_deref() != Some("true"),
                "CI 必须实际验证配置符号链接边界"
            );
            // 普通 Windows 用户可能没有建链接权限；CI 管理员环境必须另验证该分支。
            eprintln!("链接用例未执行：当前用户没有创建文件符号链接的权限");
        }
        Err(error) => panic!("cannot create controlled symlink: {error}"),
    }
}
