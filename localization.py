#!/usr/bin/env python3
"""Reproducible gettext catalog maintenance for ApiumSlicer."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
POT_PATH = SCRIPT_DIR / "ApiumSlicer.pot"
LIST_PATH = SCRIPT_DIR / "list.txt"
HINTS_PATH = REPO_ROOT / "resources" / "data" / "hints.ini"
AUDIT_ALLOWLIST_PATH = SCRIPT_DIR / "audit_allowlist.json"
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
GETTEXT_TOOLS = ("xgettext", "msgcat", "msguniq", "msgmerge", "msgattrib", "msgfmt")
WIDTH = "100"


class LocalizationError(RuntimeError):
    """Raised when catalog generation or validation cannot continue safely."""


@dataclass(frozen=True)
class CatalogEntry:
    block: str
    msgctxt: str
    msgid: str
    msgid_plural: str
    translations: tuple[tuple[int, str], ...]
    flags: frozenset[str]
    obsolete: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return self.msgctxt, self.msgid, self.msgid_plural

    @property
    def is_header(self) -> bool:
        return not self.obsolete and self.msgid == "" and self.msgctxt == ""

    @property
    def fuzzy(self) -> bool:
        return "fuzzy" in self.flags

    @property
    def translated(self) -> bool:
        return bool(self.translations) and all(value != "" for _, value in self.translations)


@dataclass(frozen=True)
class CatalogOverview:
    locale: str
    total: int
    translated: int
    fuzzy: int
    empty: int
    damaged: int
    invalid_characters: int
    obsolete: int
    damage_details: tuple[tuple[str, str, str], ...]
    character_details: tuple[tuple[str, str, str], ...]


def run_command(
    args: Sequence[str | Path],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [str(arg) for arg in args]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise LocalizationError(f"Could not run required command {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise LocalizationError(f"Command failed ({' '.join(command)}):\n{detail}")
    return result


def require_gettext_tools() -> None:
    missing = [tool for tool in GETTEXT_TOOLS if shutil.which(tool) is None]
    if missing:
        raise LocalizationError("Missing GNU gettext tools: " + ", ".join(missing))


def tracked_source_files(repo_root: Path = REPO_ROOT) -> list[str]:
    result = run_command(["git", "ls-files", "-z", "--", "src"], cwd=repo_root)
    paths = result.stdout.split("\0")
    return sorted(path.replace("\\", "/") for path in paths if Path(path).suffix.lower() in SOURCE_SUFFIXES)


def source_list_text(repo_root: Path = REPO_ROOT) -> str:
    files = tracked_source_files(repo_root)
    if not files:
        raise LocalizationError("No tracked C/C++ source files were found below src/")
    return "\n".join(files) + "\n"


def po_unquote(value: str) -> str:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise LocalizationError(f"Invalid PO string literal: {value}") from exc
    if not isinstance(parsed, str):
        raise LocalizationError(f"Invalid PO string literal: {value}")
    return parsed


def parse_catalog_text(text: str) -> list[CatalogEntry]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized:
        return []
    blocks = re.split(r"\n[ \t]*\n", normalized)
    entries: list[CatalogEntry] = []
    directive_re = re.compile(r"^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(\".*\")$")

    for block in blocks:
        # PO syntax uses LF/CRLF line endings only. str.splitlines() also treats
        # C1 controls such as U+0085 as separators and can hide mojibake inside
        # a msgstr by turning it into an unparsed continuation fragment.
        lines = block.split("\n")
        obsolete = any(line.startswith("#~") for line in lines)
        fields: dict[str, str] = {}
        current: str | None = None
        flags: set[str] = set()
        for original_line in lines:
            if original_line.startswith("#,"):
                flags.update(flag.strip() for flag in original_line[2:].split(",") if flag.strip())
            if original_line.startswith("#~"):
                continue
            line = original_line.strip()
            match = directive_re.match(line)
            if match:
                current = match.group(1)
                fields[current] = po_unquote(match.group(3))
            elif current is not None and line.startswith('"'):
                fields[current] += po_unquote(line)

        if "msgid" not in fields:
            continue
        translations: list[tuple[int, str]] = []
        if "msgstr" in fields:
            translations.append((0, fields["msgstr"]))
        for name, value in fields.items():
            plural_match = re.fullmatch(r"msgstr\[(\d+)\]", name)
            if plural_match:
                translations.append((int(plural_match.group(1)), value))
        entries.append(
            CatalogEntry(
                block=block,
                msgctxt=fields.get("msgctxt", ""),
                msgid=fields["msgid"],
                msgid_plural=fields.get("msgid_plural", ""),
                translations=tuple(sorted(translations)),
                flags=frozenset(flags),
                obsolete=obsolete,
            )
        )
    return entries


def read_catalog(path: Path) -> list[CatalogEntry]:
    return parse_catalog_text(path.read_text(encoding="utf-8"))


def active_entries(entries: Iterable[CatalogEntry]) -> list[CatalogEntry]:
    return [entry for entry in entries if not entry.obsolete and not entry.is_header]


def catalog_keys(path: Path) -> set[tuple[str, str, str]]:
    return {entry.key for entry in active_entries(read_catalog(path))}


def validate_duplicate_translations(path: Path) -> None:
    seen: dict[tuple[str, str, str], tuple[tuple[int, str], ...]] = {}
    for entry in active_entries(read_catalog(path)):
        previous = seen.get(entry.key)
        if previous is not None and previous != entry.translations:
            raise LocalizationError(f"Conflicting duplicate translation in {path}: {entry.msgid!r}")
        seen[entry.key] = entry.translations


def normalize_pot_header(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(
        r'^"POT-Creation-Date: .*?\\n"$',
        lambda _match: '"POT-Creation-Date: \\n"',
        text,
        flags=re.MULTILINE,
    )


def po_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def hint_entries_text(path: Path = HINTS_PATH) -> str:
    entries: list[tuple[int, str, str]] = []
    section = ""
    section_line = 0
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        section_match = re.fullmatch(r"\[(hint:[^]]+)]", stripped)
        if section_match:
            section = section_match.group(1)
            section_line = line_number
            continue
        if section and stripped.startswith("text") and "=" in stripped:
            name, value = stripped.split("=", 1)
            if name.strip() == "text":
                entries.append((section_line, section, value.strip().replace("\\n", "\n")))
                section = ""

    blocks = []
    for line_number, section_name, text in entries:
        blocks.append(
            f"#. Hint section: {section_name}\n"
            f"#: resources/data/hints.ini:{line_number}\n"
            f"msgid {po_quote(text)}\n"
            'msgstr ""'
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_pot(repo_root: Path, list_text: str, work_dir: Path) -> Path:
    list_file = work_dir / "list.txt"
    code_pot = work_dir / "code.pot"
    hints_pot = work_dir / "hints.pot"
    combined_pot = work_dir / "combined.pot"
    unique_pot = work_dir / "ApiumSlicer.pot"
    list_file.write_text(list_text, encoding="utf-8", newline="\n")
    hints_pot.write_text(
        hint_entries_text(repo_root / "resources" / "data" / "hints.ini"),
        encoding="utf-8",
        newline="\n",
    )

    run_command(
        [
            "xgettext",
            "--language=C++",
            "--keyword=_",
            "--keyword=L",
            "--keyword=_L",
            "--keyword=_u8L",
            "--keyword=L_CONTEXT:1,2c",
            "--keyword=_L_PLURAL:1,2",
            "--add-comments=TRN",
            "--from-code=UTF-8",
            "--debug",
            "--boost",
            f"--width={WIDTH}",
            "--package-name=ApiumSlicer",
            "--force-po",
            "--files-from",
            list_file,
            "--output",
            code_pot,
        ],
        cwd=repo_root,
    )
    run_command(["msgcat", f"--width={WIDTH}", "-o", combined_pot, code_pot, hints_pot])
    run_command(["msguniq", "--use-first", f"--width={WIDTH}", "-o", unique_pot, combined_pot])
    unique_pot.write_text(
        normalize_pot_header(unique_pot.read_text(encoding="utf-8")), encoding="utf-8", newline="\n"
    )
    validate_no_duplicate_keys(unique_pot)
    return unique_pot


def validate_no_duplicate_keys(path: Path) -> None:
    seen: set[tuple[str, str, str]] = set()
    for entry in active_entries(read_catalog(path)):
        if entry.key in seen:
            raise LocalizationError(f"Duplicate catalog key in {path}: {entry.msgid!r}")
        seen.add(entry.key)


def reorder_catalog(path: Path) -> None:
    entries = parse_catalog_text(path.read_text(encoding="utf-8"))
    headers = [entry for entry in entries if entry.is_header]
    if len(headers) != 1:
        raise LocalizationError(f"Expected exactly one PO header in {path}, found {len(headers)}")
    if any(entry.obsolete for entry in entries):
        raise LocalizationError(f"Obsolete entries remain in {path}")
    translated = [entry for entry in entries if not entry.is_header and not entry.fuzzy and entry.translated]
    fuzzy = [entry for entry in entries if not entry.is_header and entry.fuzzy]
    untranslated = [entry for entry in entries if not entry.is_header and not entry.fuzzy and not entry.translated]
    ordered = headers + translated + fuzzy + untranslated
    path.write_text("\n\n".join(entry.block for entry in ordered) + "\n", encoding="utf-8", newline="\n")


def apply_direct_translations(
    path: Path,
    translations: dict[tuple[str, str, str], str],
    *,
    require_all_untranslated: bool = False,
) -> None:
    """Fill non-fuzzy empty singular entries without an intermediate catalog."""
    entries = parse_catalog_text(path.read_text(encoding="utf-8"))
    open_entries = {
        entry.key: entry
        for entry in active_entries(entries)
        if not entry.fuzzy and not entry.translated and not entry.msgid_plural
    }
    unknown = set(translations) - set(open_entries)
    if unknown:
        _, msgid, _ = sorted(unknown)[0]
        raise LocalizationError(f"Translation target is not an empty singular entry in {path}: {msgid!r}")
    if require_all_untranslated and set(translations) != set(open_entries):
        missing = set(open_entries) - set(translations)
        _, msgid, _ = sorted(missing)[0]
        raise LocalizationError(f"Missing direct translation for {msgid!r} in {path}")

    rendered: list[str] = []
    for entry in entries:
        translation = translations.get(entry.key)
        if translation is None:
            rendered.append(entry.block)
            continue
        match = re.search(r"^msgstr(?:\[\d+\])?\s+\"", entry.block, flags=re.MULTILINE)
        if match is None:
            raise LocalizationError(f"Could not locate msgstr for {entry.msgid!r} in {path}")
        rendered.append(entry.block[: match.start()].rstrip() + "\nmsgstr " + po_quote(translation))

    content = ("\n\n".join(rendered) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="apiumslicer-direct-translation-") as temp_name:
        candidate = Path(temp_name) / path.name
        candidate.write_bytes(content)
        validate_translation_structure(candidate)
        validate_with_msgfmt(candidate)
    atomic_replace(path, content)


def apply_reviewed_fuzzy_translations(
    path: Path,
    translations: dict[tuple[str, str, str], dict[int, str]],
    *,
    require_all_fuzzy: bool = False,
    allow_non_fuzzy: bool = False,
) -> None:
    """Replace reviewed translations and remove fuzzy flags where present."""
    entries = parse_catalog_text(path.read_text(encoding="utf-8"))
    target_entries = {
        entry.key: entry
        for entry in active_entries(entries)
        if allow_non_fuzzy or entry.fuzzy
    }
    fuzzy_entries = {entry.key: entry for entry in active_entries(entries) if entry.fuzzy}
    unknown = set(translations) - set(target_entries)
    if unknown:
        _, msgid, _ = sorted(unknown)[0]
        raise LocalizationError(f"Translation target is not fuzzy in {path}: {msgid!r}")
    if require_all_fuzzy and set(translations) != set(fuzzy_entries):
        missing = set(fuzzy_entries) - set(translations)
        _, msgid, _ = sorted(missing)[0]
        raise LocalizationError(f"Missing reviewed fuzzy translation for {msgid!r} in {path}")

    rendered: list[str] = []
    for entry in entries:
        replacement = translations.get(entry.key)
        if replacement is None:
            rendered.append(entry.block)
            continue
        expected_indices = {index for index, _ in entry.translations}
        if not expected_indices:
            expected_indices = {0, 1} if entry.msgid_plural else {0}
        if set(replacement) != expected_indices:
            raise LocalizationError(
                f"Expected translation forms {sorted(expected_indices)} for {entry.msgid!r}, "
                f"got {sorted(replacement)}"
            )
        match = re.search(r"^msgstr(?:\[\d+\])?\s+\"", entry.block, flags=re.MULTILINE)
        if match is None:
            raise LocalizationError(f"Could not locate msgstr for {entry.msgid!r} in {path}")
        prefix = entry.block[: match.start()].rstrip()
        if entry.fuzzy:
            flag_match = re.search(r"^#,\s*(.+)$", prefix, flags=re.MULTILINE)
            if flag_match is None:
                raise LocalizationError(f"Fuzzy entry has no flag line for {entry.msgid!r} in {path}")
            flags = [flag.strip() for flag in flag_match.group(1).split(",") if flag.strip() != "fuzzy"]
            if flags:
                prefix = prefix[: flag_match.start()] + "#, " + ", ".join(flags) + prefix[flag_match.end() :]
            else:
                start = flag_match.start()
                end = flag_match.end()
                if end < len(prefix) and prefix[end] == "\n":
                    end += 1
                prefix = prefix[:start] + prefix[end:]
        if entry.msgid_plural:
            message_lines = [
                f"msgstr[{index}] " + po_quote(replacement[index])
                for index in sorted(replacement)
            ]
        else:
            message_lines = ["msgstr " + po_quote(replacement[0])]
        rendered.append(prefix.rstrip() + "\n" + "\n".join(message_lines))

    content = ("\n\n".join(rendered) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="apiumslicer-fuzzy-review-") as temp_name:
        candidate = Path(temp_name) / path.name
        candidate.write_bytes(content)
        reorder_catalog(candidate)
        validate_order(read_catalog(candidate), candidate)
        validate_translation_structure(candidate)
        validate_with_msgfmt(candidate)
        content = candidate.read_bytes()
    atomic_replace(path, content)


def write_source_language_catalog(input_path: Path, output_path: Path) -> None:
    """Write an English catalog whose translations exactly match its msgids."""
    rendered: list[str] = []
    for entry in parse_catalog_text(input_path.read_text(encoding="utf-8")):
        if entry.is_header or entry.obsolete:
            rendered.append(entry.block)
            continue
        match = re.search(r"^msgstr(?:\[\d+\])?\s+\"", entry.block, flags=re.MULTILINE)
        if match is None:
            raise LocalizationError(f"Could not locate msgstr for {entry.msgid!r} in {input_path}")
        prefix = entry.block[: match.start()].rstrip()
        if entry.msgid_plural:
            indices = [index for index, _ in entry.translations] or [0, 1]
            translations = [
                f"msgstr[{index}] " + po_quote(entry.msgid if index == 0 else entry.msgid_plural)
                for index in indices
            ]
        else:
            translations = ["msgstr " + po_quote(entry.msgid)]
        rendered.append(prefix + "\n" + "\n".join(translations))
    output_path.write_text(
        "\n\n".join(rendered) + "\n", encoding="utf-8", newline="\n"
    )


def validate_order(entries: Iterable[CatalogEntry], path: Path) -> None:
    previous = 0
    for entry in entries:
        if entry.obsolete or entry.is_header:
            continue
        group = 1 if not entry.fuzzy and entry.translated else 2 if entry.fuzzy else 3
        if group < previous:
            raise LocalizationError(
                f"Invalid PO order in {path}: translated entries must precede fuzzy and empty entries"
            )
        previous = group


BOOST_TOKEN_RE = re.compile(r"%\d+%")
BRACE_TOKEN_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_.:-]*\}(?!\})")
SLICER_TOKEN_RE = re.compile(r"\[[a-z_][a-z0-9_]*(?:\[[^\]\n]+\])?\]")
HTML_TOKEN_RE = re.compile(
    r"<\s*(/?)\s*(a|b|br|em|i|li|ol|p|span|strong|ul)\b[^>]*>", re.IGNORECASE
)
PRINTF_TOKEN_RE = re.compile(
    r"%(?:\d+\$)?[-+#0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcsp](?![a-z])"
)
MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "ðŸ", "ï¿½")


def structural_signature(
    value: str,
) -> tuple[Counter[str], Counter[str], Counter[str], Counter[str], Counter[str]]:
    boost_tokens = Counter(BOOST_TOKEN_RE.findall(value))
    html_tokens = Counter(
        ("/" if closing else "") + name.lower() for closing, name in HTML_TOKEN_RE.findall(value)
    )
    return (
        boost_tokens,
        Counter(),
        Counter(BRACE_TOKEN_RE.findall(value)),
        Counter(SLICER_TOKEN_RE.findall(value)),
        html_tokens,
    )


def printf_signature(value: str) -> Counter[str]:
    """Return conservative printf tokens without treating prose percentages as formats."""
    without_custom_macros = re.sub(r"%[A-Za-z_][A-Za-z0-9_]*%", "", value)
    return Counter(PRINTF_TOKEN_RE.findall(without_custom_macros))


def invalid_character_labels(value: str) -> tuple[str, ...]:
    """Describe invalid Unicode and common UTF-8/Windows mojibake markers."""
    labels: set[str] = set()
    for character in value:
        codepoint = ord(character)
        if character == "\ufffd":
            labels.add("Unicode replacement character U+FFFD")
        elif codepoint == 0 or (
            (codepoint < 32 or 0x7F <= codepoint <= 0x9F)
            and character not in "\t\n\r"
        ):
            labels.add(f"control character U+{codepoint:04X}")
        elif 0xD800 <= codepoint <= 0xDFFF:
            labels.add(f"unpaired surrogate U+{codepoint:04X}")
        elif 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFF in (0xFFFE, 0xFFFF):
            labels.add(f"Unicode noncharacter U+{codepoint:04X}")
    for marker in MOJIBAKE_MARKERS:
        if marker in value:
            labels.add("suspected UTF-8 mojibake")
    return tuple(sorted(labels))


def entry_reference(entry: CatalogEntry) -> str:
    match = re.search(r"^#:\s*(.+)$", entry.block, flags=re.MULTILINE)
    return match.group(1).split()[0] if match else "(no source reference)"


def entry_damage_reasons(entry: CatalogEntry) -> tuple[str, ...]:
    reasons: set[str] = set()
    for index, translation in entry.translations:
        if not translation:
            continue
        source = entry.msgid if index == 0 or not entry.msgid_plural else entry.msgid_plural
        if structural_signature(source) != structural_signature(translation):
            reasons.add("placeholder or HTML structure mismatch")
        if printf_signature(source) != printf_signature(translation):
            reasons.add("printf placeholder mismatch")
        if source.count("\n\n") != translation.count("\n\n"):
            reasons.add("paragraph break mismatch")
    return tuple(sorted(reasons))


def catalog_overview(path: Path) -> CatalogOverview:
    # Replacement decoding keeps overview usable even when a catalog contains
    # invalid UTF-8; the affected entry is then reported as an invalid character.
    text = path.read_bytes().decode("utf-8", errors="replace")
    entries = parse_catalog_text(text)
    active = [entry for entry in entries if not entry.obsolete and not entry.is_header]
    obsolete = sum(entry.obsolete for entry in entries)
    key_counts = Counter(entry.key for entry in active)
    damage_details: list[tuple[str, str, str]] = []
    character_details: list[tuple[str, str, str]] = []
    damaged_indices: set[int] = set()
    invalid_indices: set[int] = set()
    for index, entry in enumerate(active):
        reasons = list(entry_damage_reasons(entry))
        if key_counts[entry.key] > 1:
            reasons.append("duplicate catalog key")
        if reasons:
            damaged_indices.add(index)
            damage_details.append((entry_reference(entry), entry.msgid, ", ".join(sorted(reasons))))
        labels: set[str] = set()
        for value in (entry.msgctxt, entry.msgid, entry.msgid_plural):
            labels.update(invalid_character_labels(value))
        for _, translation in entry.translations:
            labels.update(invalid_character_labels(translation))
        if labels:
            invalid_indices.add(index)
            character_details.append((entry_reference(entry), entry.msgid, ", ".join(sorted(labels))))
    return CatalogOverview(
        locale=path.parent.name,
        total=len(active),
        translated=sum(entry.translated and not entry.fuzzy for entry in active),
        fuzzy=sum(entry.fuzzy for entry in active),
        empty=sum(not entry.fuzzy and not entry.translated for entry in active),
        damaged=len(damaged_indices),
        invalid_characters=len(invalid_indices),
        obsolete=obsolete,
        damage_details=tuple(damage_details),
        character_details=tuple(character_details),
    )
def validate_translation_structure(path: Path) -> None:
    errors: list[str] = []
    for entry in active_entries(read_catalog(path)):
        if entry.fuzzy or not entry.translated:
            continue
        for index, translation in entry.translations:
            source = entry.msgid if index == 0 or not entry.msgid_plural else entry.msgid_plural
            if structural_signature(source) != structural_signature(translation):
                errors.append(f"{entry.msgid!r} (msgstr[{index}])")
                if len(errors) == 10:
                    break
        if len(errors) == 10:
            break
    if errors:
        raise LocalizationError(
            f"Placeholder, markup, or newline mismatch in {path}:\n  " + "\n  ".join(errors)
        )


def validate_with_msgfmt(path: Path, output: Path | None = None) -> None:
    target = output if output is not None else os.devnull
    run_command(["msgfmt", "--check", "--check-format", "-o", target, path])


def po_files(localization_dir: Path = SCRIPT_DIR) -> list[Path]:
    return sorted(localization_dir.glob("*/ApiumSlicer_*.po"))


def sync_one_catalog(po_path: Path, pot_path: Path, work_dir: Path, localization_dir: Path) -> Path:
    validate_duplicate_translations(po_path)
    locale = po_path.parent.name
    wx_path = localization_dir / "wx_locale" / f"{locale}.po"
    if not wx_path.exists():
        raise LocalizationError(f"Missing wxWidgets catalog for {locale}: {wx_path}")

    unique = work_dir / f"{locale}-unique.po"
    wx_active = work_dir / f"{locale}-wx-active.po"
    template = work_dir / f"{locale}-template.po"
    merged = work_dir / f"{locale}-merged.po"
    active = work_dir / f"{locale}-active.po"
    combined = work_dir / f"{locale}-combined.po"
    deduplicated = work_dir / f"{locale}-deduplicated.po"
    english = work_dir / f"{locale}-english.po"
    english_clean = work_dir / f"{locale}-english-clean.po"
    result = work_dir / f"{locale}-result.po"
    run_command(["msguniq", "--use-first", f"--width={WIDTH}", "-o", unique, po_path])
    validate_with_msgfmt(unique)
    # Obsolete wxWidgets entries must be removed before concatenation. If an
    # obsolete wx entry shares a key with an active application entry,
    # msguniq may otherwise retain the obsolete state for the combined entry.
    run_command(["msgattrib", "--no-obsolete", f"--width={WIDTH}", "-o", wx_active, wx_path])
    # Merge against the union of application and wx keys. This keeps existing
    # application-specific translations for wx-only messages active, while the
    # following msgcat fills genuinely new or empty entries from wx.
    run_command(["msgcat", "--use-first", f"--width={WIDTH}", "-o", template, pot_path, wx_active])
    run_command(["msgmerge", f"--width={WIDTH}", "-o", merged, unique, template])
    run_command(["msgattrib", "--no-obsolete", f"--width={WIDTH}", "-o", active, merged])
    run_command(["msgcat", "--use-first", f"--width={WIDTH}", "-o", combined, active, wx_active])
    run_command(["msguniq", "--use-first", f"--width={WIDTH}", "-o", deduplicated, combined])
    normalized_input = deduplicated
    if locale == "en":
        # English is the source language. Keep its catalog complete and exact,
        # including plural forms, instead of maintaining translated copies of
        # the source strings by hand. Fuzzy flags are not meaningful here and
        # would make msgfmt omit otherwise valid source-language messages.
        write_source_language_catalog(deduplicated, english)
        run_command(
            ["msgattrib", "--clear-fuzzy", f"--width={WIDTH}", "-o", english_clean, english]
        )
        normalized_input = english_clean
    run_command(["msgattrib", "--no-obsolete", f"--width={WIDTH}", "-o", result, normalized_input])
    reorder_catalog(result)
    validate_no_duplicate_keys(result)
    validate_order(read_catalog(result), result)
    validate_translation_structure(result)
    validate_with_msgfmt(result)
    return result


def build_outputs(
    repo_root: Path, localization_dir: Path, *, use_existing_pot: bool = False
) -> dict[Path, bytes]:
    require_gettext_tools()
    outputs: dict[Path, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="apiumslicer-l10n-") as temp_name:
        work_dir = Path(temp_name)
        list_text = source_list_text(repo_root)
        outputs[localization_dir / "list.txt"] = list_text.encode("utf-8")
        if use_existing_pot:
            pot_path = localization_dir / "ApiumSlicer.pot"
            validate_no_duplicate_keys(pot_path)
        else:
            pot_path = generate_pot(repo_root, list_text, work_dir)
            outputs[localization_dir / "ApiumSlicer.pot"] = pot_path.read_bytes()

        result_paths: list[Path] = []
        for po_path in po_files(localization_dir):
            result = sync_one_catalog(po_path, pot_path, work_dir, localization_dir)
            result_paths.append(result)
            outputs[po_path] = result.read_bytes()
        validate_catalog_paths(pot_path, result_paths, localization_dir / "wx_locale")
    return outputs


def build_extraction_outputs(repo_root: Path, localization_dir: Path) -> dict[Path, bytes]:
    require_gettext_tools()
    list_text = source_list_text(repo_root)
    with tempfile.TemporaryDirectory(prefix="apiumslicer-pot-") as temp_name:
        pot_path = generate_pot(repo_root, list_text, Path(temp_name))
        return {
            localization_dir / "list.txt": list_text.encode("utf-8"),
            localization_dir / "ApiumSlicer.pot": pot_path.read_bytes(),
        }


def atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temp_path.chmod(path.stat().st_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def apply_outputs(outputs: dict[Path, bytes]) -> None:
    for path, content in outputs.items():
        atomic_replace(path, content)
        print(f"Updated {path.relative_to(REPO_ROOT).as_posix()}")


def validate_catalog_paths(pot_path: Path, catalogs: Iterable[Path], wx_dir: Path) -> None:
    pot_keys = catalog_keys(pot_path)
    for po_path in catalogs:
        entries = read_catalog(po_path)
        validate_no_duplicate_keys(po_path)
        validate_order(entries, po_path)
        validate_translation_structure(po_path)
        validate_with_msgfmt(po_path)
        if any(entry.obsolete for entry in entries):
            raise LocalizationError(f"Obsolete entries remain in {po_path}")
        locale_match = re.match(r"([A-Za-z_]+)(?:-|$)", po_path.stem)
        locale = po_path.parent.name if po_path.name.startswith("ApiumSlicer_") else ""
        if not locale and locale_match:
            locale = locale_match.group(1)
        wx_path = wx_dir / f"{locale}.po"
        allowed = pot_keys | catalog_keys(wx_path)
        actual = {entry.key for entry in active_entries(entries)}
        missing = pot_keys - actual
        extra = actual - allowed
        if missing:
            raise LocalizationError(f"{po_path} is missing {len(missing)} POT entries")
        if extra:
            raise LocalizationError(
                f"{po_path} contains {len(extra)} entries not present in POT or wx catalog"
            )


def validate_catalog_set(pot_path: Path, localization_dir: Path) -> None:
    validate_catalog_paths(pot_path, po_files(localization_dir), localization_dir / "wx_locale")


def compile_catalogs(localization_dir: Path = SCRIPT_DIR) -> None:
    require_gettext_tools()
    staged: list[tuple[Path, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="apiumslicer-mo-") as temp_name:
        work_dir = Path(temp_name)
        for po_path in po_files(localization_dir):
            output = work_dir / f"{po_path.parent.name}-ApiumSlicer.mo"
            validate_with_msgfmt(po_path, output)
            staged.append((po_path.parent / "ApiumSlicer.mo", output.read_bytes()))
    for path, content in staged:
        atomic_replace(path, content)
        print(f"Compiled {path.relative_to(REPO_ROOT).as_posix()}")


def strip_cpp_comments(text: str) -> str:
    result = list(text)
    index = 0
    in_string = False
    quote = ""
    while index < len(result):
        char = result[index]
        next_char = result[index + 1] if index + 1 < len(result) else ""
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                in_string = False
            index += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
            index += 1
            continue
        if char == "/" and next_char == "/":
            end = text.find("\n", index)
            end = len(result) if end == -1 else end
            for pos in range(index, end):
                if result[pos] != "\n":
                    result[pos] = " "
            index = end
            continue
        if char == "/" and next_char == "*":
            end = text.find("*/", index + 2)
            end = len(result) - 2 if end == -1 else end
            for pos in range(index, min(end + 2, len(result))):
                if result[pos] != "\n":
                    result[pos] = " "
            index = end + 2
            continue
        index += 1
    return "".join(result)


AUDIT_PATTERNS = (
    re.compile(
        r"\b(?P<sink>SetLabel|SetTitle|SetToolTip|wxMessageBox)\s*\(\s*"
        r"(?P<literal>\"(?:\\.|[^\"\\])*\")",
        re.DOTALL,
    ),
    re.compile(
        r"\b(?P<sink>wxStaticText|wxButton|wxCheckBox|wxRadioButton)\s*\("
        r"(?:[^,]|,(?!\s*(?:wxID_[A-Za-z0-9_]+|-?\d+)\s*,))*?,\s*"
        r"(?:wxID_[A-Za-z0-9_]+|-?\d+)\s*,\s*(?P<literal>\"(?:\\.|[^\"\\])*\")",
        re.DOTALL,
    ),
    re.compile(
        r"\b(?P<sink>append_menu_item|append_menu_check_item|append_menu_radio_item|Append)\s*\("
        r"\s*[^,;]+,\s*(?:[^,;]+,\s*)?(?P<literal>\"(?:\\.|[^\"\\])*\")",
        re.DOTALL,
    ),
    re.compile(
        r"\b(?P<sink>wxDialog|wxMessageDialog|wxMenuItem)\s*\("
        r"\s*[^,;]+,\s*[^,;]+,\s*(?P<literal>\"(?:\\.|[^\"\\])*\")",
        re.DOTALL,
    ),
)


def load_audit_allowlist(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed = set()
    for item in data:
        if not all(key in item for key in ("path", "sink", "literal", "reason")):
            raise LocalizationError(f"Invalid audit allowlist entry in {path}")
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise LocalizationError(f"Audit allowlist entries require a non-empty reason in {path}")
        allowed.add((item["path"], item["sink"], item["literal"]))
    return allowed


def is_probably_user_visible(value: str) -> bool:
    if not re.search(r"[A-Za-z]", value) or len(value) < 2:
        return False
    if any(marker in value for marker in ("_L(", "_u8L(", "L_CONTEXT(", "_L_PLURAL(")):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:/\\-]+", value) and (
        "://" in value or value.startswith((".", "/", "\\")) or value.count(".") >= 1
    ):
        return False
    return True


def audit_candidates(
    repo_root: Path = REPO_ROOT, allowlist_path: Path = AUDIT_ALLOWLIST_PATH
) -> list[tuple[str, int, str, str]]:
    allowed = load_audit_allowlist(allowlist_path)
    candidates: set[tuple[str, int, str, str]] = set()
    for relative in tracked_source_files(repo_root):
        path = repo_root / relative
        text = strip_cpp_comments(path.read_text(encoding="utf-8", errors="replace"))
        for pattern in AUDIT_PATTERNS:
            for match in pattern.finditer(text):
                literal = po_unquote(match.group("literal"))
                sink = match.group("sink")
                key = (relative, sink, literal)
                if key in allowed or not is_probably_user_visible(literal):
                    continue
                line = text.count("\n", 0, match.start("literal")) + 1
                candidates.add((relative, line, sink, literal.replace("\n", "\\n")))
    return sorted(candidates)


def run_audit(repo_root: Path = REPO_ROOT) -> int:
    candidates = audit_candidates(repo_root)
    for path, line, sink, literal in candidates:
        print(f"{path}:{line}: [{sink}] {literal}")
    print(f"Audit candidates: {len(candidates)} (informational only)")
    return 0


def command_overview(show_details: bool = False) -> int:
    pot_entries = active_entries(read_catalog(POT_PATH))
    overviews = [catalog_overview(path) for path in po_files(SCRIPT_DIR)]
    totals = CatalogOverview(
        locale="ALL",
        total=sum(item.total for item in overviews),
        translated=sum(item.translated for item in overviews),
        fuzzy=sum(item.fuzzy for item in overviews),
        empty=sum(item.empty for item in overviews),
        damaged=sum(item.damaged for item in overviews),
        invalid_characters=sum(item.invalid_characters for item in overviews),
        obsolete=sum(item.obsolete for item in overviews),
        damage_details=(),
        character_details=(),
    )
    print("Localization overview")
    print(f"Project source messages (POT): {len(pot_entries)}")
    print(f"Languages: {len(overviews)}")
    print(f"Catalog entries across languages: {totals.total}")
    print()
    headings = ("Language", "Total", "Translated", "Fuzzy", "Empty", "Damaged", "Invalid chars", "Obsolete")
    rows = [
        (
            item.locale,
            str(item.total),
            str(item.translated),
            str(item.fuzzy),
            str(item.empty),
            str(item.damaged),
            str(item.invalid_characters),
            str(item.obsolete),
        )
        for item in [*overviews, totals]
    ]
    widths = [max(len(headings[index]), *(len(row[index]) for row in rows)) for index in range(len(headings))]
    print("  ".join(heading.ljust(widths[index]) for index, heading in enumerate(headings)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))

    if show_details:
        for item in overviews:
            if not item.damage_details and not item.character_details:
                continue
            print(f"\n{item.locale} details")
            for reference, msgid, reason in item.damage_details:
                literal = msgid.replace("\n", "\\n")
                print(f"  damaged: {reference}: {literal!r} ({reason})")
            for reference, msgid, reason in item.character_details:
                literal = msgid.replace("\n", "\\n")
                print(f"  invalid characters: {reference}: {literal!r} ({reason})")
    return 0


def command_extract() -> int:
    apply_outputs(build_extraction_outputs(REPO_ROOT, SCRIPT_DIR))
    return 0


def command_sync(use_existing_pot: bool) -> int:
    apply_outputs(build_outputs(REPO_ROOT, SCRIPT_DIR, use_existing_pot=use_existing_pot))
    return 0


def command_check() -> int:
    expected = build_outputs(REPO_ROOT, SCRIPT_DIR)
    stale = [path for path, content in expected.items() if not path.exists() or path.read_bytes() != content]
    if stale:
        details = "\n  ".join(path.relative_to(REPO_ROOT).as_posix() for path in stale)
        raise LocalizationError(
            f"Localization files are not synchronized; run localization.py sync:\n  {details}"
        )
    validate_catalog_set(POT_PATH, SCRIPT_DIR)
    print("Localization catalogs are synchronized and valid.")
    run_audit(REPO_ROOT)
    return 0


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("extract", help="Regenerate list.txt and ApiumSlicer.pot")
    sync_parser = subparsers.add_parser(
        "sync", help="Regenerate and synchronize all localization files"
    )
    sync_parser.add_argument(
        "--use-existing-pot",
        action="store_true",
        help="Merge PO files without regenerating list.txt and the POT",
    )
    subparsers.add_parser("check", help="Check catalogs without modifying repository files")
    subparsers.add_parser("audit", help="Report likely unmarked user-visible C++ strings")
    overview_parser = subparsers.add_parser(
        "overview", help="Show translation coverage and catalog health statistics"
    )
    overview_parser.add_argument(
        "--details",
        action="store_true",
        help="List entries counted as damaged or containing invalid characters",
    )
    subparsers.add_parser("compile", help="Validate PO files and atomically compile MO files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return command_extract()
        if args.command == "sync":
            return command_sync(args.use_existing_pot)
        if args.command == "check":
            return command_check()
        if args.command == "audit":
            return run_audit(REPO_ROOT)
        if args.command == "overview":
            return command_overview(args.details)
        if args.command == "compile":
            compile_catalogs(SCRIPT_DIR)
            return 0
    except LocalizationError as exc:
        print(f"localization error: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
