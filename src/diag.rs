//! Optional row-level evidence. Release builds omit this module and all call sites.
use crate::{
    Error, Result,
    csv::split_line,
    key::IdKey,
    record::{Candidate, Click, Fate},
    refdata::Refs,
    ts,
};
use std::{
    collections::HashSet,
    fs::{self, File},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    sync::{Mutex, OnceLock},
};

const FILES: [&str; 7] = ["B1", "B2", "B3", "B4", "B5", "B6-user", "B6-campaign"];
struct Sink {
    data: PathBuf,
    writers: Vec<Mutex<BufWriter<File>>>,
    failure: Mutex<Option<String>>,
    clicks: Mutex<HashSet<IdKey>>,
}
static SINK: OnceLock<Sink> = OnceLock::new();
pub fn init(data: &Path) -> Result<()> {
    let Some(dir) = std::env::var_os("SS_DUMP_DIR") else {
        return Ok(());
    };
    let dir = Path::new(&dir);
    fs::create_dir_all(dir).map_err(|e| Error(4, format!("{}: {e}", dir.display())))?;
    let writers = FILES
        .iter()
        .map(|n| {
            File::create_new(dir.join(format!("{n}.tsv")))
                .map(|f| Mutex::new(BufWriter::new(f)))
                .map_err(|e| Error(4, format!("{n}: {e}")))
        })
        .collect::<Result<_>>()?;
    SINK.set(Sink {
        data: data.into(),
        writers,
        failure: Mutex::default(),
        clicks: Mutex::default(),
    })
    .map_err(|_| Error(2, "diagnostics already initialized".into()))
}
fn emit(index: usize, fields: impl FnOnce(&Sink) -> Vec<Vec<u8>>) {
    let Some(s) = SINK.get() else { return };
    let mut line = Vec::new();
    for (i, field) in fields(s).into_iter().enumerate() {
        if i > 0 {
            line.push(b'\t');
        }
        for c in field {
            if (33..=126).contains(&c) && c != b'\\' {
                line.push(c);
            } else {
                write!(line, "\\x{c:02x}").unwrap();
            }
        }
    }
    line.push(b'\n');
    if let Err(e) = s.writers[index].lock().unwrap().write_all(&line) {
        *s.failure.lock().unwrap() = Some(e.to_string());
    }
}
pub fn finish() -> Result<()> {
    if let Some(s) = SINK.get() {
        for w in &s.writers {
            w.lock()
                .unwrap()
                .flush()
                .map_err(|e| Error(4, e.to_string()))?;
        }
        if let Some(e) = s.failure.lock().unwrap().take() {
            return Err(Error(4, e));
        }
    }
    Ok(())
}
fn num(n: impl ToString) -> Vec<u8> {
    n.to_string().into_bytes()
}
pub fn raw<const N: usize>(path: &Path, offset: usize, line: &[u8], fate: &str) {
    emit(0, |s| {
        let mut row = vec![
            path.strip_prefix(&s.data)
                .unwrap_or(path)
                .as_os_str()
                .as_encoded_bytes()
                .to_vec(),
            num(offset),
            fate.as_bytes().to_vec(),
        ];
        if let Ok(f) = split_line::<N>(line) {
            if N != 2 {
                row.push(
                    ts::parse(f[if N == 7 { 2 } else { 3 }])
                        .ok()
                        .map(num)
                        .unwrap_or_default(),
                );
            }
            row.extend(f.iter().map(|s| s.to_vec()));
        }
        row
    })
}
pub fn link(key: IdKey, name: IdKey) {
    emit(1, |_| vec![key.bytes(), name.bytes()]);
}
pub fn winner(id: IdKey, c: &Candidate, r: &Refs) {
    emit(2, |_| {
        vec![
            id.bytes(),
            num(c.ingest),
            c.fate.label().as_bytes().to_vec(),
            c.user.bytes(),
            if c.fate == Fate::Valid {
                num(c.event.ts)
            } else {
                vec![]
            },
            num(c.event.cents),
            if c.event.cents > 0 {
                r.cats[c.event.category].clone()
            } else {
                vec![]
            },
        ]
    });
}
pub fn click(name: IdKey, c: &Click, r: &Refs) {
    if SINK
        .get()
        .is_some_and(|s| s.clicks.lock().unwrap().insert(c.id))
    {
        emit(3, |_| {
            vec![
                c.id.bytes(),
                name.bytes(),
                num(c.ts),
                r.channels[c.campaign].0.clone(),
            ]
        });
    }
}
pub struct Session {
    pub name: IdKey,
    pub start: i64,
    pub day: i32,
    pub events: usize,
    pub cents: i64,
    pub winner: usize,
}
pub fn session(row: Session, active: impl Iterator<Item = usize>, r: &Refs) {
    emit(4, |_| {
        let mut a: Vec<_> = active.map(|i| r.channels[i].0.clone()).collect();
        a.sort_unstable();
        let mut v = vec![
            row.name.bytes(),
            num(row.start),
            num(row.day),
            num(row.events),
            num(row.cents),
            num(i64::from(row.cents > 0)),
            r.channels[row.winner].0.clone(),
        ];
        v.extend(a);
        v
    })
}
pub fn user(u: &crate::person::UserDay, r: &Refs) {
    emit(5, |_| {
        vec![
            u.person.bytes(),
            num(u.day),
            num(u.sessions),
            num(u.events),
            num(u.cents),
            u.top.map(|k| r.cats[k].clone()).unwrap_or_default(),
        ]
    });
}
pub fn campaign(c: usize, day: i32, v: &[i64; 4], r: &Refs) {
    emit(6, |_| {
        let mut row = vec![r.channels[c].0.clone(), num(day), r.channels[c].1.clone()];
        row.extend(v.iter().map(num));
        row
    })
}

pub fn command(args: &[std::ffi::OsString]) -> Option<Result<()>> {
    let sub = args.first()?.to_str()?;
    let result = match sub {
        "leaf" => leaf(),
        "scan" => scan(&args[1..]),
        "explain" => explain(&args[1..]),
        _ => return None,
    };
    Some(result)
}
fn unhex(v: &str) -> Option<Vec<u8>> {
    if !v.is_ascii() || !v.len().is_multiple_of(2) {
        return None;
    }
    (0..v.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&v[i..i + 2], 16).ok())
        .collect()
}
fn hex(v: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::new();
    for b in v {
        write!(s, "{b:02x}").unwrap();
    }
    s
}
fn leaf() -> Result<()> {
    use std::io::BufRead;
    for line in std::io::stdin().lock().lines() {
        let request: serde_json::Value =
            serde_json::from_str(&line.map_err(|e| Error(3, e.to_string()))?)
                .map_err(|e| Error(2, e.to_string()))?;
        let bytes = |key: &str| {
            request[key]
                .as_str()
                .and_then(unhex)
                .ok_or_else(|| Error(2, format!("invalid hex field {key}")))
        };
        let v = bytes("hex")?;
        let value = match request["op"].as_str() {
            Some("price") => serde_json::json!(crate::price::parse(&v)),
            Some("time") => match ts::parse(&v) {
                Ok(n) => serde_json::json!(n),
                Err(ts::Bad::Format) => "format".into(),
                Err(ts::Bad::Range) => "range".into(),
            },
            Some("key") => serde_json::json!(match IdKey::encode(&v)
                .cmp_bytes(&IdKey::encode(&bytes("other")?))
            {
                std::cmp::Ordering::Less => -1,
                std::cmp::Ordering::Equal => 0,
                std::cmp::Ordering::Greater => 1,
            }),
            Some("csv") => {
                fn fields<const N: usize>(v: &[u8]) -> serde_json::Value {
                    match split_line::<N>(v) {
                        Ok(f) => serde_json::json!(f.into_iter().map(hex).collect::<Vec<_>>()),
                        Err(e) => e.label().into(),
                    }
                }
                match request["width"].as_u64() {
                    Some(2) => fields::<2>(&v),
                    Some(4) => fields::<4>(&v),
                    Some(7) => fields::<7>(&v),
                    _ => return Err(Error(2, "invalid CSV width".into())),
                }
            }
            _ => return Err(Error(2, "invalid leaf operation".into())),
        };
        println!("{value}");
    }
    Ok(())
}
fn scan(args: &[std::ffi::OsString]) -> Result<()> {
    let [flag, method] = args else {
        return Err(Error(2, "scan --io mmap|pread".into()));
    };
    if flag != "--io" || (method != "mmap" && method != "pread") {
        return Err(Error(2, "scan --io mmap|pread".into()));
    }
    let c = crate::config::Config::load(&[], "fast")?;
    let files = crate::input::Files::new(&c.data)?;
    let mut hash = 0xcbf29ce484222325u64;
    let mut rows = 0u64;
    let mut valid = 0u64;
    for (width, paths) in [(7, files.events), (4, files.clicks), (2, files.links)] {
        for path in paths {
            let mut visit = |off: usize, line: &[u8]| {
                rows += 1;
                valid += u64::from(match width {
                    7 => split_line::<7>(line).is_ok(),
                    4 => split_line::<4>(line).is_ok(),
                    _ => split_line::<2>(line).is_ok(),
                });
                for b in off.to_le_bytes().iter().chain(line) {
                    hash = (hash ^ u64::from(*b)).wrapping_mul(0x100000001b3);
                }
            };
            if method == "mmap" {
                let src = crate::fast::Source::open(&path)?;
                let data = src.data();
                for i in (0..data.len()).step_by(c.chunk) {
                    crate::input::lines(data, i, i.saturating_add(c.chunk), &mut visit);
                }
            } else {
                pread(&path, c.chunk, &mut visit)?;
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({"rows":rows,"valid":valid,"checksum":format!("{hash:016x}")})
    );
    Ok(())
}
fn pread(path: &Path, chunk: usize, mut visit: impl FnMut(usize, &[u8])) -> Result<()> {
    use std::os::unix::fs::FileExt;
    let f = File::open(path).map_err(|e| crate::input::problem(path, e))?;
    let mut block = vec![0; chunk.min(1 << 20)];
    let mut tail = Vec::new();
    let mut off = 0;
    let mut row_start = 0;
    loop {
        let n = f
            .read_at(&mut block, off as u64)
            .map_err(|e| crate::input::problem(path, e))?;
        if n == 0 {
            break;
        }
        let mut start = 0;
        for i in memchr::memchr_iter(b'\n', &block[..n]) {
            if row_start != 0 {
                if tail.is_empty() {
                    visit(row_start, &block[start..i]);
                } else {
                    tail.extend_from_slice(&block[start..i]);
                    visit(row_start, &tail);
                }
            }
            tail.clear();
            start = i + 1;
            row_start = off + start;
        }
        tail.extend_from_slice(&block[start..n]);
        off += n;
    }
    if !tail.is_empty() && row_start != 0 {
        visit(row_start, &tail);
    }
    Ok(())
}
fn escape(field: &[u8]) -> String {
    use std::fmt::Write;
    let mut out = String::new();
    for &c in field {
        if (33..=126).contains(&c) && c != b'\\' {
            out.push(c as char);
        } else {
            write!(out, "\\x{c:02x}").unwrap();
        }
    }
    out
}
fn explain(args: &[std::ffi::OsString]) -> Result<()> {
    use std::io::{BufRead, BufReader};
    let [who] = args else {
        return Err(Error(2, "explain USER_ID".into()));
    };
    let dir = PathBuf::from(
        std::env::var_os("SS_DUMP_DIR")
            .ok_or_else(|| Error(2, "set SS_DUMP_DIR to a completed diagnostic run".into()))?,
    );
    let id = escape(who.as_encoded_bytes());
    let mut name = id.clone();
    for (file, column) in [("B2", 0), ("B4", 1), ("B5", 0), ("B6-user", 0)] {
        let p = dir.join(format!("{file}.tsv"));
        let input = File::open(&p).map_err(|e| crate::input::problem(&p, e))?;
        for row in BufReader::new(input).lines() {
            let row = row.map_err(|e| crate::input::problem(&p, e))?;
            if row.split('\t').nth(column) == Some(&name) {
                println!("{file}\t{row}");
                if file == "B2" {
                    name = row.split('\t').nth(1).unwrap_or(&id).to_owned();
                    break;
                }
            }
        }
    }
    Ok(())
}
