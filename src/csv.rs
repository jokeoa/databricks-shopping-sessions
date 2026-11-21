#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum Bad {
    EmptyLine,
    Fields,
    Quote,
}
impl Bad {
    pub fn label(self) -> &'static str {
        match self {
            Self::EmptyLine => "empty_line",
            Self::Fields => "field_count",
            Self::Quote => "quote",
        }
    }
}
#[inline]
pub fn scalar<const N: usize>(line: &[u8]) -> Result<[&[u8]; N], Bad> {
    if line.is_empty() {
        return Err(Bad::EmptyLine);
    }
    let mut fields = [&[][..]; N];
    let mut count = 0;
    for field in line.split(|&b| b == b',') {
        if count == N {
            return Err(Bad::Fields);
        }
        fields[count] = field;
        count += 1;
    }
    if count != N {
        return Err(Bad::Fields);
    }
    for field in &mut fields {
        if field.first() == Some(&b'"') {
            if field.len() < 2 || field.last() != Some(&b'"') {
                return Err(Bad::Quote);
            }
            *field = &field[1..field.len() - 1];
        }
        if memchr::memchr(b'"', field).is_some() {
            return Err(Bad::Quote);
        }
    }
    Ok(fields)
}

// Each bit represents the byte at the same position in the physical line.
#[cfg(target_arch = "x86_64")]
#[inline]
fn punctuation(block: &[u8; 16]) -> (u16, u16) {
    use std::arch::x86_64::*;
    // SSE2 is part of x86_64. The array guarantees sixteen readable bytes.
    unsafe {
        let value = _mm_loadu_si128(block.as_ptr().cast());
        let mask = |c| _mm_movemask_epi8(_mm_cmpeq_epi8(value, _mm_set1_epi8(c))) as u16;
        (mask(b',' as i8), mask(b'"' as i8))
    }
}
#[cfg(target_arch = "aarch64")]
#[inline]
fn punctuation(block: &[u8; 16]) -> (u16, u16) {
    use std::arch::aarch64::*;
    const WEIGHTS: [u8; 16] = [1, 2, 4, 8, 16, 32, 64, 128, 1, 2, 4, 8, 16, 32, 64, 128];
    // Advanced SIMD is available on the Apple Silicon development target.
    unsafe {
        let value = vld1q_u8(block.as_ptr());
        let weights = vld1q_u8(WEIGHTS.as_ptr());
        let mask = |c| {
            let bits = vandq_u8(vceqq_u8(value, vdupq_n_u8(c)), weights);
            u16::from(vaddv_u8(vget_low_u8(bits))) | (u16::from(vaddv_u8(vget_high_u8(bits))) << 8)
        };
        (mask(b','), mask(b'"'))
    }
}
#[inline]
pub fn split_line<const N: usize>(line: &[u8]) -> Result<[&[u8]; N], Bad> {
    #[cfg(any(target_arch = "x86_64", target_arch = "aarch64"))]
    if (16..=128).contains(&line.len()) && N > 0 {
        let mut commas = 0u128;
        let mut quotes = 0u128;
        let mut pos = 0;
        loop {
            let (c, q) = punctuation(line[pos..pos + 16].try_into().unwrap());
            commas |= u128::from(c) << pos;
            quotes |= u128::from(q) << pos;
            if pos + 16 == line.len() {
                break;
            }
            pos = (pos + 16).min(line.len() - 16);
        }
        if commas.count_ones() as usize != N - 1 {
            return Err(Bad::Fields);
        }
        let mut fields = [&[][..]; N];
        let mut start = 0;
        for field in &mut fields {
            let end = if commas == 0 {
                line.len()
            } else {
                let end = commas.trailing_zeros() as usize;
                commas &= commas - 1;
                end
            };
            if end > start && quotes & (1u128 << start) != 0 {
                if end - start < 2 || quotes & (1u128 << (end - 1)) == 0 {
                    return Err(Bad::Quote);
                }
                quotes ^= (1u128 << start) | (1u128 << (end - 1));
                *field = &line[start + 1..end - 1];
            } else {
                *field = &line[start..end];
            }
            start = end + 1;
        }
        return if quotes == 0 {
            Ok(fields)
        } else {
            Err(Bad::Quote)
        };
    }
    scalar(line)
}
