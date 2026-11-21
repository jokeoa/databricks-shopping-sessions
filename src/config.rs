use crate::{Error, Result};
use std::{env, path::PathBuf};

pub struct Config {
    pub data: PathBuf,
    pub out: PathBuf,
    pub scratch: PathBuf,
    pub mode: String,
    pub threads: usize,
    pub chunk: usize,
    pub event_buckets: usize,
    pub person_buckets: usize,
    pub budget: u64,
}
fn number(name: &str, default: usize) -> Result<usize> {
    match env::var(name) {
        Ok(v) => v
            .parse::<usize>()
            .ok()
            .filter(|n| *n > 0)
            .ok_or_else(|| Error(2, format!("invalid {name}={v}"))),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(e) => Err(Error(2, format!("{name}: {e}"))),
    }
}
impl Config {
    pub fn load(args: &[std::ffi::OsString], default_mode: &str) -> Result<Self> {
        let (data, out) = match args {
            [] => (
                env::var_os("DATA_DIR").unwrap_or("/data".into()),
                env::var_os("OUTPUT_DIR").unwrap_or("/output".into()),
            ),
            [data, out] => (data.clone(), out.clone()),
            _ => return Err(Error(2, "usage: shopping-sessions [DATA OUTPUT]".into())),
        };
        let mode = env::var("SS_MODE").unwrap_or_else(|_| default_mode.into());
        if !matches!(mode.as_str(), "simple" | "fast") {
            return Err(Error(2, format!("invalid SS_MODE={mode}")));
        }
        let host_budget = std::fs::read_to_string("/sys/fs/cgroup/memory.max")
            .ok()
            .and_then(|v| v.trim().parse::<u64>().ok())
            .unwrap_or(u64::MAX);
        let budget = (number("MEM_GB", 24)? as u64)
            .saturating_mul(1_000_000_000)
            .min(12_000_000_000)
            .min(host_budget);
        let threads = number(
            "NCPU",
            std::thread::available_parallelism().map_or(1, usize::from),
        )?;
        let event_buckets = number("SS_EVENT_BUCKETS", 256)?;
        let person_buckets = number("SS_PERSON_BUCKETS", 512)?;
        if threads > 4096
            || event_buckets > 65536
            || person_buckets > 65536
            || threads.saturating_mul(event_buckets.max(person_buckets)) > 4_000_000
        {
            return Err(Error(2, "worker or bucket count exceeds capacity".into()));
        }
        Ok(Self {
            data: data.into(),
            out: out.into(),
            scratch: env::var_os("SCRATCH_DIR")
                .unwrap_or("/scratch".into())
                .into(),
            mode,
            threads,
            chunk: number("SS_CHUNK_BYTES", 4 << 20)?,
            event_buckets,
            person_buckets,
            budget,
        })
    }
}
