use std::net::TcpListener;

pub fn serve() -> std::io::Result<TcpListener> {
    TcpListener::bind("0.0.0.0:9000")
}
