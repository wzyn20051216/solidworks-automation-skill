"""API doğrulama çalışma ortamı: eksik bileşenleri isteğe bağlı kurar, çevrim dışı ve hata geri dönüşünü korur."""
from __future__ import annotations

import hashlib
import importlib
import os
import platform
import site
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

_LOCK = threading.Lock()
_FAILED_UNTIL: dict[str, float] = {}
_OFF = {"off", "false", "0"}
_RELEASE = "https://github.com/ip7z/7zip/releases/download/26.05/"
_SEVENZIP_FILES = {
    "7zr.exe": "9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7",
    "7z2605-x64.exe": "fd99e86f57d8f429ef5ed045bf98315af962e2309b0f1ba87a147a44c71647d0",
    "7z.exe": "94205cfc054dd3bbeb978905bc619a65b3f04e9e73bb2717841110b6f46d962e",
    "7z.dll": "78bf6b668d75801e3aa180b4ccb16e6d8395fba80dec8a065055bb6f8dfabb82",
}


class SetupCancelled(Exception):
    """Kullanıcı otomatik yapılandırmayı iptal etti."""


@contextmanager
def _setup_lock(cancelled: Callable[[], bool] | None):
    """Hem aynı süreçteki iş parçacıklarını hem de farklı istemci süreçlerindeki kurulumu sıraya koyar."""
    deadline = time.monotonic() + 200
    while not _LOCK.acquire(timeout=0.2):
        if (cancelled and cancelled()) or time.monotonic() >= deadline:
            yield False
            return
    handle = None
    locked = False
    try:
        try:
            root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "solidworks-automation"
            root.mkdir(parents=True, exist_ok=True)
            handle = (root / "api-setup.lock").open("a+b")
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            while not locked:
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    if (cancelled and cancelled()) or time.monotonic() >= deadline:
                        break
                    time.sleep(0.2)
        except OSError:
            locked = False
        yield locked
    finally:
        try:
            if handle is not None:
                try:
                    if locked:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
        finally:
            _LOCK.release()


def _run_setup(args: list[str], timeout: float, cancelled: Callable[[], bool] | None) -> None:
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if cancelled and cancelled():
                raise SetupCancelled()
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def setup_enabled(allow_network: bool) -> bool:
    return (allow_network and os.environ.get("SW_API_LOOKUP_NETWORK", "on").strip().lower() not in _OFF
            and os.environ.get("SW_API_LOOKUP_AUTO_INSTALL", "on").strip().lower() not in _OFF)


def _missing(modules: tuple[str, ...]) -> bool:
    for name in modules:
        try:
            importlib.import_module(name)
        except (ImportError, OSError):
            return True
    return False


def ensure_python_packages(requirements: tuple[str, ...], modules: tuple[str, ...], *,
                           allow_network: bool, cancelled: Callable[[], bool] | None = None) -> str | None:
    """Eksikse yalnızca belirtilen bağımlılıkları kurar; hata durumunda görünür hata döndürür, tekrar kurulumu önler."""
    if not _missing(modules):
        return None
    if not setup_enabled(allow_network):
        return "Python bağımlılıkları eksik ve otomatik kurulum kapalı: " + ", ".join(requirements)
    key = "pip:" + ",".join(requirements)
    with _setup_lock(cancelled) as acquired:
        if not acquired:
            return "Otomatik yapılandırma kilidi kullanılamıyor veya görev iptal edildi; Python bağımlılıkları kurulmadı."
        if not _missing(modules):
            return None
        if time.monotonic() < _FAILED_UNTIL.get(key, 0):
            return "Python bağımlılık kurulumu yakın zamanda başarısız oldu; ağı veya Python ortamını kontrol edin: " + ", ".join(requirements)
        if cancelled and cancelled():
            return "Görev iptal edildi; Python bağımlılıkları kurulmadı."
        args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                "--only-binary=:all:"]
        install_to_user = sys.prefix == getattr(sys, "base_prefix", sys.prefix)
        if install_to_user:
            args.append("--user")
        args.extend(requirements)
        try:
            _run_setup(args, 180, cancelled)
            importlib.invalidate_caches()
            if install_to_user and not sys.flags.no_user_site:
                site.addsitedir(site.getusersitepackages())
            if not _missing(modules):
                return None
        except SetupCancelled:
            return "Görev iptal edildi; Python bağımlılık kurulumu durduruldu."
        except (OSError, subprocess.SubprocessError):
            pass
        _FAILED_UNTIL[key] = time.monotonic() + 300
        return "Python bağımlılık otomatik kurulumu başarısız; ağı, pip'i ve yazma izinlerini kontrol edin: " + ", ".join(requirements)


def _portable_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "solidworks-automation" / "tools" / "7zip-26.05-x64"


def _valid_portable(root: Path) -> bool:
    try:
        return all((root / name).stat().st_size <= 10_000_000 and
                   hashlib.sha256((root / name).read_bytes()).hexdigest() == _SEVENZIP_FILES[name]
                   for name in ("7z.exe", "7z.dll"))
    except OSError:
        return False


def _download(url: str, expected: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SolidWorks-API-Lookup/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("7-Zip indirilen içerik resmi sürüm karmasıyla tutarsız")
    destination.write_bytes(data)


def ensure_sevenzip(*, allow_network: bool, cancelled: Callable[[], bool] | None = None) -> tuple[str | None, str | None]:
    """Yalnızca sabit resmi karmayla doğrulanmış x64 taşınabilir sürümü kurar; sistem kurulumunu veya PATH'i değiştirmez."""
    root = _portable_root()
    if _valid_portable(root):
        return str(root / "7z.exe"), None
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        return None, "Kullanılabilir 7-Zip bulunamadı; bu platform yerel yardım ayrıştırıcısının otomatik yapılandırmasını henüz desteklemiyor."
    if not setup_enabled(allow_network):
        return None, "7-Zip bulunamadı ve çevrim dışı mod veya ayarlar otomatik kurulumu yasaklıyor."
    with _setup_lock(cancelled) as acquired:
        if not acquired:
            return None, "Otomatik yapılandırma kilidi kullanılamıyor veya görev iptal edildi; 7-Zip kurulmadı."
        if _valid_portable(root):
            return str(root / "7z.exe"), None
        if root.exists():
            return None, "Mevcut taşınabilir 7-Zip doğrulanamadı; dizin üzerine yazılmadı."
        if time.monotonic() < _FAILED_UNTIL.get("7zip", 0):
            return None, "7-Zip otomatik yapılandırması yakın zamanda başarısız oldu; ağı kontrol edip yeniden deneyin."
        try:
            root.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="7zip-setup-", dir=root.parent) as temp:
                work = Path(temp)
                for name in ("7zr.exe", "7z2605-x64.exe"):
                    if cancelled and cancelled():
                        return None, "Görev iptal edildi; 7-Zip kurulmadı."
                    _download(_RELEASE + name, _SEVENZIP_FILES[name], work / name)
                out = work / "portable"
                out.mkdir()
                _run_setup([str(work / "7zr.exe"), "e", "-y", "-o" + str(out),
                            str(work / "7z2605-x64.exe"), "7z.exe", "7z.dll"], 30, cancelled)
                if not _valid_portable(out):
                    raise ValueError("7-Zip çıkarılan dosya doğrulaması başarısız")
                try:
                    out.rename(root)
                except OSError:
                    if not _valid_portable(root):
                        raise
            return str(root / "7z.exe"), None
        except SetupCancelled:
            return None, "Görev iptal edildi; 7-Zip otomatik yapılandırması durduruldu."
        except (OSError, ValueError, subprocess.SubprocessError):
            _FAILED_UNTIL["7zip"] = time.monotonic() + 300
            return None, "7-Zip otomatik yapılandırması başarısız; ağı kontrol edip resmi 7-Zip'i elle kurabilirsiniz."
