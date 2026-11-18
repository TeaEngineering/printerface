# Locations and configuration shared by main, mailer and stationary.
#
# PRINTERFACE_HOME holds the stored jobs, rendered PDFs, email address book and email.cfg overrides.
# It defaults to ~/printerface; set the environment variable to run a second instance (for example a
# shadow instance on a copy of the data) without touching the live one.
import configparser
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser(os.environ.get('PRINTERFACE_HOME', '~/printerface'))

def load_config():
	config = configparser.ConfigParser()
	with open(os.path.join(BASE_DIR, 'defaults.cfg')) as f:
		config.read_file(f)
	config.read(os.path.join(HOME, 'email.cfg'))
	return config

config = load_config()
