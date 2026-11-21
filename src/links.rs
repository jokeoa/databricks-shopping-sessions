use crate::{Map, Result, csv::split_line, input, key::IdKey};
use std::path::PathBuf;
pub type Names = Map<IdKey, IdKey>;
struct Graph {
    ids: Map<IdKey, usize>,
    parent: Vec<usize>,
    size: Vec<usize>,
    names: Vec<IdKey>,
}
impl Graph {
    fn id(&mut self, key: IdKey) -> usize {
        *self.ids.entry(key).or_insert_with(|| {
            let i = self.parent.len();
            self.parent.push(i);
            self.size.push(1);
            self.names.push(key);
            i
        })
    }
    fn root(&mut self, mut i: usize) -> usize {
        while self.parent[i] != i {
            let p = self.parent[i];
            self.parent[i] = self.parent[p];
            i = self.parent[i];
        }
        i
    }
    fn union(&mut self, a: IdKey, b: IdKey) {
        let ai = self.id(a);
        let bi = self.id(b);
        let mut a = self.root(ai);
        let mut b = self.root(bi);
        if a == b {
            return;
        }
        if self.size[a] < self.size[b] {
            std::mem::swap(&mut a, &mut b);
        }
        self.parent[b] = a;
        self.size[a] += self.size[b];
        if !crate::mutation("first_name") && self.names[b].cmp_bytes(&self.names[a]).is_lt() {
            self.names[a] = self.names[b];
        }
    }
}
pub fn load(files: &[PathBuf]) -> Result<Names> {
    let mut g = Graph {
        ids: Map::default(),
        parent: vec![],
        size: vec![],
        names: vec![],
    };
    for path in files {
        let bytes = input::read(path)?;
        input::lines(&bytes, 0, bytes.len(), |_offset, line| {
            #[cfg(feature = "diag")]
            {
                let fate = match split_line::<2>(line) {
                    Err(f) => f.label(),
                    Ok([a, b]) if a.is_empty() || b.is_empty() => "empty_person",
                    _ => "valid",
                };
                crate::diag::raw::<2>(path, _offset, line, fate);
            }
            if let Ok([a, b]) = split_line::<2>(line)
                && !a.is_empty()
                && !b.is_empty()
            {
                g.union(IdKey::encode(a), IdKey::encode(b));
            }
        });
    }
    let ids = std::mem::take(&mut g.ids);
    Ok(ids
        .into_iter()
        .map(|(k, i)| {
            let root = g.root(i);
            #[cfg(feature = "diag")]
            crate::diag::link(k, g.names[root]);
            (k, g.names[root])
        })
        .collect())
}
