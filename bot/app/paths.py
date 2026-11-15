"""Bundle assets and writable macOS application data, isolated from source."""
from __future__ import annotations
import os,sys
from pathlib import Path

ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
BUNDLE=Path(getattr(sys,'_MEIPASS',ROOT))
ASSETS=BUNDLE/'assets'
DATA=Path(os.environ.get('ARONA_DATA_DIR',str(Path.home()/'Library/Application Support/WemacAuto/Arona'))).expanduser().resolve()
STICKER_DIR=DATA/'stickers'
LOGS=DATA/'logs'
CONFIG_FILE=DATA/'config.json'
PERSONAS_FILE=DATA/'personas.json'
STICKERS_FILE=DATA/'stickers.json'
DATABASE=DATA/'arona.db'
LOG_FILE=LOGS/'arona.log'
BACKUP_DIR=DATA/'backups'
SDK_ROOT=Path(os.environ.get('WEMAC_SDK_ROOT',str(ROOT.parent))).expanduser().resolve()
DEFAULT_NATIVE_PROFILE=(DATA/'native-profile-isolated.json' if (DATA/'native-profile-isolated.json').is_file()
                        else SDK_ROOT/'research/native-profile-isolated.json')


def ensure_dirs():
    import shutil
    for folder in (DATA,STICKER_DIR,LOGS,BACKUP_DIR):folder.mkdir(parents=True,exist_ok=True)
    try:DATA.chmod(0o700)
    except OSError:pass
    defaults=BUNDLE/'data/stickers'
    if defaults.is_dir():
        for source in defaults.glob('arona_official_*.png'):
            destination=STICKER_DIR/source.name
            if not destination.exists():shutil.copy2(source,destination)
