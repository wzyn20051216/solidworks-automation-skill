use std::path::PathBuf;
use std::process::Command;

fn prepare_release_resources() {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let root = manifest.ancestors().nth(3).expect("repository root");
    let python = std::env::var_os("PYTHON").unwrap_or_else(|| "python".into());
    let status = Command::new(python)
        .arg(root.join("scripts/sync_bundled_skill.py"))
        .current_dir(root)
        .status()
        .expect("Python 3.10+ is required to prepare the bundled skill");
    assert!(status.success(), "bundled skill synchronization failed");

    // 只监视源目录；资源复制策略由 Python 共用清单唯一维护。
    for source in [
        "README.md",
        "SKILL.md",
        "SUBSKILLS.md",
        "capabilities.yaml",
        "golden-workflows.yaml",
        "requirements.txt",
        "requirements-mesh.txt",
        "requirements-occt.txt",
        "requirements-pdf.txt",
        "agents",
        "dotnet",
        "examples",
        "mcp-server",
        "profiles/drc",
        "scripts",
        "references",
        "subskills",
        "apps/desktop",
    ] {
        println!("cargo:rerun-if-changed={}", root.join(source).display());
    }
}

fn main() {
    prepare_release_resources();
    tauri_build::build()
}
