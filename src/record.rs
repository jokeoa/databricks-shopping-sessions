use crate::{
    csv::{Bad, split_line},
    key::IdKey,
    price,
    refdata::Refs,
    ts,
};

#[repr(u8)]
#[derive(Debug, Copy, Clone, Default, PartialEq, Eq)]
pub enum Fate {
    #[default]
    Valid,
    EmptyLine,
    FieldCount,
    Quote,
    MissingId,
    BadIngest,
    EmptyPerson,
    BadTime,
    Outside,
    BadType,
    EmptyProduct,
    BadPrice,
    Late,
    UnknownCampaign,
}
pub const FATES: [Fate; 14] = [
    Fate::Valid,
    Fate::EmptyLine,
    Fate::FieldCount,
    Fate::Quote,
    Fate::MissingId,
    Fate::BadIngest,
    Fate::EmptyPerson,
    Fate::BadTime,
    Fate::Outside,
    Fate::BadType,
    Fate::EmptyProduct,
    Fate::BadPrice,
    Fate::Late,
    Fate::UnknownCampaign,
];
impl Fate {
    pub fn label(self) -> &'static str {
        [
            "valid",
            "empty_line",
            "field_count",
            "quote",
            "missing_id",
            "bad_ingest",
            "empty_person",
            "bad_time",
            "outside",
            "bad_type",
            "empty_product",
            "bad_price",
            "late",
            "unknown_campaign",
        ][self as usize]
    }
}
impl From<Bad> for Fate {
    fn from(v: Bad) -> Self {
        match v {
            Bad::EmptyLine => Self::EmptyLine,
            Bad::Fields => Self::FieldCount,
            Bad::Quote => Self::Quote,
        }
    }
}
#[derive(Copy, Clone, Debug, Default, PartialEq)]
pub struct Event {
    pub ts: i64,
    pub category: usize,
    pub cents: u32,
}
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct Candidate {
    pub user: IdKey,
    pub ingest: i64,
    pub event: Event,
    pub fate: Fate,
}
#[derive(Copy, Clone, Debug)]
pub struct Click {
    pub ts: i64,
    pub id: IdKey,
    pub campaign: usize,
}
fn timestamp(raw: &[u8], start: i64, end: i64) -> Result<i64, Fate> {
    match ts::parse(raw) {
        Ok(v) if (start..end).contains(&v) => Ok(v),
        Err(ts::Bad::Format) => Err(Fate::BadTime),
        _ => Err(Fate::Outside),
    }
}
fn validate(fields: &[&[u8]; 7], ingest: i64, r: &Refs) -> Result<Event, Fate> {
    if fields[1].is_empty() {
        return Err(Fate::EmptyPerson);
    }
    let ts = timestamp(fields[2], r.first, r.end)?;
    let purchase = match fields[4] {
        b"purchase" => true,
        b"view" | b"cart" => false,
        _ => return Err(Fate::BadType),
    };
    if fields[5].is_empty() {
        return Err(Fate::EmptyProduct);
    }
    let (cents, category) = if purchase {
        (
            price::parse(fields[6]).ok_or(Fate::BadPrice)?,
            *r.products.get(fields[5]).unwrap_or(&r.unknown),
        )
    } else {
        (0, 0)
    };
    if ingest - ts > ts::DAY {
        return Err(Fate::Late);
    }
    Ok(Event {
        ts,
        cents,
        category,
    })
}
#[inline]
pub fn event(line: &[u8], r: &Refs) -> Result<(IdKey, Candidate), Fate> {
    let f = split_line::<7>(line)?;
    if f[0].is_empty() {
        return Err(Fate::MissingId);
    }
    let ingest = ts::f1(f[3]).ok_or(Fate::BadIngest)?;
    let (event, fate) = match validate(&f, ingest, r) {
        Ok(e) => (e, Fate::Valid),
        Err(f) => (Event::default(), f),
    };
    if crate::mutation("validate_first") && fate != Fate::Valid {
        return Err(fate);
    }
    Ok((
        IdKey::encode(f[0]),
        Candidate {
            user: IdKey::encode(f[1]),
            ingest,
            event,
            fate,
        },
    ))
}
#[inline]
pub fn click(line: &[u8], r: &Refs) -> Result<(IdKey, Click), Fate> {
    let [id, user, campaign, raw] = split_line::<4>(line)?;
    if id.is_empty() {
        return Err(Fate::MissingId);
    }
    if user.is_empty() {
        return Err(Fate::EmptyPerson);
    }
    let ts = timestamp(raw, r.first - ts::WEEK, r.end)?;
    let campaign = *r.campaigns.get(campaign).ok_or(Fate::UnknownCampaign)?;
    Ok((
        IdKey::encode(user),
        Click {
            ts,
            id: IdKey::encode(id),
            campaign,
        },
    ))
}
#[derive(Default, Debug)]
pub struct Counters {
    pub events: [u64; 14],
    pub clicks: [u64; 14],
    pub winners: [u64; 14],
    pub equal_diff: u64,
}
impl Counters {
    pub fn add(&mut self, rhs: &Self) {
        for i in 0..14 {
            self.events[i] += rhs.events[i];
            self.clicks[i] += rhs.clicks[i];
            self.winners[i] += rhs.winners[i];
        }
        self.equal_diff += rhs.equal_diff;
    }
    pub fn json(&self) -> serde_json::Value {
        let tally = |a: &[u64; 14]| {
            FATES
                .iter()
                .filter(|f| a[**f as usize] > 0)
                .map(|f| (f.label(), a[*f as usize]))
                .collect::<std::collections::BTreeMap<_, _>>()
        };
        serde_json::json!({"raw":{"events":tally(&self.events),"clicks":tally(&self.clicks)},"event_winners":tally(&self.winners),"equal_ingest_projection_diff":self.equal_diff})
    }
}
