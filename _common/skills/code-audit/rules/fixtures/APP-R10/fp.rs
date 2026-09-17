use std::path::Path;

pub fn move_file(from: &Path, to: &Path) -> std::io::Result<()> {
    let c = from.canonicalize()?;
    if !c.starts_with(&allowed_root()) {
        return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied,
                                       "outside root"));
    }
    std::fs::copy(&c, to)?;
    std::fs::remove_file(&c)
}
