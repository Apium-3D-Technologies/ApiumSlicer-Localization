from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


LOCALIZATION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOCALIZATION_DIR))

import localization  # noqa: E402


PO_HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: test\\n"
"Language: {language}\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
'''


class SourceRootDiscoveryTests(unittest.TestCase):
    @staticmethod
    def make_source_checkout(path: Path) -> None:
        (path / "src").mkdir(parents=True)
        hints = path / "resources" / "data" / "hints.ini"
        hints.parent.mkdir(parents=True)
        hints.write_text("", encoding="utf-8")

    def test_discovers_source_checkout_from_submodule_superproject(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "ApiumSlicer"
            self.make_source_checkout(source_root)
            script_dir = source_root / "resources" / "localization"
            script_dir.mkdir()
            self.assertEqual(
                localization.discover_source_root(script_dir, source_root),
                source_root.resolve(),
            )

    def test_discovers_historical_embedded_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "ApiumSlicer"
            self.make_source_checkout(source_root)
            script_dir = source_root / "resources" / "localization"
            script_dir.mkdir()
            with mock.patch.object(localization, "git_superproject_root", return_value=None):
                self.assertEqual(localization.discover_source_root(script_dir), source_root.resolve())

    def test_discovers_source_checkout_next_to_standalone_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source_root = workspace / "ApiumSlicer"
            self.make_source_checkout(source_root)
            script_dir = workspace / "ApiumSlicer-Localization"
            script_dir.mkdir()
            with (
                mock.patch.object(localization, "git_superproject_root", return_value=None),
                mock.patch.object(localization, "git_root", return_value=script_dir),
            ):
                self.assertEqual(localization.discover_source_root(script_dir), source_root.resolve())


class CatalogParsingTests(unittest.TestCase):
    def test_reorders_translated_fuzzy_and_empty_entries(self):
        source = PO_HEADER.format(language="de") + '''
#: source.cpp:1
msgid "Empty"
msgstr ""

#: source.cpp:2
#, fuzzy
msgid "Draft"
msgstr "Entwurf"

#: source.cpp:3
msgid "Done"
msgstr "Fertig"
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.po"
            path.write_text(source, encoding="utf-8")
            localization.reorder_catalog(path)
            entries = localization.active_entries(localization.read_catalog(path))
            self.assertEqual([entry.msgid for entry in entries], ["Done", "Draft", "Empty"])
            localization.validate_order(entries, path)

    def test_conflicting_duplicate_translations_are_rejected(self):
        source = PO_HEADER.format(language="de") + '''
msgid "Same"
msgstr "Eins"

msgid "Same"
msgstr "Zwei"
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.po"
            path.write_text(source, encoding="utf-8")
            with self.assertRaises(localization.LocalizationError):
                localization.validate_duplicate_translations(path)

    def test_structure_preserves_boost_slicer_and_html_tokens(self):
        source = '%1% uses [filament_diameter_0] and <a>settings</a>'
        translation = '%1% nutzt [filament_diameter_0] und <a>Einstellungen</a>'
        self.assertEqual(
            localization.structural_signature(source),
            localization.structural_signature(translation),
        )
        self.assertNotEqual(
            localization.structural_signature(source),
            localization.structural_signature(translation.replace("</a>", "")),
        )

    def test_overview_counts_translation_states_and_health_problems(self):
        source = PO_HEADER.format(language="de") + '''
#: source.cpp:1
msgid "Done"
msgstr "Fertig"

#: source.cpp:2
#, fuzzy
msgid "Draft"
msgstr "Entwurf"

#: source.cpp:3
msgid "Empty"
msgstr ""

#: source.cpp:4
#, boost-format
msgid "Value %1%"
msgstr "Wert"

#: source.cpp:5
msgid "Â°"
msgstr "Â°"
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "de" / "test.po"
            path.parent.mkdir()
            path.write_text(source, encoding="utf-8")
            overview = localization.catalog_overview(path)
            self.assertEqual(overview.total, 5)
            self.assertEqual(overview.translated, 3)
            self.assertEqual(overview.fuzzy, 1)
            self.assertEqual(overview.empty, 1)
            self.assertEqual(overview.damaged, 1)
            self.assertEqual(overview.invalid_characters, 1)
            self.assertIn("source.cpp:4", overview.damage_details[0][0])
            self.assertIn("mojibake", overview.character_details[0][2])

    def test_overview_detects_c1_mojibake_inside_translation(self):
        source = PO_HEADER.format(language="zh_CN") + '''
#: source.cpp:1
msgid "Broken encoding"
msgstr "è\u0081ç\u0095"
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zh_CN" / "test.po"
            path.parent.mkdir()
            path.write_text(source, encoding="utf-8")
            overview = localization.catalog_overview(path)
            self.assertEqual(overview.translated, 1)
            self.assertEqual(overview.empty, 0)
            self.assertEqual(overview.invalid_characters, 1)
            self.assertIn("control character", overview.character_details[0][2])

    @unittest.skipUnless(shutil.which("msgfmt"), "gettext is required")
    def test_direct_translation_fills_empty_entries_without_a_patch_catalog(self):
        source = PO_HEADER.format(language="de") + '''
#: source.cpp:1
msgid "Open"
msgstr ""
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.po"
            path.write_text(source, encoding="utf-8")
            localization.apply_direct_translations(
                path,
                {("", "Open", ""): "Offen"},
                require_all_untranslated=True,
            )
            entry = localization.active_entries(localization.read_catalog(path))[0]
            self.assertEqual(dict(entry.translations)[0], "Offen")

    @unittest.skipUnless(shutil.which("msgfmt"), "gettext is required")
    def test_reviewed_fuzzy_translation_replaces_all_forms_and_clears_flag(self):
        source = PO_HEADER.format(language="de") + '''
#, fuzzy, c-format
msgid "%d file"
msgid_plural "%d files"
msgstr[0] "%d Datei alt"
msgstr[1] "%d Dateien alt"
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.po"
            path.write_text(source, encoding="utf-8")
            localization.apply_reviewed_fuzzy_translations(
                path,
                {
                    ("", "%d file", "%d files"): {
                        0: "%d Datei",
                        1: "%d Dateien",
                    }
                },
                require_all_fuzzy=True,
            )
            entry = localization.active_entries(localization.read_catalog(path))[0]
            self.assertFalse(entry.fuzzy)
            self.assertEqual(dict(entry.translations), {0: "%d Datei", 1: "%d Dateien"})


class ExtractionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("xgettext") and shutil.which("msgcat"), "gettext is required")
    def test_extracts_references_context_plural_and_hints_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "resources" / "data").mkdir(parents=True)
            (root / "src" / "first.cpp").write_text(
                '_L("Shared");\nL_CONTEXT("Open", "Verb");\n_L_PLURAL("%d file", "%d files", n);\n',
                encoding="utf-8",
            )
            (root / "src" / "second.cpp").write_text('_L("Shared");\n', encoding="utf-8")
            (root / "resources" / "data" / "hints.ini").write_text(
                "[hint:Shared]\ntext = Shared\n\n[hint:Markup]\ntext = Headline\\nBody <b>text</b>.\n",
                encoding="utf-8",
            )
            work = root / "work"
            work.mkdir()
            pot = localization.generate_pot(
                root,
                "src/first.cpp\nsrc/second.cpp\n",
                work,
            )
            entries = localization.active_entries(localization.read_catalog(pot))
            shared = [entry for entry in entries if entry.msgid == "Shared"]
            self.assertEqual(len(shared), 1)
            self.assertIn("src/first.cpp:1", shared[0].block)
            self.assertIn("src/second.cpp:1", shared[0].block)
            self.assertIn("resources/data/hints.ini:1", shared[0].block)
            self.assertTrue(any(entry.msgctxt == "Verb" and entry.msgid == "Open" for entry in entries))
            self.assertTrue(any(entry.msgid_plural == "%d files" for entry in entries))
            self.assertTrue(any(entry.msgid == "Headline\nBody <b>text</b>." for entry in entries))


class SynchronizationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("msgmerge") and shutil.which("msgfmt"), "gettext is required")
    def test_sync_makes_english_match_source_and_clears_fuzzy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            localization_dir = root / "localization"
            app_dir = localization_dir / "en"
            wx_dir = localization_dir / "wx_locale"
            work_dir = root / "work"
            app_dir.mkdir(parents=True)
            wx_dir.mkdir()
            work_dir.mkdir()
            pot = localization_dir / "ApiumSlicer.pot"
            pot.write_text(
                PO_HEADER.format(language="")
                + '''
msgid "Original"
msgstr ""

msgid "One file"
msgid_plural "Many files"
msgstr[0] ""
msgstr[1] ""
''',
                encoding="utf-8",
            )
            po = app_dir / "ApiumSlicer_en.po"
            po.write_text(
                PO_HEADER.format(language="en")
                + '''
#, fuzzy
msgid "Original"
msgstr "Stale guess"

msgid "One file"
msgid_plural "Many files"
msgstr[0] "Changed singular"
msgstr[1] "Changed plural"
''',
                encoding="utf-8",
            )
            (wx_dir / "en.po").write_text(
                PO_HEADER.format(language="en")
                + '''
msgid "Cancel"
msgstr "Cancel"
''',
                encoding="utf-8",
            )

            result = localization.sync_one_catalog(po, pot, work_dir, localization_dir)
            entries = localization.active_entries(localization.read_catalog(result))
            by_id = {entry.msgid: entry for entry in entries}
            self.assertEqual(dict(by_id["Original"].translations), {0: "Original"})
            self.assertFalse(by_id["Original"].fuzzy)
            self.assertEqual(
                dict(by_id["One file"].translations),
                {0: "One file", 1: "Many files"},
            )

    @unittest.skipUnless(shutil.which("msgmerge") and shutil.which("msgfmt"), "gettext is required")
    def test_sync_preserves_app_overrides_adds_wx_and_prunes_obsolete_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            localization_dir = root / "localization"
            app_dir = localization_dir / "de"
            wx_dir = localization_dir / "wx_locale"
            work_dir = root / "work"
            app_dir.mkdir(parents=True)
            wx_dir.mkdir()
            work_dir.mkdir()

            pot = localization_dir / "ApiumSlicer.pot"
            pot.write_text(
                PO_HEADER.format(language="")
                + '''
msgid "Required"
msgstr ""

msgid "New empty"
msgstr ""
''',
                encoding="utf-8",
            )
            po = app_dir / "ApiumSlicer_de.po"
            po.write_text(
                PO_HEADER.format(language="de")
                + '''
msgid "Required"
msgstr "Erforderlich"

msgid "Shared wx key"
msgstr "Apium override"

#, fuzzy
msgid "Draft"
msgstr "Entwurf"

#~ msgid "Removed"
#~ msgstr "Entfernt"
''',
                encoding="utf-8",
            )
            (wx_dir / "de.po").write_text(
                PO_HEADER.format(language="de")
                + '''
msgid "Shared wx key"
msgstr "wx translation"

msgid "Cancel"
msgstr "Abbrechen"

#~ msgid "Required"
#~ msgstr "Veraltet"
''',
                encoding="utf-8",
            )

            result = localization.sync_one_catalog(po, pot, work_dir, localization_dir)
            entries = localization.active_entries(localization.read_catalog(result))
            translations = {entry.msgid: dict(entry.translations).get(0, "") for entry in entries}
            self.assertEqual(translations["Required"], "Erforderlich")
            self.assertEqual(translations["Shared wx key"], "Apium override")
            self.assertEqual(translations["Cancel"], "Abbrechen")
            self.assertEqual(entries[-1].msgid, "New empty")
            self.assertFalse(any(entry.obsolete for entry in localization.read_catalog(result)))

    @unittest.skipUnless(shutil.which("msgfmt"), "gettext is required")
    def test_msgfmt_rejects_incompatible_c_format_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.po"
            path.write_text(
                PO_HEADER.format(language="de")
                + '''
#, c-format
msgid "Value: %s"
msgstr "Wert: %d"
''',
                encoding="utf-8",
            )
            with self.assertRaises(localization.LocalizationError):
                localization.validate_with_msgfmt(path)


class AuditTests(unittest.TestCase):
    def test_audit_reports_raw_labels_and_ignores_marked_and_allowlisted_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "src" / "gui.cpp"
            source_path.parent.mkdir()
            source_path.write_text(
                'label->SetLabel("Raw label");\n'
                'label->SetLabel(_L("Translated label"));\n'
                'append_menu_item(menu, wxID_ANY, "Raw menu label");\n'
                'wxMessageBox("Allowed label");\n',
                encoding="utf-8",
            )
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                '[{"path":"src/gui.cpp","sink":"wxMessageBox",'
                '"literal":"Allowed label","reason":"Fixture"}]',
                encoding="utf-8",
            )
            with mock.patch.object(localization, "tracked_source_files", return_value=["src/gui.cpp"]):
                candidates = localization.audit_candidates(root, allowlist)
            self.assertEqual(
                candidates,
                [
                    ("src/gui.cpp", 1, "SetLabel", "Raw label"),
                    ("src/gui.cpp", 3, "append_menu_item", "Raw menu label"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
