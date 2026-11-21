use shopping_sessions::{config::Config, run};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    #[cfg(feature = "diag")]
    if let Some(result) = shopping_sessions::diag::command(&args) {
        return status(result);
    }
    status(Config::load(&args, "fast").and_then(|cfg| run(&cfg)))
}
fn status(result: shopping_sessions::Result<()>) -> ExitCode {
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(e.0)
        }
    }
}
