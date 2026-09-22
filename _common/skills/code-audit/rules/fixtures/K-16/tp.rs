use std::net::TcpListener;

pub fn serve() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:9000")?;
    for stream in listener.incoming() {
        std::io::copy(&mut stream?, &mut std::io::sink())?;
    }
    Ok(())
}
