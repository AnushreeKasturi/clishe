# Releasing Clishe

1. Bump `version` in `pyproject.toml` and `CLISHE_VERSION` in `clishe.sh`.
   The two must match: `clishe --version` reads `CLISHE_VERSION`, PyPI reads
   `pyproject.toml`.
2. Rename `## Unreleased` to `## X.Y.Z (date)` in the CHANGELOG.
3. Open a PR, and merge it when CI passes.
4. Run `gh release create vX.Y.Z --target main` with the changelog section as
   notes. `publish.yml` then uploads to PyPI (trusted publishing).
5. Check the upload finished (`gh run list --workflow publish.yml`) and the
   new version is on PyPI.
6. Update `packaging/aur` to the new tarball's sha256 in a follow-up PR.

Issue labels for contributors: `good first issue`, `data only (no code)`,
`help wanted` and `testing`.
