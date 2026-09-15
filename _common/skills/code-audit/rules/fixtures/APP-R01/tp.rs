use std::path::Path;

const MAX: usize = 8192;

pub fn read_preview(p: &Path) -> std::io::Result<Vec<u8>> {
    let raw = std::fs::read(p)?;
    let n = raw.len().min(MAX);
    Ok(raw[..n].to_vec())
}
