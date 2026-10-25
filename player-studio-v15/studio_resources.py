"""Locate deployed assets independently of the Python importer's virtual path."""
from pathlib import Path
import sys


def bundled_resources():
    # PyInstaller and android_backend set _MEIPASS to the extracted asset bundle.
    # Chaquopy's __file__ points inside AssetFinder, which is not a real folder.
    bundle=getattr(sys,'_MEIPASS',None)
    return (Path(bundle) if bundle is not None else Path(__file__).resolve().parent)/'resources'
