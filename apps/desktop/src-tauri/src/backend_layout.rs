//! P08 installed-backend layout contract.
//!
//! This module is deliberately a skeleton. P08-01 will wire the resolver into
//! the Tauri commands only after its implementation specification is approved.
//! The executable therefore retains its existing development-root behavior.

use std::path::PathBuf;

/// Where the desktop process obtained its backend resource root.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BackendLayoutOrigin {
    /// An explicit, valid developer override.
    EnvironmentOverride,
    /// The packaged Tauri resource directory.
    BundleResource,
    /// A development-only working-directory or executable-ancestor lookup.
    DevelopmentFallback,
}

/// Paths that must coexist for a desktop process to start the Python backend.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendLayout {
    /// Directory containing both the runner and the Python package.
    pub root: PathBuf,
    /// Expected path to tools/run_local.py below root.
    pub runner_path: PathBuf,
    /// Expected path to the backend Python package below root.
    pub package_path: PathBuf,
    /// The selected lookup source, exposed to doctor diagnostics.
    pub origin: BackendLayoutOrigin,
}

/// Safe category used when no valid backend resource layout can be selected.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BackendLayoutError {
    /// SODAM_REPOSITORY_ROOT was present but does not contain a valid layout.
    InvalidEnvironmentOverride,
    /// A packaged application did not contain its declared backend resources.
    MissingBundleResource,
    /// No development fallback path contains both required resources.
    MissingDevelopmentLayout,
}

/// Testable inputs for the future deterministic layout resolver.
///
/// Implementations must apply this order: valid environment override, valid
/// Tauri resource root, then a development-only fallback. Each candidate must
/// contain both tools/run_local.py and backend/; a partial layout is an error,
/// not a successful fallback.
#[derive(Clone, Debug, Default)]
pub struct BackendLayoutCandidates {
    pub environment_override: Option<PathBuf>,
    pub resource_root: Option<PathBuf>,
    pub development_roots: Vec<PathBuf>,
}

/// Resolve the packaged or development backend layout without spawning a process.
///
/// P08-01 replaces this placeholder with filesystem validation and focused Rust
/// unit tests. It is intentionally not called by the current application.
pub fn resolve_backend_layout(
    candidates: BackendLayoutCandidates,
) -> Result<BackendLayout, BackendLayoutError> {
    if let Some(root) = candidates.environment_override {
        return valid_layout(root, BackendLayoutOrigin::EnvironmentOverride)
            .ok_or(BackendLayoutError::InvalidEnvironmentOverride);
    }

    if let Some(root) = candidates.resource_root {
        return valid_layout(root, BackendLayoutOrigin::BundleResource)
            .ok_or(BackendLayoutError::MissingBundleResource);
    }

    for root in candidates.development_roots {
        if let Some(layout) = valid_layout(root, BackendLayoutOrigin::DevelopmentFallback) {
            return Ok(layout);
        }
    }

    Err(BackendLayoutError::MissingDevelopmentLayout)
}

fn valid_layout(root: PathBuf, origin: BackendLayoutOrigin) -> Option<BackendLayout> {
    let runner_path = root.join("tools").join("run_local.py");
    let package_path = root.join("backend");
    if !runner_path.is_file() || !package_path.is_dir() {
        return None;
    }
    Some(BackendLayout {
        root,
        runner_path,
        package_path,
        origin,
    })
}

#[cfg(test)]
mod tests {
    use super::{
        resolve_backend_layout, BackendLayoutCandidates, BackendLayoutError, BackendLayoutOrigin,
    };
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn fixture_root(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock is valid")
            .as_nanos();
        let root = std::env::temp_dir().join(format!("sodam-p08-{label}-{nonce}"));
        fs::create_dir_all(root.join("tools")).expect("create fixture tools");
        fs::create_dir_all(root.join("backend")).expect("create fixture backend");
        fs::write(root.join("tools").join("run_local.py"), b"# fixture")
            .expect("create fixture runner");
        root
    }

    fn remove_fixture(root: &Path) {
        fs::remove_dir_all(root).expect("remove fixture");
    }

    /// An override containing both resource paths wins over all other candidates.
    #[test]
    fn environment_override_has_highest_priority() {
        let override_root = fixture_root("override");
        let resource_root = fixture_root("resource");
        let development_root = fixture_root("development");
        let candidates = BackendLayoutCandidates {
            environment_override: Some(override_root.clone()),
            resource_root: Some(resource_root.clone()),
            development_roots: vec![development_root.clone()],
        };
        let layout = resolve_backend_layout(candidates).expect("override is valid");
        assert_eq!(layout.origin, BackendLayoutOrigin::EnvironmentOverride);
        assert_eq!(layout.root, override_root);
        remove_fixture(&override_root);
        remove_fixture(&resource_root);
        remove_fixture(&development_root);
    }

    /// A resource root wins over development fallback when no override exists.
    #[test]
    fn bundle_resource_precedes_development_fallback() {
        let resource_root = fixture_root("resource-priority");
        let development_root = fixture_root("development-priority");
        let candidates = BackendLayoutCandidates {
            environment_override: None,
            resource_root: Some(resource_root.clone()),
            development_roots: vec![development_root.clone()],
        };
        let layout = resolve_backend_layout(candidates).expect("resource is valid");
        assert_eq!(layout.origin, BackendLayoutOrigin::BundleResource);
        assert_eq!(layout.root, resource_root);
        remove_fixture(&resource_root);
        remove_fixture(&development_root);
    }

    /// An invalid explicit override must not be hidden by a valid fallback.
    #[test]
    fn invalid_override_does_not_fallback() {
        let fallback = fixture_root("invalid-override-fallback");
        let candidates = BackendLayoutCandidates {
            environment_override: Some(PathBuf::from("missing-override")),
            resource_root: None,
            development_roots: vec![fallback.clone()],
        };
        assert_eq!(
            resolve_backend_layout(candidates),
            Err(BackendLayoutError::InvalidEnvironmentOverride)
        );
        remove_fixture(&fallback);
    }

    /// A packaged root is accepted only when runner and backend both exist.
    #[test]
    fn partial_bundle_layout_is_not_accepted() {
        let root = std::env::temp_dir().join("sodam-p08-partial-bundle");
        fs::create_dir_all(root.join("tools")).expect("create partial tools");
        fs::write(root.join("tools").join("run_local.py"), b"# fixture")
            .expect("create partial runner");
        let candidates = BackendLayoutCandidates {
            environment_override: None,
            resource_root: Some(root.clone()),
            development_roots: Vec::new(),
        };
        assert_eq!(
            resolve_backend_layout(candidates),
            Err(BackendLayoutError::MissingBundleResource)
        );
        remove_fixture(&root);
    }

    /// Empty or invalid development candidates return a safe category.
    #[test]
    fn missing_development_layout_is_reported() {
        assert_eq!(
            resolve_backend_layout(BackendLayoutCandidates::default()),
            Err(BackendLayoutError::MissingDevelopmentLayout)
        );
    }

    /// The returned paths are deterministic children of the selected root.
    #[test]
    fn returned_paths_and_input_shape_are_deterministic() {
        let root = fixture_root("deterministic");
        let candidates = BackendLayoutCandidates {
            environment_override: None,
            resource_root: None,
            development_roots: vec![root.clone()],
        };
        let layout = resolve_backend_layout(candidates).expect("development root is valid");
        assert_eq!(layout.runner_path, root.join("tools").join("run_local.py"));
        assert_eq!(layout.package_path, root.join("backend"));
        assert!(layout.runner_path.starts_with(&layout.root));
        assert!(layout.package_path.starts_with(&layout.root));
        remove_fixture(&root);
    }
}
