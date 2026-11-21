use crate::{Error, Result};
use std::{
    fs,
    path::{Path, PathBuf},
};

pub fn problem(path: &Path, e: impl std::fmt::Display) -> Error {
    Error(3, format!("{}: {e}", path.display()))
}
pub fn read(path: &Path) -> Result<Vec<u8>> {
    fs::read(path).map_err(|e| problem(path, e))
}
pub fn files(dir: &Path) -> Result<Vec<PathBuf>> {
    let mut result = Vec::new();
    for entry in fs::read_dir(dir).map_err(|e| problem(dir, e))? {
        let entry = entry.map_err(|e| problem(dir, e))?;
        let path = entry.path();
        if entry.file_type().map_err(|e| problem(&path, e))?.is_file()
            && path
                .file_name()
                .unwrap_or_default()
                .as_encoded_bytes()
                .ends_with(b".csv")
        {
            result.push(path);
        }
    }
    result.sort();
    Ok(result)
}
pub struct Files {
    pub events: Vec<PathBuf>,
    pub clicks: Vec<PathBuf>,
    pub links: Vec<PathBuf>,
}
impl Files {
    pub fn new(dir: &Path) -> Result<Self> {
        Ok(Self {
            events: files(&dir.join("events"))?,
            clicks: files(&dir.join("clicks"))?,
            links: files(&dir.join("links"))?,
        })
    }
    pub fn bytes(&self) -> Result<[u64; 3]> {
        let mut sizes = [0; 3];
        for (i, files) in [&self.events, &self.clicks, &self.links].iter().enumerate() {
            for p in *files {
                sizes[i] += fs::metadata(p).map_err(|e| problem(p, e))?.len();
            }
        }
        Ok(sizes)
    }
}
pub fn lines(data: &[u8], start: usize, end: usize, mut visit: impl FnMut(usize, &[u8])) {
    let end = end.min(data.len());
    if start >= end {
        return;
    }
    let mut at = start;
    if start > 0 && data[start - 1] != b'\n' {
        match memchr::memchr(b'\n', &data[start..end]) {
            Some(d) => at += d + 1,
            None => return,
        }
    }
    while at < end {
        let len = memchr::memchr(b'\n', &data[at..]).unwrap_or(data.len() - at);
        if at != 0 {
            visit(at, &data[at..at + len]);
        }
        at += len + 1;
    }
}
