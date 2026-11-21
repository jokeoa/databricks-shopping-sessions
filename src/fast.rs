use crate::{
    Error, Map, Result,
    config::Config,
    input::{self, Files},
    key::IdKey,
    links,
    person::{self, Batch, Person},
    record::{self, Candidate, Click, Counters, Event, Fate},
    refdata::Refs,
};
use memmap2::Mmap;
use std::{
    fs::File,
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::Instant,
};

pub struct Source {
    pub path: PathBuf,
    map: Option<Mmap>,
}
impl Source {
    pub fn open(path: &Path) -> Result<Self> {
        let file = File::open(path).map_err(|e| input::problem(path, e))?;
        let size = file.metadata().map_err(|e| input::problem(path, e))?.len();
        // The scorer mounts an immutable input directory throughout execution.
        let map = if size == 0 {
            None
        } else {
            Some(unsafe { Mmap::map(&file) }.map_err(|e| input::problem(path, e))?)
        };
        Ok(Self {
            path: path.to_owned(),
            map,
        })
    }
    pub fn data(&self) -> &[u8] {
        self.map.as_deref().unwrap_or_default()
    }
}
pub(crate) fn workers<J: Send, S: Send>(
    jobs: Vec<J>,
    threads: usize,
    init: impl Fn() -> S + Sync,
    action: impl Fn(&mut S, J) + Sync,
) -> Result<Vec<S>> {
    let threads = threads.min(jobs.len()).max(1);
    let queue = Mutex::new(jobs.into_iter());
    thread::scope(|scope| {
        let mut handles = Vec::new();
        for _ in 0..threads {
            handles.push(
                thread::Builder::new()
                    .spawn_scoped(scope, || {
                        let mut state = init();
                        loop {
                            let job = queue.lock().unwrap().next();
                            match job {
                                Some(j) => action(&mut state, j),
                                None => break,
                            }
                        }
                        state
                    })
                    .map_err(|e| Error(3, format!("start worker: {e}")))?,
            );
        }
        handles
            .into_iter()
            .map(|h| h.join().map_err(|_| Error(3, "worker panicked".into())))
            .collect()
    })
}
fn empty<T>(n: usize) -> Vec<Vec<T>> {
    (0..n).map(|_| Vec::new()).collect()
}
type Raw = (IdKey, Candidate);
type NamedClick = (IdKey, Click);
type NamedEvent = (IdKey, Event);
struct Parsed {
    buckets: Vec<Vec<Raw>>,
    clicks: Vec<NamedClick>,
    counts: Counters,
}
struct Partitioned {
    events: Vec<Vec<NamedEvent>>,
    clicks: Vec<Vec<NamedClick>>,
    counts: Counters,
}
enum Job {
    Events(Vec<Vec<Raw>>),
    Clicks(Vec<NamedClick>),
}
#[derive(Default)]
struct Bucket {
    events: Vec<Vec<NamedEvent>>,
    clicks: Vec<Vec<NamedClick>>,
    size: usize,
}

pub fn run(config: &Config, files: &Files, r: &Refs) -> Result<(Vec<Batch>, Counters)> {
    let started = Instant::now();
    let t = config.threads;
    let (parsed, names) = thread::scope(|scope| -> Result<_> {
        let graph = scope.spawn(|| links::load(&files.links));
        let mut maps = Vec::new();
        let mut chunks = Vec::new();
        for (is_event, paths) in [(true, &files.events), (false, &files.clicks)] {
            for path in paths {
                let source = Source::open(path)?;
                let len = source.data().len();
                for start in (0..len).step_by(config.chunk) {
                    chunks.push((
                        is_event,
                        maps.len(),
                        start,
                        start.saturating_add(config.chunk).min(len),
                    ));
                }
                maps.push(source);
            }
        }
        chunks.sort_unstable_by_key(|&(_, _, s, e)| std::cmp::Reverse(e - s));
        let output = workers(
            chunks,
            t,
            || Parsed {
                buckets: empty(config.event_buckets),
                clicks: vec![],
                counts: Counters::default(),
            },
            |state, (event, i, start, end)| {
                input::lines(maps[i].data(), start, end, |_, line| {
                    if event {
                        match record::event(line, r) {
                            Ok((key, c)) => {
                                state.counts.events[c.fate as usize] += 1;
                                state.buckets[key.bucket(config.event_buckets)].push((key, c));
                            }
                            Err(f) => state.counts.events[f as usize] += 1,
                        }
                    } else {
                        match record::click(line, r) {
                            Ok(c) => {
                                state.counts.clicks[0] += 1;
                                state.clicks.push(c);
                            }
                            Err(f) => state.counts.clicks[f as usize] += 1,
                        }
                    }
                })
            },
        )?;
        Ok((
            output,
            graph
                .join()
                .map_err(|_| Error(3, "link worker panicked".into()))??,
        ))
    })?;
    let parse_secs = started.elapsed().as_secs_f64();
    let mut counts = Counters::default();
    let mut event_jobs = empty(config.event_buckets);
    let mut jobs = Vec::new();
    for p in parsed {
        counts.add(&p.counts);
        for (dst, src) in event_jobs.iter_mut().zip(p.buckets) {
            if !src.is_empty() {
                dst.push(src);
            }
        }
        if !p.clicks.is_empty() {
            jobs.push(Job::Clicks(p.clicks));
        }
    }
    jobs.extend(
        event_jobs
            .into_iter()
            .filter(|v| !v.is_empty())
            .map(Job::Events),
    );
    let parts = workers(
        jobs,
        t,
        || Partitioned {
            events: empty(config.person_buckets),
            clicks: empty(config.person_buckets),
            counts: Counters::default(),
        },
        |state, job| match job {
            Job::Clicks(clicks) => {
                for (u, c) in clicks {
                    let name = *names.get(&u).unwrap_or(&u);
                    state.clicks[name.bucket(config.person_buckets)].push((name, c));
                }
            }
            Job::Events(vectors) => {
                let mut raw = Vec::with_capacity(vectors.iter().map(Vec::len).sum());
                for mut v in vectors {
                    raw.append(&mut v);
                }
                raw.sort_unstable_by(|a, b| {
                    a.0.cmp_bytes(&b.0)
                        .then_with(|| a.1.ingest.cmp(&b.1.ingest))
                });
                for group in raw.chunk_by(|a, b| a.0 == b.0) {
                    let c = group[0].1;
                    state.counts.winners[c.fate as usize] += 1;
                    state.counts.equal_diff += group[1..]
                        .iter()
                        .filter(|(_, o)| o.ingest == c.ingest && *o != c)
                        .count() as u64;
                    if c.fate == Fate::Valid {
                        let name = *names.get(&c.user).unwrap_or(&c.user);
                        state.events[name.bucket(config.person_buckets)].push((name, c.event));
                    }
                }
            }
        },
    )?;
    drop(names);
    let bucket_secs = started.elapsed().as_secs_f64() - parse_secs;
    let mut buckets: Vec<Bucket> = (0..config.person_buckets)
        .map(|_| Bucket::default())
        .collect();
    for p in parts {
        counts.add(&p.counts);
        for ((dest, e), c) in buckets.iter_mut().zip(p.events).zip(p.clicks) {
            dest.size += e.len() + c.len();
            if !e.is_empty() {
                dest.events.push(e);
            }
            if !c.is_empty() {
                dest.clicks.push(c);
            }
        }
    }
    buckets.retain(|b| !b.events.is_empty());
    buckets.sort_unstable_by_key(|b| std::cmp::Reverse(b.size));
    let batches = workers(buckets, t, Batch::default, |state, shard| {
        let mut people: Map<IdKey, Person> = Map::default();
        for (name, e) in shard.events.into_iter().flatten() {
            people.entry(name).or_default().events.push(e);
        }
        for (name, c) in shard.clicks.into_iter().flatten() {
            if let Some(p) = people.get_mut(&name) {
                p.clicks.push(c);
            }
        }
        for (name, mut p) in people {
            person::process(name, &mut p.events, &mut p.clicks, r, state);
        }
    })?;
    eprintln!(
        "{}",
        serde_json::json!({"parse_links_s":parse_secs,"partition_s":bucket_secs,"session_s":started.elapsed().as_secs_f64()-bucket_secs-parse_secs})
    );
    Ok((batches, counts))
}
