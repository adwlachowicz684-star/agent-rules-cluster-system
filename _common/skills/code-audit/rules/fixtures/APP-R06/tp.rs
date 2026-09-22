use std::process::Command;

pub fn run(name: &str) {
    Command::new(name).arg("-l").spawn().unwrap();
}
