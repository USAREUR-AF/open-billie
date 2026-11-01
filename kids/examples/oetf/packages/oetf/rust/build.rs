// Embeds the shared, language-neutral OETF artifacts (schemas, maps, lookups)
// into the crate as `&[(relative_path, json_text)]` tables. Adding a map file
// under ../shared/mappings is picked up on the next build with no code change.

use std::{env, fs, path::Path, path::PathBuf};

fn collect(dir: &Path, rel: &str, out: &mut Vec<(String, PathBuf)>) {
    let mut entries: Vec<_> = fs::read_dir(dir)
        .unwrap_or_else(|e| panic!("reading {}: {e}", dir.display()))
        .map(|e| e.unwrap())
        .collect();
    entries.sort_by_key(|e| e.file_name());
    for e in entries {
        let name = e.file_name().to_string_lossy().into_owned();
        let r = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
        if e.file_type().unwrap().is_dir() {
            collect(&e.path(), &r, out);
        } else if name.ends_with(".json") && !name.starts_with('_') {
            out.push((r, e.path()));
        }
    }
}

fn main() {
    let shared = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("..").join("shared");
    let mut src = String::new();
    for (name, dir) in [
        ("SCHEMAS", shared.join("schemas")),
        ("MAPS", shared.join("mappings")),
        ("LOOKUPS", shared.join("lookups")),
    ] {
        println!("cargo:rerun-if-changed={}", dir.display());
        let mut files = Vec::new();
        collect(&dir, "", &mut files);
        src += &format!("pub static {name}: &[(&str, &str)] = &[\n");
        for (rel, path) in files {
            println!("cargo:rerun-if-changed={}", path.display());
            src += &format!("    ({rel:?}, include_str!({:?})),\n", path.display().to_string());
        }
        src += "];\n";
    }
    fs::write(PathBuf::from(env::var("OUT_DIR").unwrap()).join("bundled.rs"), src).unwrap();
}
