pub const DAY: i64 = 86_400_000;
pub const WEEK: i64 = 7 * DAY;
pub const GAP: i64 = 1_800_000;
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum Bad {
    Format,
    Range,
}
#[inline]
fn pair(v: &[u8]) -> Option<i64> {
    let a = v[0].wrapping_sub(b'0');
    let b = v[1].wrapping_sub(b'0');
    (a < 10 && b < 10).then_some(i64::from(a) * 10 + i64::from(b))
}
#[inline]
fn calendar(v: &[u8]) -> Option<i64> {
    if v[4] != b'-' || v[7] != b'-' || v[10] != b'T' || v[13] != b':' || v[16] != b':' {
        return None;
    }
    let year = pair(v)? * 100 + pair(&v[2..])?;
    let month = pair(&v[5..])?;
    let day = pair(&v[8..])?;
    let hour = pair(&v[11..])?;
    let minute = pair(&v[14..])?;
    let second = pair(&v[17..])?;
    let max = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => 28 + i64::from(year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)),
        _ => return None,
    };
    if day < 1 || day > max || hour > 23 || minute > 59 || second > 59 {
        return None;
    }
    // Days from civil, using March as the first month of a leap cycle.
    let y = year - i64::from(month <= 2);
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let m = if month <= 2 { month + 9 } else { month - 3 };
    let days =
        era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + (153 * m + 2) / 5 + day - 1 - 719468;
    Some(days * DAY + ((hour * 60 + minute) * 60 + second) * 1000)
}
#[inline]
pub fn f1(v: &[u8]) -> Option<i64> {
    if v.len() != 20 || v[19] != b'Z' {
        return None;
    }
    calendar(v)
}
#[inline]
pub fn parse(v: &[u8]) -> Result<i64, Bad> {
    if v.get(4) == Some(&b'-') {
        return match v.len() {
            20 => f1(v).ok_or(Bad::Format),
            25 if matches!(v[19], b'+' | b'-') && v[22] == b':' => {
                let h = pair(&v[20..]).ok_or(Bad::Format)?;
                let m = pair(&v[23..]).ok_or(Bad::Format)?;
                if h > 23 || m > 59 {
                    return Err(Bad::Format);
                }
                let sign = if v[19] == b'+' { 1 } else { -1 };
                Ok(calendar(v).ok_or(Bad::Format)? - sign * (h * 60 + m) * 60000)
            }
            _ => Err(Bad::Format),
        };
    }
    if v.is_empty() || !v.iter().all(u8::is_ascii_digit) {
        return Err(Bad::Format);
    }
    let mut value = 0i64;
    for &b in v {
        value = value
            .checked_mul(10)
            .and_then(|n| n.checked_add(i64::from(b - b'0')))
            .ok_or(Bad::Range)?;
    }
    Ok(value)
}
