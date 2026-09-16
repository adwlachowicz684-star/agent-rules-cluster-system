use std::process::Command;

pub fn run_script(script: &str) -> String {
    let out = Command::new("cmd").arg(format!("/c {}", script)).output().unwrap();
    String::from_utf8_lossy(&out.stdout).to_string()
}
