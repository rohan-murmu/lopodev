"""Import first in tests that install or bootstrap: no downloads, no real user data.

Sets LOPODEV_NO_INTEGRATIONS=1 so `lopodev new/install` skip `setup`, and points
LOPODEV_DATA at a throwaway directory so the developer's knowledge store and
pinned integrations are never read or written. Subprocesses inherit both.
"""

import atexit
import os
import shutil
import tempfile

if "LOPODEV_TEST_DATA" not in os.environ:
    _data = tempfile.mkdtemp(prefix="lopodev-test-data-")
    atexit.register(shutil.rmtree, _data, ignore_errors=True)
    os.environ["LOPODEV_TEST_DATA"] = _data
    os.environ["LOPODEV_DATA"] = _data
    os.environ["LOPODEV_NO_INTEGRATIONS"] = "1"
