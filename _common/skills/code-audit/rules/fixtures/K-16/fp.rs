use std::net::TcpListener;
use std::time::Duration;

pub fn serve() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:9000")?;
    for stream in listener.incoming() {
        let mut s = stream?;
        s.set_read_timeout(Some(Duration::from_secs(5)))?;
        s.set_write_timeout(Some(Duration::from_secs(5)))?;
        std::io::copy(&mut s, &mut std::io::sink())?;
    }
    Ok(())
}
