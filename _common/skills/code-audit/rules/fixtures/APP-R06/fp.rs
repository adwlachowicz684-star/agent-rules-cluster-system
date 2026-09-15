use std::process::Command;

pub fn run() {
    Command::new("/usr/bin/ls").arg("-l").spawn().unwrap();
}
