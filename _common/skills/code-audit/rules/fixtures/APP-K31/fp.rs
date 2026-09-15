use std::process::Command;

pub fn run() -> Result<String, String> {
    let out = Command::new("git").arg("status").output().unwrap();
    if !out.status.success() {
        return Err(format!("exit {:?}", out.status.code()));
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}
