use crate::{Map, refdata::Refs, ts::DAY};
pub type Totals = [i64; 4];
pub enum CampaignDays {
    Dense {
        start: i32,
        days: usize,
        cells: Vec<Totals>,
    },
    Sparse(Map<(usize, i32), Totals>),
}
impl Default for CampaignDays {
    fn default() -> Self {
        Self::Sparse(Map::default())
    }
}
impl CampaignDays {
    pub fn new(r: &Refs, threads: usize, budget: u64) -> Self {
        let start = r.first.div_euclid(DAY) as i32;
        let days = ((r.end - 1).div_euclid(DAY) - i64::from(start) + 1) as usize;
        if let Some(cells) = r.channels.len().checked_mul(days)
            && cells <= 8_000_000
            && cells
                .checked_mul(threads)
                .and_then(|n| n.checked_mul(size_of::<Totals>()))
                .is_some_and(|n| n as u64 <= budget / 8)
        {
            Self::Dense {
                start,
                days,
                cells: vec![[0; 4]; cells],
            }
        } else {
            Self::default()
        }
    }
    #[inline]
    pub fn get(&mut self, c: usize, day: i32) -> &mut Totals {
        match self {
            Self::Dense { start, days, cells } => &mut cells[c * *days + (day - *start) as usize],
            Self::Sparse(map) => map.entry((c, day)).or_default(),
        }
    }
    pub fn merge_into(self, merged: &mut Map<(usize, i32), Totals>) {
        let mut add = |key, values: Totals| {
            let sum = merged.entry(key).or_default();
            for (s, v) in sum.iter_mut().zip(values) {
                *s += v;
            }
        };
        match self {
            Self::Dense { start, days, cells } => {
                for (i, v) in cells.into_iter().enumerate() {
                    if v[0] != 0 || v[3] != 0 {
                        add((i / days, start + (i % days) as i32), v);
                    }
                }
            }
            Self::Sparse(map) => {
                for (k, v) in map {
                    add(k, v);
                }
            }
        }
    }
}
