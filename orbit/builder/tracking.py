import dataclasses
from pathlib import Path
import hashlib
import subprocess
from typing import Any, Union
import sys

from orbit import PROJ_ROOT

@dataclasses.dataclass
class GitInfo:
    branch: str
    commit: str
    last_tag: Union[str, None] = None
    patch_str: str = ""
    
    @classmethod
    def from_ws(cls, repo_root:str=PROJ_ROOT) -> tuple[str]:
        try:
            branch = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
                    cwd=repo_root, capture_output=True, text=True, check=True
                ).stdout.strip() 
            commit_hash = subprocess.run(
                    ["git", "rev-parse", "--short" ,"HEAD"],
                    cwd=repo_root, capture_output=True, text=True, check=True
                ).stdout.strip() 
        
            try:
                last_tag =subprocess.run(['git', 'describe', '--tags', '--abbrev=0'], 
                        cwd=repo_root, capture_output=True, text=True,  check=True
                    ).stdout.strip()        
            except:
                last_tag = None # current repo doesn't have any tag

            patch_str = subprocess.run(['git', 'diff'], 
                    cwd=repo_root, capture_output=True, text=True,  check=True
                ).stdout
            


            return cls(branch, commit_hash, last_tag, patch_str)
        
        except subprocess.CalledProcessError:
            print("Calling git failed!")
            sys.exit(1)
    
    def as_dict(self, skip_patch_str=False):
        data_dict = dataclasses.asdict(self)
        if skip_patch_str:
            data_dict.pop("patch_str")
        return data_dict

    def __str__(self):
        return f"{self.commit}" + ("+patch" if self.patch_str else "") + f"@{self.branch}"

    def __repr__(self):
        return f"GitInfo({str(self)})"





def create_patch_file( repo_root:Path, patch_file:Path ) -> str:
    try:
        with patch_file.open("w") as f:
            subprocess.run(
                        ["git", "diff" ], 
                        cwd=repo_root, stdout=f
            )
    except:
        print( "Error while trying to create patch file.")
        sys.exit(1)

    md5 = None
    with patch_file.open("rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
    
    return md5