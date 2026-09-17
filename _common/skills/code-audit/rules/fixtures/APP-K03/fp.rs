use std::fs;
use std::path::Path;

pub fn delete_path(p: &Path, root: &Path) -> std::io::Result<()> {
    let canon = fs::canonicalize(p)?;
    if !canon.starts_with(fs::canonicalize(root)?) {
        return Err(std::io::Error::other("outside root"));
    }
    fs::remove_file(&canon)
}
