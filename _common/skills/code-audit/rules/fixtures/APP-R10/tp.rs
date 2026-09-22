use std::path::Path;

pub fn move_file(from: &Path, to: &Path) -> std::io::Result<()> {
    std::fs::rename(from, to)
}
