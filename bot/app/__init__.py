"""ARONA — Blue Archive themed WeChat auto-reply assistant."""

import os

# python.org macOS builds may not have installed system certificate links.
# Keep verification enabled and use the packaged Mozilla trust store.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

__version__ = "1.3.3"
__app_name__ = "什亭之匣"
