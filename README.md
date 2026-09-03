# ApiumSlicer localization

`localization.py` is the only maintenance tool for ApiumSlicer's gettext
catalogs. It discovers translatable source files, extracts messages, merges the
application and wxWidgets catalogs, validates translations, reports catalog
health, audits unmarked GUI strings, and compiles the runtime `.mo` files.

The tool always edits the actual POT and PO files. It does not create patch
catalogs, translation batches, or persistent intermediate files. Temporary
files are used only for validation and atomic replacement and are removed at
the end of each run.

## Requirements

- Python 3
- Git
- GNU gettext tools on `PATH`: `xgettext`, `msgcat`, `msguniq`, `msgmerge`,
  `msgattrib`, and `msgfmt`

From the ApiumSlicer repository root, run:

```text
python resources/localization/localization.py <command>
```

Use `python resources/localization/localization.py --help` or append `--help`
to a command to see its command-line options.

## Repository layouts and automatic source discovery

No source-root option or environment variable is required. The tool determines
its layout automatically, independently of the current working directory:

1. When this repository is mounted as a Git submodule, Git's superproject is
   used as the ApiumSlicer source checkout.
2. The historical `resources/localization` directory inside an ApiumSlicer
   checkout is detected by walking through the script's parent directories.
3. A standalone localization repository may be cloned directly next to one
   ApiumSlicer source checkout. The single matching sibling is selected
   automatically.

Example standalone sibling layout:

```text
workspace/
  ApiumSlicer/
    src/
    resources/data/hints.ini
  ApiumSlicer-Localization/
    localization.py
```

Commands may then be run from the standalone repository as follows:

```text
python localization.py sync
python localization.py check
```

`overview` and `compile` need only the localization repository and therefore
also work when no source checkout is present. `extract`, `sync`, `check`, and
`audit` require the ApiumSlicer sources. If no source checkout can be detected,
they stop with a diagnostic instead of silently using the wrong directory. If
multiple sibling source checkouts are present, place the localization checkout
inside the intended source tree as a submodule to make the relationship
unambiguous.

## Quick workflow

For a normal source-code change:

1. Mark every new user-visible C++ string with the appropriate gettext macro.
2. Run `python resources/localization/localization.py sync`.
3. Open the affected `ApiumSlicer_<locale>.po` files and translate their empty
   entries directly. New empty entries are at the end of each file.
4. Review fuzzy translations and remove the `fuzzy` flag only after correcting
   the translation.
5. Run `sync` again so entries are normalized and reordered.
6. Run `python resources/localization/localization.py overview --details`.
7. Run `python resources/localization/localization.py check`.
8. Run `python resources/localization/localization.py compile`.

Do not edit `list.txt`, `ApiumSlicer.pot`, source references, or `.mo` files by
hand. They are generated outputs.

## Command reference

### `overview`

```text
python resources/localization/localization.py overview
python resources/localization/localization.py overview --details
```

This command is read-only. It prints the number of project messages extracted
into the POT, the number of configured languages, totals across all effective
catalogs, and a per-language table:

```text
Language  Total  Translated  Fuzzy  Empty  Damaged  Invalid chars  Obsolete
```

The columns mean:

- `Total`: active messages in the effective application catalog. This includes
  project messages and merged wxWidgets messages, but excludes the PO header
  and obsolete entries.
- `Translated`: every required `msgstr` is non-empty and the entry is not
  fuzzy. Plural entries count as translated only when every plural form is
  filled.
- `Fuzzy`: gettext considers the translation an unreviewed approximation.
  Fuzzy messages are normally excluded from the compiled runtime catalog.
- `Empty`: a non-fuzzy entry has at least one missing required translation.
- `Damaged`: the translation has a placeholder, printf conversion, HTML tag,
  paragraph-break, or duplicate-key inconsistency. This is a health count and
  may overlap the other state columns.
- `Invalid chars`: the entry contains invalid Unicode, prohibited control
  characters, Unicode noncharacters, decoding replacement characters, or a
  common UTF-8 mojibake sequence such as `Â°`. This count may also overlap the
  state and damaged columns. Source keys, contexts, singular/plural forms, and
  translations are all inspected because a damaged source key affects every
  language.
- `Obsolete`: old `#~` entries still present in the file. A successful `sync`
  removes them, so this should normally be zero.

The `ALL` row is the sum across language catalogs, not the number of unique
source messages. Use `--details` to print the source reference, `msgid`, and
reason for every entry counted as damaged or containing invalid characters.
The overview remains informational and returns successfully when it finds a
problem; `check` and `compile` provide the blocking validation gates.

### `sync`

```text
python resources/localization/localization.py sync
```

`sync` performs the complete reproducible update:

1. It asks Git for all tracked C and C++ sources below `src/` with extensions
   `.c`, `.cc`, `.cpp`, `.cxx`, `.h`, `.hh`, `.hpp`, and `.hxx`.
2. It excludes tests, sandboxes, bundled dependencies, and other foreign
   source trees.
3. It writes the sorted repository-relative paths to `list.txt` using `/` path
   separators, UTF-8, and LF line endings.
4. It runs `xgettext` with the `_`, `L`, `_L`, `_u8L`, `L_CONTEXT:1,2c`, and
   `_L_PLURAL:1,2` markers. `TRN` comments, contexts, plural forms, Boost format
   flags, and current file/line references are retained.
5. It reads `resources/data/hints.ini` directly and adds its messages and
   references without using an append-only converter.
6. It combines and deduplicates the extracted data, normalizes the POT header,
   removes the changing generation timestamp, and writes `ApiumSlicer.pot`.
7. It synchronizes each `ApiumSlicer_<locale>.po` against the new POT.
8. It merges the matching `wx_locale/<locale>.po`. If application and wxWidgets
   catalogs contain the same key, the existing ApiumSlicer translation wins.
9. It removes obsolete entries and rejects conflicting duplicate translations.
10. It validates placeholders, markup, headers, plural forms, and gettext
    format flags before replacing a PO file.
11. It orders entries as translated, then fuzzy, then empty while preserving
    stable relative order inside each group.

All generated gettext output uses UTF-8, LF, and a fixed width of 100 columns.
Each destination is written to a temporary sibling, flushed, validated, and
then replaced with `os.replace`. A failed validation leaves the original file
untouched.

`sync --use-existing-pot` skips POT extraction and merges against the checked-in
POT. It is intended for focused catalog maintenance or diagnostics. Normal
development should use the full `sync` command.

### `extract`

```text
python resources/localization/localization.py extract
```

`extract` regenerates only `list.txt` and `ApiumSlicer.pot`. It does not update
PO or MO files. Most contributors should use `sync`, which includes extraction.

### `check`

```text
python resources/localization/localization.py check
```

`check` rebuilds the expected source list, POT, and PO catalogs entirely in a
temporary directory and compares them byte-for-byte with the checked-in files.
It fails when references are stale, extraction or merge output differs, entry
order is wrong, duplicates or obsolete entries exist, translations have
structural problems, or gettext rejects a catalog. This also verifies that a
second `sync` would produce no changes.

After the blocking checks pass, the command prints the informational raw-string
audit. Audit findings do not currently change the exit status.

### `audit`

```text
python resources/localization/localization.py audit
```

`audit` scans tracked sources for direct string literals passed to known
wxWidgets UI sinks, including dialog titles, static text, buttons, checkboxes,
radio buttons, menus, `SetLabel`, and message dialogs. It reports candidates as:

```text
path/to/file.cpp:123: [SetLabel] Raw user-visible text
```

It never changes source code or catalogs. A candidate must first be marked in
C++ with `L`, `_L`, `_u8L`, `L_CONTEXT`, or `_L_PLURAL`; the next `sync` then
adds it to every catalog.

Stable false positives may be added to `audit_allowlist.json`:

```json
[
  {
    "path": "src/example.cpp",
    "sink": "SetLabel",
    "literal": "Technical ID",
    "reason": "Protocol identifier, not user-facing prose"
  }
]
```

Line numbers are deliberately not part of the allowlist key because they change
as source files evolve. Every allowlist entry requires a non-empty reason.

### `compile`

```text
python resources/localization/localization.py compile
```

`compile` validates every application PO with
`msgfmt --check --check-format`, compiles all catalogs to temporary MO files,
and replaces the checked-in `ApiumSlicer.mo` files only after every language
has succeeded. It never modifies a PO file.

## Translation states and ordering

A gettext message key consists of `msgctxt + msgid + msgid_plural`. Identical
English text in different contexts is intentionally treated as different
messages. Singular and plural messages are also distinct keys.

`msgmerge` marks an entry `fuzzy` when it maps an older translation to a similar
new source string. The existing `msgstr` is only a suggestion and can be
completely unrelated. Review the current `msgid`, replace every singular or
plural translation, and remove `fuzzy`. Never remove the flag merely to improve
coverage statistics.

To inspect German fuzzy messages without creating a file:

```text
msgattrib --only-fuzzy --no-obsolete resources/localization/de/ApiumSlicer_de.po
```

After `sync`, PO files have three stable sections:

1. complete, non-fuzzy translations;
2. fuzzy entries requiring review;
3. non-fuzzy entries with at least one empty translation.

This places every newly extracted untranslated label at the bottom. Completing
and approving it moves it into the first section during the next `sync`.

## English source-language policy

All original application strings are English. During every `sync`, the English
catalog is regenerated so that each singular `msgstr` equals its `msgid`, and
each plural translation equals the corresponding singular or plural source
form. English fuzzy flags are removed automatically. Do not use the English PO
to introduce wording or product-name changes; change the original source string
instead and run `sync`.

## Context, plurals, placeholders, and formatting

- Use `L_CONTEXT(text, context)` when identical English labels require different
  meanings in another language.
- Use `_L_PLURAL(singular, plural, count)` for count-dependent text. Fill every
  `msgstr[n]` required by the locale's `Plural-Forms` header.
- Preserve Boost placeholders such as `%1%`, printf placeholders such as `%s`
  and `%1$d`, named placeholders such as `{name}`, Slicer placeholders such as
  `[filament_diameter_0]`, relevant paragraph breaks, and supported HTML tags.
- Custom strings such as `%n%` that resemble printf or Boost directives must be
  annotated at the source with the appropriate `xgettext:no-c-format` and
  `xgettext:no-boost-format` comments.
- Do not change technical placeholder names in a translation.

## Files maintained by the tool

- `localization.py`: the single implementation and command-line interface.
- `list.txt`: generated list of tracked extraction inputs.
- `ApiumSlicer.pot`: deterministic project message template.
- `<locale>/ApiumSlicer_<locale>.po`: directly edited human translations plus
  merged wxWidgets messages.
- `<locale>/ApiumSlicer.mo`: validated runtime catalog generated by `compile`.
- `wx_locale/<locale>.po`: upstream wxWidgets translation input.
- `audit_allowlist.json`: reviewed raw-string audit exceptions.

The historical `compile.py`, `convert.py`, append-only hints converter flow, and
`README.txt` are no longer part of the workflow.

## CMake integration

The existing gettext target names remain available for build integration, but
they delegate to `localization.py`:

- `gettext_make_pot` runs `extract`;
- `gettext_merge_po_with_pot` runs `sync`;
- `gettext_merge_community_po_with_pot` and
  `gettext_merge_wxwidgets_po_with_pot` remain compatibility target names around
  the same synchronized pipeline;
- `gettext_po_to_mo` runs `compile` and never edits PO files.

## Tests

The maintenance code has isolated fixture tests inside the localization
repository under `tests`. From the ApiumSlicer source root, run:

```text
python -m unittest discover -s resources/localization/tests -v
```

From a standalone localization checkout, run instead:

```text
python -m unittest discover -s tests -v
```

The tests cover extraction references, hints, contexts, plurals, duplicate
handling, application-over-wx precedence, direct PO translation, fuzzy review,
English source-language generation, ordering, format validation, overview
health counts, audit detection, and allowlisting.

Before committing localization changes, run at minimum:

```text
python -m unittest discover -s resources/localization/tests -v
python resources/localization/localization.py sync
python resources/localization/localization.py overview --details
python resources/localization/localization.py check
python resources/localization/localization.py compile
```

If `check` reports drift, run `sync`, inspect the direct PO changes, complete or
review translations, and repeat the checks. Do not resolve drift by editing
generated references or copying fragments into a separate patch catalog.
