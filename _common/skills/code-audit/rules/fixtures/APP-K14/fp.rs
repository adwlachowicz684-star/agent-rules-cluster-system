use std::path::Path;

pub fn has_tool(name: &str) -> bool {
    std::env::split_paths(&std::env::var("PATH").unwrap_or_default())
        .any(|d| d.join(name).exists())
}
