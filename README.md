# ApiumSlicer Localization

This repository contains the gettext catalogs and the maintenance tooling for
ApiumSlicer translations. It can be cloned and maintained as a standalone
repository. The same repository is also consumed by ApiumSlicer as a Git
submodule; see [README_APIUMSLICER.md](README_APIUMSLICER.md) for that workflow.

`localization.py` is the single entry point for extracting source messages,
synchronizing translations, checking catalog health, auditing unmarked GUI
strings, and compiling runtime catalogs. It edits the actual POT and PO files
directly. Temporary files are used only for validation and atomic replacement;
the workflow does not create patch catalogs or persistent intermediate files.

## Repository contents

- `localization.py`: command-line maintenance tool.
- `list.txt`: generated list of tracked ApiumSlicer extraction inputs.
- `ApiumSlicer.pot`: deterministic application message template.
- `<locale>/ApiumSlicer_<locale>.po`: directly maintained translations.
- `<locale>/ApiumSlicer.mo`: compiled runtime catalogs.
- `wx_locale/<locale>.po`: upstream wxWidgets translation inputs.
- `audit_allowlist.json`: reviewed exceptions for the raw-string audit.
- `tests/`: isolated unit tests for the maintenance tool.

Do not edit `list.txt`, `ApiumSlicer.pot`, source references, or `.mo` files by
hand. They are generated outputs. Human and AI translators edit the `.po` files
directly.

## Requirements

- Python 3
- Git
- GNU gettext tools on `PATH`: `xgettext`, `msgcat`, `msguniq`, `msgmerge`,
  `msgattrib`, and `msgfmt`

Display the available commands with:

```text
python localization.py --help
```

## Standalone setup

Commands that inspect or compile existing catalogs work immediately after
cloning this repository:

```text
git clone https://github.com/Apium-3D-Technologies/ApiumSlicer-Localization.git
cd ApiumSlicer-Localization
python localization.py overview
python localization.py compile
```

Extraction-based commands additionally require an ApiumSlicer source checkout.
Clone both repositories next to each other:

```text
workspace/
  ApiumSlicer/
    src/
    resources/data/hints.ini
  ApiumSlicer-Localization/
    localization.py
```

No source-root option or environment variable is required. The script searches
for exactly one compatible sibling checkout and verifies the expected
ApiumSlicer source layout. If no source checkout can be found, or multiple
matching siblings make the choice ambiguous, the command stops with a clear
diagnostic instead of selecting an arbitrary directory.

The tool also recognizes its historical embedded layout and its current Git
submodule layout automatically. Its behavior does not depend on the current
working directory.

## Translation workflow

1. Ensure that new user-visible C++ strings are marked with the appropriate
   gettext macro in the adjacent ApiumSlicer checkout.
2. Run `python localization.py sync`.
3. Edit empty entries directly in the affected
   `<locale>/ApiumSlicer_<locale>.po` file. Newly extracted empty entries are at
   the bottom.
4. Review fuzzy suggestions carefully. Correct every translation and remove
   the `fuzzy` flag only after approval.
5. Run `sync` again to normalize and reorder the catalogs.
6. Run `python localization.py overview --details`.
7. Run `python localization.py check`.
8. Run `python localization.py compile`.
9. Commit the changed source catalogs and generated files together.

Only one translation agent should modify a catalog at a time. This avoids
unnecessary PO merge conflicts and makes review of generated changes reliable.

## Commands

### `overview`

```text
python localization.py overview
python localization.py overview --details
```

This read-only command reports project messages, configured languages, totals,
and a per-language table:

```text
Language  Total  Translated  Fuzzy  Empty  Damaged  Invalid chars  Obsolete
```

- `Total`: active messages in the effective application catalog, including
  merged wxWidgets messages but excluding the PO header and obsolete entries.
- `Translated`: all required translations are non-empty and not fuzzy. Every
  required plural form must be filled.
- `Fuzzy`: gettext considers the existing translation an unreviewed suggestion.
  Fuzzy messages are normally excluded from compiled runtime catalogs.
- `Empty`: a non-fuzzy entry is missing at least one required translation.
- `Damaged`: placeholder, printf conversion, HTML structure, paragraph-break,
  or duplicate-key validation found an inconsistency.
- `Invalid chars`: invalid Unicode, prohibited controls, Unicode noncharacters,
  replacement characters, or common UTF-8 mojibake were detected.
- `Obsolete`: old `#~` entries remain in the catalog.

Health columns may overlap translation-state columns. The `ALL` row sums the
language catalogs; it is not a count of unique source messages. `--details`
prints the source reference, message ID, and reason for each health problem.
`overview` remains informational, while `check` and `compile` are blocking
validation gates.

### `sync`

```text
python localization.py sync
```

`sync` performs the complete reproducible update:

1. It asks Git for tracked C and C++ files below the source repository's `src/`
   directory, excluding tests, sandboxes, bundled dependencies, and foreign
   source trees.
2. It writes sorted repository-relative paths to `list.txt` using UTF-8, `/`
   separators, and LF endings.
3. It invokes `xgettext` for `_`, `L`, `_L`, `_u8L`, `L_CONTEXT:1,2c`, and
   `_L_PLURAL:1,2`, retaining translator comments, contexts, plurals, format
   flags, and current source references.
4. It reads `resources/data/hints.ini` from the source checkout directly.
5. It combines and deduplicates messages and creates a deterministic POT header
   without a changing generation timestamp.
6. It merges every application PO against the POT and its matching wxWidgets
   catalog. An existing ApiumSlicer translation wins on an identical key.
7. It removes obsolete entries, detects conflicting duplicates, validates
   structure and formats, and orders entries as translated, fuzzy, then empty.

All generated gettext output uses UTF-8, LF, and a width of 100 columns. Each
destination is written to a temporary sibling, flushed, validated, and replaced
atomically. A failed validation leaves the original catalog untouched.

`sync --use-existing-pot` skips source extraction and merges against the
checked-in POT. It is intended for focused catalog maintenance and diagnostics;
normal updates should use the complete `sync` command.

### `extract`

```text
python localization.py extract
```

Regenerates only `list.txt` and `ApiumSlicer.pot`. It does not update PO or MO
files. Most contributors should use `sync`, which includes extraction.

### `check`

```text
python localization.py check
```

Rebuilds the expected source list, POT, and PO catalogs in a temporary directory
and compares them byte-for-byte with the repository. It fails for stale source
references, extraction or merge drift, incorrect ordering, duplicates, obsolete
entries, structural translation damage, invalid characters, invalid gettext
catalogs, or a non-idempotent synchronization result.

After its blocking checks pass, it prints the informational raw-string audit.
Audit findings currently do not change the exit status.

### `audit`

```text
python localization.py audit
```

Scans tracked ApiumSlicer sources for direct string literals passed to known
wxWidgets UI sinks. Candidates are reported as:

```text
path/to/file.cpp:123: [SetLabel] Raw user-visible text
```

The command never changes source code or catalogs. Mark a confirmed UI string
with `L`, `_L`, `_u8L`, `L_CONTEXT`, or `_L_PLURAL` in the source repository;
the next `sync` will extract it. Stable false positives can be added to
`audit_allowlist.json` with `path`, `sink`, `literal`, and a non-empty `reason`.
Line numbers are deliberately not part of an allowlist key.

### `compile`

```text
python localization.py compile
```

Validates every application PO with `msgfmt --check --check-format`, compiles
all catalogs to temporary MO files, and replaces the checked-in runtime files
only after every language succeeds. It never modifies a PO file.

## Translation rules

A gettext key consists of `msgctxt + msgid + msgid_plural`. Equal English text
in distinct contexts therefore represents distinct messages, as do singular
and plural messages.

`msgmerge` marks an entry `fuzzy` when it maps an older translation to a similar
new source string. Its `msgstr` is only a suggestion and may be semantically
wrong. Review the current source text, replace every singular or plural
translation, and only then remove `fuzzy`.

Inspect fuzzy entries, for example in German, without creating another file:

```text
msgattrib --only-fuzzy --no-obsolete de/ApiumSlicer_de.po
```

After synchronization, catalogs contain complete translations first, fuzzy
entries second, and non-fuzzy empty entries last. Completing and approving an
entry moves it into the translated section during the next `sync`.

All original application strings are English. During `sync`, the English
catalog is regenerated so singular translations equal their `msgid` and plural
translations equal the corresponding source form. English fuzzy flags are
removed automatically. Wording and product-name changes belong in the source
code, not in the English catalog.

Translations must preserve Boost placeholders such as `%1%`, printf tokens such
as `%s` and `%1$d`, named placeholders such as `{name}`, Slicer placeholders
such as `[filament_diameter_0]`, relevant paragraph breaks, and supported HTML
tags. Use `L_CONTEXT` for meaning-dependent translations and `_L_PLURAL` for
count-dependent strings, filling every plural form required by the PO header.

## Tests

Run the isolated test suite from this repository:

```text
python -m unittest discover -s tests -v
```

Before committing, run at minimum:

```text
python -m unittest discover -s tests -v
python localization.py sync
python localization.py overview --details
python localization.py check
python localization.py compile
```

If `check` reports drift, run `sync`, inspect the direct PO changes, complete or
review translations, and repeat the checks. Do not resolve drift by editing
generated references or by copying fragments into a separate patch catalog.

## ApiumSlicer integration

This repository is mounted at `resources/localization` in ApiumSlicer. Build
maintainers and source contributors should use the commands and submodule
procedures in [README_APIUMSLICER.md](README_APIUMSLICER.md).

## License

This repository is distributed under the GNU Affero General Public License,
version 3, matching the ApiumSlicer project. See [LICENSE](LICENSE) for the full
license text.
