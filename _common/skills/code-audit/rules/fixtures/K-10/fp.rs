use std::process::Command;

pub fn grep(term: &str) -> String {
    let out = Command::new("rg").args(["-n", term]).output().unwrap();
    String::from_utf8_lossy(&out.stdout).to_string()
}
