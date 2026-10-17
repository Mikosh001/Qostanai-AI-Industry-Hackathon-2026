"""Set isolated defaults before any backend module caches its configuration."""
import os
import tempfile
os.environ['SERGEK_DATA']=tempfile.mkdtemp(prefix='sergek-pytest-')
os.environ['SERGEK_DESKTOP_KEY']='test-desktop-key'
os.environ.pop('SERGEK_DEMO_CONFIG',None)
