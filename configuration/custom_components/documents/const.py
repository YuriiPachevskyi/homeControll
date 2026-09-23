"""Constants for the documents integration."""
from datetime import timedelta
from pathlib import PurePosixPath

DOMAIN = "documents"

# The one place synced PDFs live (outside www/, so HA never serves them
# unauthenticated). Keys are the URL segment: /api/documents/<kind>/<file>.
DOCUMENTS_ROOT = PurePosixPath("/config/statistics/documents")
KINDS = ("enera", "oselya")

# How long a signed link stays valid, and how often links are re-signed even
# when no file changed. The directories are rescanned every SCAN_INTERVAL.
LINK_EXPIRATION = timedelta(days=7)
RESIGN_AFTER = timedelta(days=1)
SCAN_INTERVAL = timedelta(hours=1)
