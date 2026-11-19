# Runs the node tests for web/js/compose.js (skipped where node isn't installed, e.g. the docker image).
import os
import shutil
import subprocess
import unittest

@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class TestComposeJs(unittest.TestCase):
	def test_compose_js(self):
		here = os.path.dirname(os.path.abspath(__file__))
		r = subprocess.run(['node', 'test_compose.js'], cwd=here, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
		self.assertEqual(0, r.returncode, r.stdout)
		self.assertIn('all tests passed', r.stdout)

if __name__ == "__main__":
	unittest.main()
