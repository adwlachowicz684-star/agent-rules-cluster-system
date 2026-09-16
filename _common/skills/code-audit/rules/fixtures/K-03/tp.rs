use std::fs;
use std::path::Path;

pub fn delete_path(p: &Path) -> std::io::Result<()> {
    let name = p.file_name().unwrap().to_string_lossy();
    if name.starts_with('.') {
        fs::remove_file(p)?;
    }
    Ok(())
}
