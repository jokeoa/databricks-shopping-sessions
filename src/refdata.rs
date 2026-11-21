use crate::{Error, Map, Result, csv::split_line, input, ts};
use std::path::Path;
pub struct Refs {
    pub first: i64,
    pub end: i64,
    pub products: Map<Vec<u8>, usize>,
    pub cats: Vec<Vec<u8>>,
    pub unknown: usize,
    pub campaigns: Map<Vec<u8>, usize>,
    pub channels: Vec<(Vec<u8>, Vec<u8>)>,
    pub organic: usize,
}
fn pairs(path: &Path) -> Result<Vec<(Vec<u8>, Vec<u8>)>> {
    let data = input::read(path)?;
    let mut output = Vec::new();
    let mut error = None;
    input::lines(&data, 0, data.len(), |offset, line| {
        match split_line::<2>(line) {
            Ok([id, value]) => output.push((id.to_vec(), value.to_vec())),
            Err(reason) => {
                error = Some(input::problem(
                    path,
                    format!("line at {offset}: {reason:?}"),
                ))
            }
        }
    });
    match error {
        Some(e) => Err(e),
        None => Ok(output),
    }
}
impl Refs {
    pub fn load(dir: &Path) -> Result<Self> {
        let path = dir.join("manifest.json");
        let json: serde_json::Value =
            serde_json::from_slice(&input::read(&path)?).map_err(|e| input::problem(&path, e))?;
        let bound = |k: &str| {
            json[k]
                .as_str()
                .and_then(|s| ts::f1(s.as_bytes()))
                .ok_or_else(|| input::problem(&path, k))
        };
        let (first, end) = (bound("window_start")?, bound("window_end")?);
        if first >= end {
            return Err(Error(3, "empty manifest window".into()));
        }
        let product_pairs = pairs(&dir.join("products.csv"))?;
        let mut cats: Vec<_> = product_pairs.iter().map(|(_, v)| v.clone()).collect();
        cats.push(b"unknown".to_vec());
        cats.sort_unstable();
        cats.dedup();
        let ranks: Map<_, _> = cats
            .iter()
            .enumerate()
            .map(|(i, cat)| (cat.as_slice(), i))
            .collect();
        let unknown = ranks[&b"unknown"[..]];
        let products = product_pairs
            .into_iter()
            .map(|(p, c)| (p, ranks[c.as_slice()]))
            .collect();
        let mut channels = pairs(&dir.join("campaigns.csv"))?;
        let campaigns = channels
            .iter()
            .enumerate()
            .map(|(i, (k, _))| (k.clone(), i))
            .collect();
        let organic = channels.len();
        channels.push((b"organic".to_vec(), b"organic".to_vec()));
        Ok(Self {
            first,
            end,
            products,
            cats,
            unknown,
            campaigns,
            channels,
            organic,
        })
    }
}
