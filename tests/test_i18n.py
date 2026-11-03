import ast
import os
from pathlib import Path
import re
from string import Formatter
import unittest
from unittest.mock import patch

from manette import i18n, preferences


class TranslationTests(unittest.TestCase):
    def test_language_follows_preference_and_environment(self):
        with patch.object(preferences, 'load', return_value={'language': 'en'}), \
                patch.dict(os.environ, {'LANG': 'fr_FR.UTF-8'}, clear=True):
            self.assertEqual(i18n.language(), 'en')
        with patch.object(preferences, 'load', return_value={'language': 'system'}), \
                patch.dict(os.environ, {'LANG': 'fr_FR.UTF-8'}, clear=True):
            self.assertEqual(i18n.language(), 'fr')

    def test_both_languages_keep_dynamic_values_unchanged(self):
        template = 'Données de {value0}'
        with patch.object(i18n, 'language', return_value='en'):
            self.assertEqual(i18n._(template, value0='Supprimer'), 'Data for Supprimer')
            self.assertEqual(i18n._('processus', context='singular'), 'process')
            self.assertEqual(i18n.number('12.5%'), '12.5%')
        with patch.object(i18n, 'language', return_value='fr'):
            self.assertEqual(i18n._(template, value0='Supprimer'), 'Données de Supprimer')
            self.assertEqual(i18n.number('12.5%'), '12,5 %')

    def test_catalog_preserves_all_placeholders(self):
        fields = lambda text: sorted((field, spec, conversion) for _, field, spec, conversion in Formatter().parse(text) if field is not None)
        for original, translation in i18n.ENGLISH.items():
            original = original.split('\x04')[-1]
            with self.subTest(message=original):
                self.assertEqual(fields(original), fields(translation))

    def test_all_marked_messages_have_an_english_translation(self):
        for path in (Path(__file__).resolve().parent.parent / 'manette').glob('*.py'):
            if path.name == 'i18n.py':
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('_', 'tr'):
                    self.assertIsInstance(node.args[0], ast.Constant)
                    context = next((kw.value.value for kw in node.keywords if kw.arg == 'context'), None)
                    key = (context + '\x04' if context else '') + node.args[0].value
                    self.assertIn(key, i18n.ENGLISH, f'{path.name}:{node.lineno}')

    def test_french_interface_uses_no_familiar_address(self):
        for message in i18n.ENGLISH:
            self.assertIsNone(re.search(r'\b(tu|toi|ton|ta|tes|Tutoiement)\b', message, re.I), message)


if __name__ == '__main__':
    unittest.main()
