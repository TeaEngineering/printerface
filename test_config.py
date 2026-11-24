# The [Stationery] / [Printing] layout of email.cfg, and reading and rewriting the old [Printing] / [Robot] one.
import configparser
import importlib.util
import io
import os
import unittest

import settings

spec = importlib.util.spec_from_file_location('migrate_config', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'migrate_config.py'))
migrate_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_config)

OLD = """[Email]
to=me@example.com

# the company, as it appears on the paper
[Printing]
email=sales@example.com
address=A COMPANY\\nA STREET
; the terms, over two lines
terms=All goods sold in accordance
    with our Terms
logo=~/logo.jpg
result_count=50

[Robot]
# what is printed on arrival
auto_types=Delvnote,Invoice
auto_printer=DESK_LASER

[Gmail]
login_password=pass%%word
"""


def parse(text):
	c = configparser.RawConfigParser()
	c.read_string(text)
	return c


class TestMigrate(unittest.TestCase):
	def test_keys_move_to_the_sections_they_belong_in(self):
		new = parse(migrate_config.migrate(OLD))
		self.assertEqual(['Email', 'Stationery', 'Printing', 'Gmail'], new.sections())
		self.assertEqual(['email', 'address', 'terms', 'logo'], new.options('Stationery'))
		self.assertEqual(['auto_types', 'auto_printer', 'result_count'], new.options('Printing'))
		old = parse(OLD)
		self.assertEqual(old.get('Printing', 'terms'), new.get('Stationery', 'terms'))      # the continuation line came too
		self.assertEqual('DESK_LASER', new.get('Printing', 'auto_printer'))
		self.assertEqual('50', new.get('Printing', 'result_count'))
		self.assertEqual('pass%%word', new.get('Gmail', 'login_password'))

	def test_comments_travel_with_their_keys(self):
		text = migrate_config.migrate(OLD)
		self.assertIn('; the terms, over two lines\nterms=', text)
		self.assertIn('# what is printed on arrival\nauto_types=', text)

	def test_a_file_in_the_new_layout_is_left_alone(self):
		new = migrate_config.migrate(OLD)
		self.assertEqual(new, migrate_config.migrate(new))
		self.assertEqual('[Email]\nto=x\n', migrate_config.migrate('[Email]\nto=x\n'))

	def test_only_robot_or_only_printing(self):
		only_robot = parse(migrate_config.migrate('[Robot]\nauto_printer=X\n[Main]\ntz=UTC\n'))
		self.assertEqual({'auto_printer': 'X'}, dict(only_robot.items('Printing')))
		only_company = parse(migrate_config.migrate('[Printing]\nvatreg=GB1\n[Main]\ntz=UTC\n'))
		self.assertEqual({'vatreg': 'GB1'}, dict(only_company.items('Stationery')))
		self.assertFalse(only_company.has_section('Printing'))


class TestReadingTheOldLayout(unittest.TestCase):
	keys = {'email', 'address', 'terms', 'logo'}

	def test_translate(self):
		out, legacy = settings.translate(parse(OLD), self.keys)
		self.assertTrue(legacy)
		self.assertEqual('A COMPANY\\nA STREET', out.get('Stationery', 'address'))
		self.assertEqual({'auto_types': 'Delvnote,Invoice', 'auto_printer': 'DESK_LASER', 'result_count': '50'}, dict(out.items('Printing')))

	def test_the_new_layout_is_not_legacy(self):
		out, legacy = settings.translate(parse(migrate_config.migrate(OLD)), self.keys)
		self.assertFalse(legacy)

	def test_defaults_are_in_the_new_layout(self):
		defaults = settings.configparser.ConfigParser()
		with open(os.path.join(settings.BASE_DIR, 'defaults.cfg')) as f:
			defaults.read_file(f)
		self.assertIn('address', defaults.options('Stationery'))
		self.assertEqual({'auto_types', 'auto_printer', 'result_count'}, set(defaults.options('Printing')))
		self.assertFalse(defaults.has_section('Robot'))

	def test_loading_an_old_file_gives_the_new_sections_and_notes_what_was_set(self):
		import tempfile
		with tempfile.TemporaryDirectory() as home:
			with open(os.path.join(home, 'email.cfg'), 'w') as f:
				f.write(OLD.replace('pass%%word', 'password'))
			old_home, settings.HOME = settings.HOME, home
			self.addCleanup(setattr, settings, 'HOME', old_home)
			self.addCleanup(lambda: (settings.load_config(),))
			config = settings.load_config()
		self.assertEqual('DESK_LASER', config.get('Printing', 'auto_printer'))
		self.assertEqual('A COMPANY\\nA STREET', config.get('Stationery', 'address'))
		self.assertEqual('50', config.get('Printing', 'result_count'))
		self.assertIn(('Stationery', 'terms'), settings.overridden)
		self.assertIn(('Printing', 'auto_printer'), settings.overridden)
		self.assertNotIn(('Stationery', 'vatreg'), settings.overridden)


if __name__ == '__main__':
	unittest.main()
