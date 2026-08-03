use std::fs;
use std::path::{Path, PathBuf};

const INCLUDED_EXTENSIONS: &[&str] = &[
    "config", "cs", "csproj", "js", "json", "md", "ps1", "py", "txt", "yaml", "yml",
];
const EXCLUDED_DIRECTORIES: &[&str] = &[".git", "__pycache__", "bin", "obj"];

fn copy_release_tree(source: &Path, destination: &Path) {
    if !source.exists() {
        return;
    }
    fs::create_dir_all(destination).expect("create release resource directory");
    for entry in fs::read_dir(source).expect("read release resource directory") {
        let entry = entry.expect("read release resource entry");
        let path = entry.path();
        let name = entry.file_name();
        if EXCLUDED_DIRECTORIES
            .iter()
            .any(|excluded| name == *excluded)
        {
            continue;
        }
        let target = destination.join(name);
        if path.is_dir() {
            copy_release_tree(&path, &target);
            continue;
        }
        let included = path
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|extension| {
                INCLUDED_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str())
            });
        if included {
            fs::copy(&path, &target).expect("copy release resource file");
        }
    }
}

fn prepare_release_resources() {
    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let root = manifest
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf();
    let staging = manifest.join("resources").join("skill");
    if staging.exists() {
        fs::remove_dir_all(&staging).expect("clear staged release resources");
    }
    fs::create_dir_all(&staging).expect("create staged release resources");

    for file in [
        "README.md",
        "SKILL.md",
        "SUBSKILLS.md",
        "capabilities.yaml",
        "golden-workflows.yaml",
        "requirements.txt",
        "requirements-mesh.txt",
        "requirements-occt.txt",
        "requirements-pdf.txt",
    ] {
        fs::copy(root.join(file), staging.join(file)).expect("copy root release resource");
        println!("cargo:rerun-if-changed={}", root.join(file).display());
    }
    for directory in [
        "agents",
        "examples",
        "mcp-server",
        "scripts",
        "references",
        "subskills",
    ] {
        copy_release_tree(&root.join(directory), &staging.join(directory));
        println!("cargo:rerun-if-changed={}", root.join(directory).display());
    }
    let desktop = root.join("apps").join("desktop");
    copy_release_tree(
        &desktop.join("cad_workbench"),
        &staging.join("apps").join("desktop").join("cad_workbench"),
    );
    fs::copy(
        desktop.join("__init__.py"),
        staging.join("apps").join("desktop").join("__init__.py"),
    )
    .expect("copy desktop package marker");
    println!("cargo:rerun-if-changed={}", desktop.display());
}

fn main() {
    prepare_release_resources();
    tauri_build::build()
}
