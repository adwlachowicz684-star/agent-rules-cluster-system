use std::process::Command;

pub fn run_git(args: &[&str]) -> String {
    let out = Command::new("git").args(args).output().unwrap();
    String::from_utf8_lossy(&out.stdout).to_string()
}
