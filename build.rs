use std::{
    fs,
    path::{Path, PathBuf},
};

fn collect(dir: &Path, files: &mut Vec<PathBuf>) {
    for item in fs::read_dir(dir).expect("source directory") {
        let path = item.expect("source entry").path();
        if path.is_dir() {
            collect(&path, files);
        } else {
            files.push(path);
        }
    }
}

fn main() {
    let mut files = vec![PathBuf::from("Cargo.toml"), PathBuf::from("Cargo.lock")];
    collect(Path::new("src"), &mut files);
    files.sort();
    let mut hash = 0xcbf29ce484222325u64;
    println!("cargo:rerun-if-changed=src");
    for file in files {
        println!("cargo:rerun-if-changed={}", file.display());
        for byte in file
            .to_str()
            .unwrap()
            .bytes()
            .chain([0])
            .chain(fs::read(&file).unwrap())
            .chain([0])
        {
            hash = (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3);
        }
    }
    println!("cargo:rustc-env=SS_BUILD_ID={hash:016x}");
}
