use std::fs::File;
use std::io::Read;
use std::path::Path;

const MAX: u64 = 8192;

pub fn read_head(p: &Path) -> std::io::Result<Vec<u8>> {
    let c = p.canonicalize()?;
    if !c.starts_with(&allowed_root()) {
        return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied,
                                       "outside root"));
    }
    let mut f = File::open(c)?;
    let mut buf = Vec::new();
    f.take(MAX).read_to_end(&mut buf)?;
    Ok(buf)
}
