from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).parent/"player-studio-v15/prepare_source.py"),run_name="__main__")
