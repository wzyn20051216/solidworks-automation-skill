//! @brief Dört Agent, yapılandırma okuma ve bağlantı sınırları için regresyon testleri.
use super::{
    cc_switch_file_path, command_summary_with_prefix, read_cc_switch_file, supported_program_name,
};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

struct Fixture(PathBuf);
static FIXTURE_SEQUENCE: AtomicU64 = AtomicU64::new(0);
impl Fixture {
    fn new() -> Self {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        Self::with_timestamp(stamp)
    }

    fn with_timestamp(stamp: u128) -> Self {
        // Saat çözünürlüğü paralel testler için benzersizliği garanti etmez; bağımsız sıra numarası ve atomik oluşturma dizinlerin yeniden kullanılmasını/yanlışlıkla silinmesini önler.
        let sequence = FIXTURE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "cadstudio-boundary-{}-{stamp}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

#[test]
fn fixtures_with_identical_timestamps_remain_isolated() {
    let (first, second) = std::thread::scope(|scope| {
        let first = scope.spawn(|| Fixture::with_timestamp(0));
        let second = scope.spawn(|| Fixture::with_timestamp(0));
        (first.join().unwrap(), second.join().unwrap())
    });
    assert_ne!(first.0, second.0);
    let preserved = second.0.join("must-survive.txt");
    fs::write(&preserved, "independent fixture").unwrap();
    drop(first);
    assert_eq!(
        fs::read_to_string(preserved).unwrap(),
        "independent fixture"
    );
}
impl Drop for Fixture {
    fn drop(&mut self) {
        // Özyinelemeli temizlikten önce hedefin hâlâ bu turda adlandırılan geçici kök içinde olduğunu doğrula.
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
    let folder = fixture.0.join("CLI Araçları");
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
                "CI yapılandırma sembolik bağlantı sınırını gerçekten doğrulamalıdır"
            );
            // Normal Windows kullanıcılarının bağlantı oluşturma izni olmayabilir; CI yönetici ortamı bu dalı ayrıca doğrulamalıdır.
            eprintln!("Bağlantı testi çalıştırılmadı: geçerli kullanıcının dosya sembolik bağlantısı oluşturma izni yok");
        }
        Err(error) => panic!("cannot create controlled symlink: {error}"),
    }
}
