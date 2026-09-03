# Using ApiumSlicer Localization as a submodule

ApiumSlicer includes the standalone
[`ApiumSlicer-Localization`](https://github.com/Apium-3D-Technologies/ApiumSlicer-Localization)
repository at `resources/localization`. The main repository records one exact
Localization commit, keeping builds and generated catalogs reproducible.

General catalog semantics and the complete command reference are documented in
[README.md](README.md). This document covers the workflow from an ApiumSlicer
source checkout.

## Clone and initialize

Clone ApiumSlicer and its submodules together:

```text
git clone --recurse-submodules <ApiumSlicer repository URL>
```

For an existing checkout, initialize the Localization submodule with:

```text
git submodule update --init --recursive
```

Run all maintenance commands from the ApiumSlicer repository root:

```text
python resources/localization/localization.py <command>
```

The script discovers the Git superproject automatically. No source-root option
or environment variable is needed.

## Source and translation workflow

1. Mark each new user-visible C++ string with `L`, `_L`, `_u8L`,
   `L_CONTEXT`, or `_L_PLURAL`, as appropriate.
2. Create or select a Localization branch before generating changes:

   ```text
   cd resources/localization
   git switch -c <localization-branch>
   cd ../..
   ```

3. Run:

   ```text
   python resources/localization/localization.py sync
   ```

4. Edit the affected `.po` files directly. New untranslated entries are at the
   bottom. Review fuzzy suggestions and remove `fuzzy` only after correcting the
   translation.
5. Normalize and validate everything from the ApiumSlicer root:

   ```text
   python resources/localization/localization.py sync
   python resources/localization/localization.py overview --details
   python resources/localization/localization.py check
   python resources/localization/localization.py compile
   python -m unittest discover -s resources/localization/tests -v
   ```

6. Commit and push the catalog changes inside the Localization repository
   first.
7. Return to the ApiumSlicer repository, stage `resources/localization`, and
   commit the updated Gitlink separately:

   ```text
   git add resources/localization
   git commit -S -m "build: update localization submodule"
   ```

Never push a main-repository Gitlink that points to an unpublished submodule
commit. Other developers and CI would be unable to initialize that revision.

## Updating the pinned revision

To update to the latest Localization `main` revision intentionally:

```text
git -C resources/localization fetch origin
git -C resources/localization switch main
git -C resources/localization pull --ff-only
git add resources/localization
git commit -S -m "build: update localization submodule"
```

Review both the submodule log and the new pointer before committing:

```text
git diff --submodule=log
git -C resources/localization log --oneline --decorate -10
```

Do not use a floating branch reference for builds. `.gitmodules` records the
preferred branch for maintenance, while each ApiumSlicer commit still pins one
immutable Localization commit.

## Working tree behavior

The main repository reports `resources/localization` as modified when the
submodule is checked out at a different commit or contains local changes.
Inspect both repositories independently:

```text
git status --short
git -C resources/localization status --short
git -C resources/localization rev-parse HEAD
git ls-tree HEAD resources/localization
```

`git submodule update --init --recursive` restores the commit pinned by the
current ApiumSlicer revision. It may leave the submodule in detached-HEAD state;
create or switch to a branch before committing Localization changes.

## CMake integration

The existing gettext target names remain available and delegate to
`localization.py`:

- `gettext_make_pot` runs `extract`.
- `gettext_merge_po_with_pot` runs `sync`.
- `gettext_merge_community_po_with_pot` and
  `gettext_merge_wxwidgets_po_with_pot` remain compatibility names around the
  synchronized pipeline.
- `gettext_po_to_mo` runs `compile` and never edits PO files.

The build must not restore the historical append-only hints converter,
`compile.py`, `convert.py`, patch catalogs, or batch translation files.

## CI and review checklist

Before accepting a Localization pointer update, verify that:

- the referenced Localization commit exists on its remote;
- the submodule working tree is clean;
- `sync` is idempotent;
- `check` succeeds;
- all unit tests pass;
- `compile` validates and regenerates all required MO files;
- new or changed translations preserve placeholders, markup, plural forms, and
  relevant line breaks;
- fuzzy flags were removed only after human or agent review;
- both the Localization commit and the ApiumSlicer Gitlink commit are signed.

Informational `audit` candidates do not currently fail CI. Confirmed raw GUI
strings must first be marked in the ApiumSlicer source and then extracted by
`sync`; they must never be inserted into the POT manually.
