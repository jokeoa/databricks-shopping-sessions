pub mod campaign;
pub mod config;
pub mod csv;
pub mod input;
pub mod key;
pub mod links;
pub mod output;
pub mod person;
pub mod price;
pub mod record;
pub mod refdata;
pub mod simple;
pub mod ts;
use std::fmt;

pub type Map<K, V> = std::collections::HashMap<K, V, foldhash::fast::RandomState>;
pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug)]
pub struct Error(pub u8, pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.1)
    }
}
impl std::error::Error for Error {}
pub fn mutation(id: &str) -> bool {
    #[cfg(feature = "mutate")]
    {
        static ACTIVE: std::sync::OnceLock<String> = std::sync::OnceLock::new();
        ACTIVE.get_or_init(|| std::env::var("SS_MUTATION").unwrap_or_default()) == id
    }
    #[cfg(not(feature = "mutate"))]
    {
        let _ = id;
        false
    }
}
#[cfg(feature = "diag")]
pub mod diag;
pub mod fast;

pub fn run(config: &config::Config) -> Result<()> {
    let start = std::time::Instant::now();
    #[cfg(feature = "diag")]
    diag::init(&config.data)?;
    let files = input::Files::new(&config.data)?;
    let sizes = files.bytes()?;
    let r = refdata::Refs::load(&config.data)?;
    eprintln!(
        "{}",
        serde_json::json!({"build":env!("SS_BUILD_ID"),"mode":config.mode,"data":config.data,"output":config.out,"scratch":config.scratch,"files":[files.events.len(),files.clicks.len(),files.links.len()],"bytes":sizes,"window":[r.first,r.end],"threads":config.threads,"chunk_bytes":config.chunk,"event_buckets":config.event_buckets,"person_buckets":config.person_buckets,"budget_bytes":config.budget})
    );
    let (batches, counters) = if config.mode == "simple" {
        simple::run(&files, &links::load(&files.links)?, &r)?
    } else {
        fast::run(config, &files, &r)?
    };
    let before = std::time::Instant::now();
    output::publish(&config.out, batches, &r)?;
    #[cfg(feature = "diag")]
    diag::finish()?;
    eprintln!("{}", counters.json());
    eprintln!(
        "{}",
        serde_json::json!({"write_s":before.elapsed().as_secs_f64(),"elapsed_s":start.elapsed().as_secs_f64(),"rss_peak_bytes":rss_bytes()})
    );
    Ok(())
}
fn rss_bytes() -> Option<u64> {
    let mut usage = std::mem::MaybeUninit::uninit();
    // getrusage initializes the structure only on success.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return None;
    }
    let value = unsafe { usage.assume_init() }.ru_maxrss as u64;
    Some(if cfg!(target_os = "macos") {
        value
    } else {
        value * 1024
    })
}
