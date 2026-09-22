use std::process::Command;

pub fn grep(term: &str) -> Result<String, String> {
    let out = Command::new("rg").args(["-n", term]).output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(format!("rg failed: {:?}", out.status.code()));
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}
