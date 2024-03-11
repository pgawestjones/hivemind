import os
import sys
if sys.platform == 'win32':
    import win32com.client
import threading
from datetime import datetime
from pathlib import Path
from shutil import copytree, copy2
from tempfile import TemporaryDirectory
from typing import Dict

import torch

from hivemind.moe.server.module_backend import ModuleBackend
from hivemind.utils.logging import get_logger

logger = get_logger(__name__)

  
def copy_tree(src: str, dst: str):
    if not os.path.exists(dst):
        os.makedirs(dst)
    for item in os.listdir(src):
        src_entry = os.path.join(src, item)
        dst_entry = os.path.join(dst, item)
        if os.path.isdir(src_entry):
            copy_tree(src_entry, dst_entry)
        else:
            copy2(src_entry, dst_entry)


class CheckpointSaver(threading.Thread):
    def __init__(self, module_backends: Dict[str, ModuleBackend], checkpoint_dir: Path, update_period: float):
        super().__init__()
        assert checkpoint_dir and checkpoint_dir.exists() and checkpoint_dir.is_dir()
        self.module_backends = module_backends
        self.update_period = update_period
        self.checkpoint_dir = checkpoint_dir
        self.stop = threading.Event()

        # create expert directories to ensure that the directory is writable and checkpoints can be loaded
        store_experts(self.module_backends, self.checkpoint_dir)

    def run(self) -> None:
        while not self.stop.wait(self.update_period):
            store_experts(self.module_backends, self.checkpoint_dir)


def store_experts(experts: Dict[str, ModuleBackend], checkpoint_dir: Path):
    logger.debug(f"Storing experts at {checkpoint_dir.absolute()}")
    assert checkpoint_dir and checkpoint_dir.exists() and checkpoint_dir.is_dir()
    timestamp = datetime.now().isoformat(sep="_")
      
    if sys.platform == "win32":
        timestamp = timestamp.replace(":", "-")
        for expert_name, expert_backend in experts.items():
            expert_dir = checkpoint_dir / expert_name
            expert_dir.mkdir(exist_ok=True)
            checkpoint_name = expert_dir / f"checkpoint_{timestamp}.pt"
            torch.save(expert_backend.state_dict(), checkpoint_name)

            shell = win32com.client.Dispatch("wscript.shell")
            shortcut = shell.CreateShortcut(os.path.join(expert_dir , "checkpoint_last.lnk"))
            shortcut.Targetpath = str(checkpoint_name)
            shortcut.WorkingDirectory = str(expert_dir)
            shortcut.save()
    else:
        with TemporaryDirectory() as tmpdirname:
            for expert_name, expert_backend in experts.items():
                expert_dir = Path(tmpdirname) / expert_name
                expert_dir.mkdir()
                checkpoint_name = expert_dir / f"checkpoint_{timestamp}.pt"
                torch.save(expert_backend.state_dict(), checkpoint_name)
                os.symlink(checkpoint_name, expert_dir / "checkpoint_last.pt")
            copy_tree(tmpdirname, str(checkpoint_dir))


def load_experts(experts: Dict[str, ModuleBackend], checkpoint_dir: Path):
    assert checkpoint_dir and checkpoint_dir.exists() and checkpoint_dir.is_dir()
    for expert_name, expert in experts.items():
        checkpoints_folder = checkpoint_dir / expert_name
        if sys.platform == "win32":
            latest_checkpoint_lnk = checkpoints_folder / "checkpoint_last.lnk"
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(latest_checkpoint_lnk))
            latest_checkpoint = Path(shortcut.Targetpath)
            print(f"### load_experts {latest_checkpoint}")
        else:
            latest_checkpoint = checkpoints_folder / "checkpoint_last.pt"

        if latest_checkpoint.exists():
            expert.load_state_dict(torch.load(latest_checkpoint))
        else:
            logger.warning(f"Failed to load checkpoint for expert {expert_name}")
