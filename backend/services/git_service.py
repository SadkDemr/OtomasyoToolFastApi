"""
Git Service
-----------
Repository clone, branch, commit, push, pull işlemleri.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone


WORKSPACES_BASE = os.environ.get("WORKSPACES_BASE", "./workspaces")


class GitError(Exception):
    """Git işlem hatası"""
    pass


def get_default_branch(repo_url: str, username: Optional[str] = None, token: Optional[str] = None) -> str:
    """
    Repository'nin default branch'ini tespit et.
    
    Returns:
        Branch adı (main, master, develop, vb.)
        Boş repo ise "main" döner
    """
    # Credential injection
    auth_url = repo_url
    if username and token:
        if "@" in repo_url:
            parts = repo_url.split("@")
            auth_url = f"https://{username}:{token}@{parts[1]}"
        else:
            auth_url = repo_url.replace("https://", f"https://{username}:{token}@")
    
    # Remote branch'leri listele
    cmd = ["git", "ls-remote", "--symref", auth_url, "HEAD"]
    code, stdout, stderr = _run_git_command(cmd)
    
    if code == 0 and stdout.strip():
        # Output: ref: refs/heads/main	HEAD
        for line in stdout.split('\n'):
            if line.startswith('ref:'):
                branch = line.split('/')[-1].split('\t')[0].strip()
                if branch:
                    return branch
    
    # Fallback: tüm branch'leri listele
    cmd = ["git", "ls-remote", "--heads", auth_url]
    code, stdout, stderr = _run_git_command(cmd)
    
    if code == 0 and stdout.strip():
        # İlk branch'i al
        lines = [l.strip() for l in stdout.split('\n') if l.strip()]
        if lines:
            # Format: <hash>  refs/heads/main
            first_branch = lines[0].split('refs/heads/')[-1].strip()
            if first_branch:
                return first_branch
    
    # Boş repo - "main" kullan
    return "main"


def _ensure_workspaces_dir():
    Path(WORKSPACES_BASE).mkdir(parents=True, exist_ok=True)


def _run_git_command(cmd: list, cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """
    Git komutu çalıştır.
    Returns: (returncode, stdout, stderr)
    """
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60
    )
    return result.returncode, result.stdout, result.stderr


def clone_repository(
    repo_url: str,
    local_path: Path,
    branch: str = "main",
    username: Optional[str] = None,
    token: Optional[str] = None
) -> dict:
    """
    Repository'yi clone et.
    
    Args:
        repo_url: Git repo URL (https://...)
        local_path: Clone edileceği path
        branch: Ana branch (default: main) - otomatik tespit edilir
        username: Git username (optional)
        token: Git token (optional)
    
    Returns:
        {"success": bool, "branch": str, "is_empty": bool}
    
    Raises:
        GitError: Clone başarısız olursa
    """
    _ensure_workspaces_dir()
    
    # Önce default branch'i tespit et
    detected_branch = get_default_branch(repo_url, username, token)
    if detected_branch != branch:
        print(f"Branch auto-detected: {detected_branch} (requested: {branch})")
        branch = detected_branch
    
    # Credential injection (Azure Repos / GitHub için)
    auth_url = repo_url
    if username and token:
        # https://username:token@dev.azure.com/org/project/_git/repo
        if "@" in repo_url:
            # Zaten credential var, değiştir
            parts = repo_url.split("@")
            auth_url = f"https://{username}:{token}@{parts[1]}"
        else:
            # https:// ekle
            auth_url = repo_url.replace("https://", f"https://{username}:{token}@")
    
    # Önce branch'siz clone dene (boş repo için)
    cmd_no_branch = ["git", "clone", auth_url, str(local_path)]
    code, stdout, stderr = _run_git_command(cmd_no_branch)
    
    if code == 0:
        # Başarılı clone - boş mu kontrol et
        gitdir = local_path / ".git"
        if gitdir.exists():
            # Branch kontrol et
            cmd_check = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            code_check, stdout_check, _ = _run_git_command(cmd_check, cwd=local_path)
            
            current_branch = stdout_check.strip() if code_check == 0 else "main"
            
            # Boş repo mu?
            cmd_log = ["git", "log", "-1"]
            code_log, _, _ = _run_git_command(cmd_log, cwd=local_path)
            is_empty = (code_log != 0)
            
            if is_empty:
                # İlk commit'i at
                readme_file = local_path / "README.md"
                readme_file.write_text(f"# Test Automation Scenarios\n\nThis repository contains test scenarios.\n")
                
                cmd_add = ["git", "add", "README.md"]
                _run_git_command(cmd_add, cwd=local_path)
                
                cmd_commit = ["git", "commit", "-m", "Initial commit: Add README"]
                _run_git_command(cmd_commit, cwd=local_path)
                
                # Push ilk commit'i
                cmd_push = ["git", "push", "-u", "origin", current_branch or "main"]
                _run_git_command(cmd_push, cwd=local_path)
            
            return {
                "success": True,
                "branch": current_branch or branch,
                "is_empty": is_empty
            }
    
    # Branch'li clone dene
    cmd = ["git", "clone", "-b", branch, auth_url, str(local_path)]
    code, stdout, stderr = _run_git_command(cmd)
    
    if code != 0:
        raise GitError(f"Clone failed: {stderr}")
    
    return {
        "success": True,
        "branch": branch,
        "is_empty": False
    }


def create_user_branch(local_path: Path, branch_name: str) -> bool:
    """
    Kullanıcı branch'i oluştur ve checkout yap.
    
    Args:
        local_path: Repo path
        branch_name: Branch adı (user-{username})
    
    Returns:
        True if success
    """
    # Branch oluştur
    cmd = ["git", "checkout", "-b", branch_name]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        # Branch zaten varsa checkout yap
        cmd = ["git", "checkout", branch_name]
        code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
        
        if code != 0:
            raise GitError(f"Branch creation failed: {stderr}")
    
    return True


def get_status(local_path: Path) -> dict:
    """
    Git status al.
    
    Returns:
        {
            "has_changes": bool,
            "changed_files": list[str],
            "untracked_files": list[str]
        }
    """
    cmd = ["git", "status", "--porcelain"]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        raise GitError(f"Status check failed: {stderr}")
    
    lines = [line.strip() for line in stdout.split("\n") if line.strip()]
    
    changed = []
    untracked = []
    
    for line in lines:
        status = line[:2]
        file = line[3:]
        
        if status.startswith("??"):
            untracked.append(file)
        else:
            changed.append(file)
    
    return {
        "has_changes": len(lines) > 0,
        "changed_files": changed,
        "untracked_files": untracked,
        "total_changes": len(lines)
    }


def pull_from_main(local_path: Path, main_branch: str = "main") -> dict:
    """
    Main branch'ten pull yap (merge).
    
    Returns:
        {
            "success": bool,
            "message": str,
            "has_conflicts": bool
        }
    """
    # Önce fetch
    cmd = ["git", "fetch", "origin", main_branch]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        return {
            "success": False,
            "message": f"Fetch failed: {stderr}",
            "has_conflicts": False
        }
    
    # Merge
    cmd = ["git", "merge", f"origin/{main_branch}"]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        # Conflict var mı kontrol et
        if "CONFLICT" in stderr or "CONFLICT" in stdout:
            return {
                "success": False,
                "message": "Merge conflict! Lütfen manuel çözün.",
                "has_conflicts": True
            }
        else:
            return {
                "success": False,
                "message": f"Merge failed: {stderr}",
                "has_conflicts": False
            }
    
    return {
        "success": True,
        "message": "Successfully pulled from main",
        "has_conflicts": False
    }


def commit_changes(local_path: Path, message: str, author: Optional[str] = None) -> bool:
    """
    Değişiklikleri commit et.
    
    Args:
        local_path: Repo path
        message: Commit message
        author: Git author (optional, format: "Name <email>")
    
    Returns:
        True if success
    """
    # Add all
    cmd = ["git", "add", "."]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        raise GitError(f"Git add failed: {stderr}")
    
    # Commit — author'dan name/email çıkar, global git config gerekmemesi için -c ile geç
    import re as _re
    if author:
        _m = _re.match(r'^(.+?)\s*<(.+?)>$', author.strip())
        _name  = _m.group(1).strip() if _m else "OtomasyoTool"
        _email = _m.group(2).strip() if _m else "noreply@otomasyotool.local"
    else:
        _name, _email = "OtomasyoTool", "noreply@otomasyotool.local"

    cmd = [
        "git",
        "-c", f"user.name={_name}",
        "-c", f"user.email={_email}",
        "commit", "-m", message,
    ]
    if author:
        cmd.extend(["--author", author])
    
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        # Hiç değişiklik yoksa 0 döner ama stderr'da "nothing to commit" yazabilir
        if "nothing to commit" in stderr or "nothing to commit" in stdout:
            return True
        raise GitError(f"Commit failed: {stderr}")
    
    return True


def push_branch(
    local_path: Path,
    branch_name: str,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> bool:
    """
    Branch'i remote'a push et.
    
    Args:
        local_path: Repo path
        branch_name: Push edilecek branch
        username: Git username (optional)
        token: Git token (optional)
    
    Returns:
        True if success
    """
    # Remote URL'i credential ile güncelle (eğer varsa)
    if username and token:
        # Get current remote URL
        cmd = ["git", "remote", "get-url", "origin"]
        code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
        
        if code == 0:
            current_url = stdout.strip()
            # Credential ekle
            if "@" in current_url:
                parts = current_url.split("@")
                new_url = f"https://{username}:{token}@{parts[1]}"
            else:
                new_url = current_url.replace("https://", f"https://{username}:{token}@")
            
            # Set new URL
            cmd = ["git", "remote", "set-url", "origin", new_url]
            _run_git_command(cmd, cwd=local_path)
    
    # Push
    cmd = ["git", "push", "-u", "origin", branch_name]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        raise GitError(f"Push failed: {stderr}")
    
    return True


def get_commit_history(local_path: Path, limit: int = 10) -> list:
    """
    Son N commit'i getir.
    
    Returns:
        [
            {"hash": "abc123", "author": "...", "date": "...", "message": "..."},
            ...
        ]
    """
    cmd = [
        "git", "log",
        f"-{limit}",
        "--pretty=format:%H|%an|%ae|%ai|%s"
    ]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        return []
    
    commits = []
    for line in stdout.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) == 5:
            commits.append({
                "hash": parts[0][:8],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "message": parts[4]
            })
    
    return commits


def get_current_branch(local_path: Path) -> str:
    """Mevcut branch adını al."""
    cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    code, stdout, stderr = _run_git_command(cmd, cwd=local_path)
    
    if code != 0:
        raise GitError(f"Branch check failed: {stderr}")
    
    return stdout.strip()


def delete_workspace(local_path: Path):
    """Workspace klasörünü sil."""
    import shutil
    if local_path.exists():
        shutil.rmtree(local_path)