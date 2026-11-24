# Locations and configuration shared by main, mailer and stationery.
#
# PRINTERFACE_HOME holds the stored jobs, rendered PDFs, email address book and email.cfg overrides.
# It defaults to ~/printerface; set the environment variable to run a second instance (for example a
# shadow instance on a copy of the data) without touching the live one.
import configparser
import io
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser(os.environ.get('PRINTERFACE_HOME', '~/printerface'))

# [Stationery] is how documents are drawn (company details, logos), [Printing] is what is done with them once drawn
# (auto-print, the printed history). They used to be [Printing] and [Robot]; a file written for that is still read,
# the keys that were in [Printing] going to [Stationery] and those in [Robot] to [Printing]. tools/migrate_config.py
# rewrites a file to the new layout.

# the (section, key) pairs that email.cfg sets, for the settings pages to mark as changed from the defaults
overridden = set()

def translate(user, company_keys):
	"""(RawConfigParser in the current layout, whether it was in the old one) for a RawConfigParser read from email.cfg."""
	out = configparser.RawConfigParser()
	legacy = False
	for section in user.sections():
		for key, value in user.items(section):
			target = section
			if section == 'Robot':
				target, legacy = 'Printing', True
			elif section == 'Printing' and key in company_keys:
				target, legacy = 'Stationery', True
			if not out.has_section(target):
				out.add_section(target)
			out.set(target, key, value)
	return out, legacy

def load_config():
	config = configparser.ConfigParser()
	with open(os.path.join(BASE_DIR, 'defaults.cfg')) as f:
		config.read_file(f)
	user = configparser.RawConfigParser()
	user.read(os.path.join(HOME, 'email.cfg'))
	user, legacy = translate(user, set(config.options('Stationery')))
	if legacy:
		print('[config] %s/email.cfg uses the old [Printing] and [Robot] sections; read as [Stationery] and [Printing]. '
			'Run tools/migrate_config.py to update it' % HOME)
	buf = io.StringIO()
	user.write(buf)
	config.read_string(buf.getvalue())
	overridden.clear()
	overridden.update((section, key) for section in user.sections() for key in user.options(section))
	return config

config = load_config()
