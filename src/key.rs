use crate::Map;
use std::{
    cmp::Ordering,
    hash::Hash,
    sync::{Arc, Mutex, OnceLock},
};
#[derive(Copy, Clone, PartialEq, Eq, Hash, Default, Debug)]
pub struct IdKey([u8; 16]);
#[derive(Default)]
struct Long {
    indices: Map<Arc<[u8]>, u32>,
    ids: Vec<Arc<[u8]>>,
}
fn strings() -> &'static Mutex<Long> {
    static TABLE: OnceLock<Mutex<Long>> = OnceLock::new();
    TABLE.get_or_init(Default::default)
}
impl IdKey {
    #[inline]
    pub fn encode(s: &[u8]) -> Self {
        let mut a = [0; 16];
        if s.len() <= 15 {
            a[..s.len()].copy_from_slice(s);
            a[15] = s.len() as u8;
        } else {
            let mut table = strings().lock().unwrap();
            let index = if let Some(i) = table.indices.get(s) {
                *i
            } else {
                let i = u32::try_from(table.ids.len())
                    .expect("long ID table exceeds addressable memory");
                let value: Arc<[u8]> = Arc::from(s);
                table.ids.push(value.clone());
                table.indices.insert(value, i);
                i
            };
            a[..11].copy_from_slice(&s[..11]);
            a[11..15].copy_from_slice(&index.to_be_bytes());
            a[15] = 255;
        }
        Self(a)
    }
    fn view<'a>(&'a self, long: &'a Long) -> &'a [u8] {
        if self.0[15] < 16 {
            &self.0[..self.0[15] as usize]
        } else {
            &long.ids[u32::from_be_bytes(self.0[11..15].try_into().unwrap()) as usize]
        }
    }
    pub fn bytes(self) -> Vec<u8> {
        if self.0[15] < 16 {
            return self.0[..self.0[15] as usize].to_vec();
        }
        self.view(&strings().lock().unwrap()).to_vec()
    }
    #[inline]
    pub fn cmp_bytes(&self, b: &Self) -> Ordering {
        if self.0[15] < 16 && b.0[15] < 16 {
            return self.0.cmp(&b.0);
        }
        let table = strings().lock().unwrap();
        self.view(&table).cmp(b.view(&table))
    }
    #[inline]
    pub fn bucket(self, n: usize) -> usize {
        use std::hash::BuildHasher;
        (foldhash::fast::FixedState::default().hash_one(self) % n as u64) as usize
    }
}
