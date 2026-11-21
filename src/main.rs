use shopping_sessions::{config::Config, run};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    match Config::load(&args, "fast").and_then(|cfg| run(&cfg)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(e.0)
        }
    }
}
