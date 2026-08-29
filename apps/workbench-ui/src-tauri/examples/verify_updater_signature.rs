//! @brief 使用客户端内置公钥验证 Windows 更新安装包签名。

use minisign_verify::{PublicKey, Signature};
use std::{env, fs, path::Path};

fn main() -> Result<(), String> {
    let arguments: Vec<String> = env::args().collect();
    if arguments.len() != 4 {
        return Err(
            "用法: verify_updater_signature <public-key-file> <artifact> <signature>".into(),
        );
    }

    let public_key_path = Path::new(&arguments[1]);
    let artifact_path = Path::new(&arguments[2]);
    let signature_path = Path::new(&arguments[3]);
    let public_key = PublicKey::from_file(public_key_path).map_err(|error| error.to_string())?;
    let signature = Signature::from_file(signature_path).map_err(|error| error.to_string())?;
    let artifact = fs::read(artifact_path).map_err(|error| error.to_string())?;
    public_key
        .verify(&artifact, &signature, false)
        .map_err(|error| error.to_string())?;
    println!("Updater signature verified: {}", artifact_path.display());
    Ok(())
}
