use std::process::Command;

pub fn run() -> String {
    let out = Command::new("git").arg("status").output().unwrap();
    String::from_utf8_lossy(&out.stdout).to_string()
}
