"""Build the portable Windows application using task-local build dependencies."""
from pathlib import Path
import argparse
import os
import sys
import shutil

root = Path(__file__).absolute().parent
workspace = root.parent
parser=argparse.ArgumentParser()
parser.add_argument('--dist-dir',default=str(workspace/'球员工坊-V15'))
dist=Path(parser.parse_args().dist_dir).absolute()
deps = workspace / ".work" / "studio-build-deps"
if deps.exists():
    sys.path.insert(0, str(deps))
    os.environ["PYTHONPATH"] = str(deps) + os.pathsep + os.environ.get("PYTHONPATH", "")
native_deps=workspace/'.work/native-integration-deps'
if native_deps.exists():
    sys.path.insert(0,str(native_deps))
    os.environ['PYTHONPATH']=str(native_deps)+os.pathsep+os.environ.get('PYTHONPATH','')
os.environ["PYINSTALLER_CONFIG_DIR"] = str(workspace / ".work" / "pyinstaller-cache")
import PyInstaller.__main__

PyInstaller.__main__.run([
    str(root / "app.py"), "--onefile", "--windowed", "--noupx", "--noconfirm",
    "--name", "球员工坊", "--icon", str(root / "resources" / "app.ico"),
    "--distpath", str(dist),
    "--workpath", str(workspace / ".work" / "studio-build-v15"),
    "--specpath", str(workspace / ".work" / "studio-spec-v15"),
    "--paths", str(root),
    "--paths", str(native_deps),
    "--add-data", str(root / "web") + ":web",
    "--add-data", str(root / "resources") + ":resources",
    "--add-data", str(root / "personal_runtime.py") + ":.",
    "--add-data", str(root / "personal_binding.py") + ":.",
    "--exclude-module", "tkinter",
])
if (root / 'tools').is_dir():
    shutil.copytree(root / 'tools', dist / 'tools', dirs_exist_ok=True)
