use std::process::Command;

pub fn has_tool(name: &str) -> bool {
    Command::new("where").arg(name).output().map(|o| o.status.success()).unwrap_or(false)
}
