"""@brief CAD Studio yerel otomasyon kuyruğu worker prototipi."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .agent_contracts import (
    DEFAULT_PROFILE,
    DANGEROUS_CAPABILITIES,
    agent_output_path,
    codex_output_path,
    compile_codex_prompt,
    policy_reasons,
    require_policy_approval,
    validate_codex_job,
)
from .agent_providers import AgentProvider, build_provider_command, parse_provider_result, resolve_provider
from .artifact_ledger import DELIVERY_FILE_EXTENSIONS, sha256_file, write_artifact_ledger
from .core import CN_TZ, now_iso
from .engineering_orchestrator import (
    build_engineering_plan,
    engineering_plan_from_dict,
    replan_for_local_change,
    requires_engineering_orchestration,
)
from .knowledge_retrieval import build_job_knowledge_context
from .reviewer_gate import write_reviewer_gate
from .worker_health import QUEUE_METADATA_FILES, write_worker_health


JobHandler = Callable[[dict[str, Any]], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]

WORKER_NAME = "cad-workbench-python-worker"
KNOWN_JOB_KINDS = {"create_shell", "import_model", "delivery_package", "dfm_review", "codex_task", "agent_task"}
TERMINAL_STATES = {"passed", "review_required", "failed", "cancelled", "blocked"}
NON_EXECUTABLE_STATES = {"approval_required", *TERMINAL_STATES}
DEFAULT_CODEX_TIMEOUT_SECONDS = 1800
DEFAULT_LEASE_SECONDS = 900
PROVIDER_VERIFICATION_FILE = "provider_verifications.json"
_ACTIVE_LOCKS: dict[Path, BinaryIO] = {}
_ACTIVE_LOCKS_GUARD = threading.Lock()
QUEUE_WRITE_RETRIES = 24


def _capability_block_reasons(job: dict[str, Any]) -> list[str]:
    """@brief Yetenek gerçeklik kaynağına göre doğrulanmamış yeteneklerin gözetimsiz teslimatını engeller."""
    requested = job.get("capabilities") or []
    if not isinstance(requested, list) or not requested:
        return []
    if job.get("schemaVersion") != "2.0":
        return []
    try:
        import sys

        scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from capabilities import capability_index, load_capabilities

        index = capability_index(load_capabilities())
    except Exception:
        # Yetenek envanteri eksikse eski görev davranışı değiştirilmez; sorunlar statik doğrulama tarafından raporlanır.
        return []
    policy = job.get("policy", {})
    manual_required = policy.get("approval") == "manual-required"
    reviewer_required = policy.get("requireReviewerPass") is True
    reasons: list[str] = []
    for capability_id in requested:
        # Güvenlik izinleri CAD yeteneği değildir. Bunlar require_policy_approval() tarafından ayrıca ele alınır;
        # capabilities.yaml'a yazılmadı diye yetkilendirilmiş bir CAD görevi doğrudan blocked olarak işaretlenemez.
        if str(capability_id) in DANGEROUS_CAPABILITIES:
            continue
        item = index.get(str(capability_id))
        if not item:
            reasons.append(f"{capability_id} yetenek envanterinde yok")
            continue
        level = item.get("level")
        if level == "verified":
            continue
        if level == "pilot" and reviewer_required:
            continue
        if level == "reference_only" and manual_required:
            continue
        reasons.append(f"{capability_id} şu anda {level} düzeyinde; yürütme modu yetenek kısıtlarını karşılamıyor")
    return reasons


class JobCancelled(RuntimeError):
    """@brief Görev kullanıcı tarafından iptal edildi."""


class JobBlocked(RuntimeError):
    """@brief Ortam veya yetenek kapısı görev yürütmeyi engelliyor."""


def _codex_windowsapps_candidates() -> list[Path]:
    """@brief Windows Store sürümü Codex için aday exe yollarını döndürür."""
    candidates: list[Path] = []
    windows_apps = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WindowsApps"
    try:
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/*/resources/codex.exe")))
        candidates.extend(sorted(windows_apps.glob("OpenAI.Codex_*/app/resources/codex.exe")))
    except OSError:
        return []
    return candidates


def _node_codex_command(npm_root: Path) -> list[str] | None:
    """@brief npm Codex'i doğrudan Node üzerinden başlatır; cmd.exe'nin kullanıcı prompt'unu ikinci kez ayrıştırmasını önler."""
    script = npm_root / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    if not script.is_file():
        return None
    bundled_node = npm_root / "node.exe"
    node = str(bundled_node) if bundled_node.is_file() else (shutil.which("node.exe") or shutil.which("node"))
    return [node, str(script)] if node else None


def resolve_codex_command() -> list[str]:
    """@brief Python worker tarafından güvenilir şekilde başlatılabilecek Codex CLI komutunu çözümler."""
    env_path = os.environ.get("CODEX_BIN")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            if candidate.suffix.lower() in {".cmd", ".bat"}:
                command = _node_codex_command(candidate.parent)
                if command:
                    return command
            else:
                return [str(candidate)]

    appdata = os.environ.get("APPDATA")
    if appdata:
        command = _node_codex_command(Path(appdata) / "npm")
        if command:
            return command

    candidates: list[Path] = []
    for name in ("codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(_codex_windowsapps_candidates())

    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        return [str(candidate)]

    raise FileNotFoundError(
        "Codex CLI bulunamadı. Ayarlardan CC Switch'i senkronize edin veya Codex'in kurulu olduğunu doğrulayın ve codex.exe/codex.cmd dosyasını PATH'e ekleyin."
    )


def default_tauri_queue_dir(identifier: str = "com.wzyn.cadstudio") -> Path:
    """@brief Tauri varsayılan uygulama verisi kuyruk dizinini döndürür."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / identifier / "queue"
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / identifier / "queue"
    return Path.home() / ".local" / "share" / identifier / "queue"


def read_job(path: Path) -> dict[str, Any]:
    """@brief Tek bir kuyruk görevi JSON'unu okur."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Görev bir JSON nesnesi değil: {path}")
    return payload


def write_job(path: Path, job: dict[str, Any]) -> None:
    """@brief Tek bir kuyruk görevi JSON'unu atomik olarak geri yazar."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, job)


def _queue_write_delay(attempt: int) -> float:
    """@brief Windows kuyruk dosyası kısa süreliğine meşgulken kullanılacak geri çekilme süresini döndürür."""
    return min(0.025 + attempt * 0.025, 0.25)


def atomic_replace_with_retry(temporary: Path, target: Path) -> None:
    """@brief Kuyruk dosyasını yeniden deneme mekanizmasıyla değiştirir; Windows'un anlık dosya kilitlerini aşar."""
    last_error: OSError | None = None
    for attempt in range(QUEUE_WRITE_RETRIES):
        try:
            temporary.replace(target)
            return
        except OSError as error:
            last_error = error
            time.sleep(_queue_write_delay(attempt))
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    raise OSError(
        f"Kuyruk dosyası yazılamadı; Windows, {target} erişimini geçici olarak reddetti. "
        "Yinelenen CAD Studio/Worker kopyalarını kapatın veya daha sonra yeniden deneyin."
    ) from last_error


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """@brief JSON'u benzersiz bir geçici dosyaya yazar, ardından hedef dosyayı atomik olarak değiştirir."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    atomic_replace_with_retry(temporary, path)


def cancel_marker_path(path: Path) -> Path:
    """@brief Süreçler arası iptal işaretçisi yolunu döndürür; görev JSON'unun eşzamanlı geri yazımının iptal isteğini yutmasını önler."""
    path = Path(path)
    return path.with_suffix(path.suffix + ".cancel")


def is_cancel_requested(path: Path, job: dict[str, Any] | None = None) -> bool:
    """@brief Bağımsız işaretçiyi ve görev alanını birlikte kontrol eder."""
    if cancel_marker_path(path).exists():
        return True
    current = job if job is not None else read_job(path)
    return current.get("status") == "cancelled" or current.get("cancelRequested") is True


def worker_id() -> str:
    """@brief Geçerli worker sürecinin kısa kimliğini döndürür."""
    return f"{WORKER_NAME}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def lock_path_for(path: Path) -> Path:
    """@brief Görev dosyasına karşılık gelen sahiplenme kilidi yolunu döndürür."""
    return Path(str(path) + ".lock")


def quarantine_dir(queue_dir: Path) -> Path:
    """@brief Bozuk görev karantina dizinini döndürür."""
    directory = Path(queue_dir) / "quarantine"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def events_dir(queue_dir: Path) -> Path:
    """@brief Görev olay akışı dizinini döndürür."""
    directory = Path(queue_dir) / "events"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def logs_dir(queue_dir: Path) -> Path:
    """@brief Çalışma günlüğü dizinini döndürür."""
    directory = Path(queue_dir) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def event_path_for(queue_dir: Path, job_id: Any) -> Path:
    """@brief Görevin JSONL olay dosyası yolunu döndürür."""
    safe_id = "".join(ch for ch in str(job_id or "") if ch.isascii() and (ch.isalnum() or ch in "-_"))
    if not safe_id:
        safe_id = "unknown"
    return events_dir(queue_dir) / f"{safe_id[:96]}.jsonl"


def log_paths_for(queue_dir: Path, job_id: Any) -> tuple[Path, Path]:
    """@brief Görevin stdout/stderr günlük yollarını döndürür."""
    safe_id = "".join(ch for ch in str(job_id or "") if ch.isascii() and (ch.isalnum() or ch in "-_")) or "unknown"
    directory = logs_dir(queue_dir)
    return directory / f"{safe_id[:96]}.stdout.log", directory / f"{safe_id[:96]}.stderr.log"


def append_event(queue_dir: Path, job: dict[str, Any], event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    """@brief Yapılandırılmış bir kuyruk olayı ekler."""
    event = {
        "type": event_type,
        "jobId": job.get("id"),
        "runId": job.get("runId"),
        "status": job.get("status"),
        "progress": job.get("progress"),
        "message": message,
        "at": now_iso(),
        "worker": WORKER_NAME,
        "runnerId": job.get("runnerId"),
        "data": data or {},
    }
    path = event_path_for(queue_dir, job.get("id"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def parse_iso(value: Any) -> datetime | None:
    """@brief ISO zamanını ayrıştırır; başarısız olursa None döndürür."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def lease_until(seconds: int = DEFAULT_LEASE_SECONDS) -> str:
    """@brief Lease sona erme zamanını döndürür."""
    return (datetime.now(CN_TZ) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def is_expired(value: Any) -> bool:
    """@brief Lease süresinin dolup dolmadığına karar verir."""
    parsed = parse_iso(value)
    if parsed is None:
        return True
    return parsed <= datetime.now(CN_TZ)


def quarantine_bad_job(path: Path, error: Exception) -> Path:
    """@brief Ayrıştırılamayan görev dosyalarını karantinaya alır; watch döngüsünün kesilmesini önler."""
    path = Path(path)
    target = quarantine_dir(path.parent) / f"{path.stem}_{datetime.now(CN_TZ).strftime('%Y%m%d_%H%M%S')}.json"
    shutil.move(str(path), str(target))
    report = target.with_suffix(".error.txt")
    report.write_text(str(error), encoding="utf-8")
    return target


def acquire_lock(path: Path, runner_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Path | None:
    """@brief Yaşam döngüsü işletim sistemi tarafından yönetilen dosya kilidini edinir."""
    lock_path = lock_path_for(path)
    payload = json.dumps(
        {
            "runnerId": runner_id,
            "pid": os.getpid(),
            "lockedAt": now_iso(),
            "leaseUntil": lease_until(lease_seconds),
        },
        ensure_ascii=False,
        indent=2,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _ACTIVE_LOCKS_GUARD:
        if lock_path in _ACTIVE_LOCKS:
            return None
        handle = lock_path.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        handle.seek(0)
        handle.truncate()
        handle.write(payload.encode("utf-8"))
        handle.flush()
        _ACTIVE_LOCKS[lock_path] = handle
    return lock_path


def release_lock(lock_path: Path | None) -> None:
    """@brief Dosya kilidini serbest bırakır; kilit dosyası korunur ve süreç çıkışında işletim sistemi kilidi otomatik serbest bırakır."""
    if lock_path is None:
        return
    path = Path(lock_path)
    with _ACTIVE_LOCKS_GUARD:
        handle = _ACTIVE_LOCKS.pop(path, None)
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def mark_job_claimed(job: dict[str, Any], runner_id: str, lease_seconds: int) -> None:
    """@brief Görev sahiplenme bilgisini yazar."""
    job["runnerId"] = runner_id
    job["workerPid"] = os.getpid()
    job["heartbeatAt"] = now_iso()
    job["leaseUntil"] = lease_until(lease_seconds)
    job["attempt"] = int(job.get("attempt") or 0) + 1


def refresh_job_heartbeat(path: Path, runner_id: str, lease_seconds: int, message: str = "worker heartbeat") -> dict[str, Any]:
    """@brief Çalışan görevin heartbeat ve lease bilgisini yeniler."""
    job = read_job(path)
    if is_cancel_requested(path, job):
        raise JobCancelled("Görev için iptal istendi")
    job["runnerId"] = runner_id
    job["workerPid"] = os.getpid()
    job["heartbeatAt"] = now_iso()
    job["leaseUntil"] = lease_until(lease_seconds)
    job["lastMessage"] = message
    write_job(path, job)
    append_event(path.parent, job, "run.heartbeat", message)
    return job


def request_cancel(path: Path) -> dict[str, Any]:
    """@brief Görevi iptal istendi olarak işaretler."""
    cancel_marker_path(path).write_text("cancel\n", encoding="ascii")
    job = read_job(path)
    job["cancelRequested"] = True
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "İptal istendi; worker'ın geçerli adımı durdurması bekleniyor."
    write_job(path, job)
    append_event(path.parent, job, "run.cancel_requested", "İptal istendi")
    return job


def approve_job(path: Path, approved_by: str = "local-user") -> dict[str, Any]:
    """@brief Onay bekleyen görevi insan onayıyla yeniden kuyruğa alır."""
    job = read_job(path)
    if job.get("status") != "approval_required":
        return job
    reasons = policy_reasons(job)
    job["approvedBy"] = approved_by
    job["approvedAt"] = now_iso()
    job["approvedPolicyReasons"] = reasons
    job["status"] = "queued"
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "İnsan onayı verildi; görev yeniden kuyruğa alındı."
    write_job(path, job)
    append_event(path.parent, job, "policy.approved", "İnsan onayı verildi", {"approvedBy": approved_by})
    return job


def mark_approval_required(path: Path, job: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    """@brief Görevi onay bekliyor durumuna alır."""
    job["status"] = "approval_required"
    job["progress"] = 0
    job["approvalReasons"] = reasons
    job["updatedAt"] = now_iso()
    job["lastMessage"] = "Görev insan onayı gerektiriyor: " + "; ".join(reasons)
    append_worker_event(job, "approval_required", job["lastMessage"])
    write_job(path, job)
    append_event(path.parent, job, "policy.approval_required", job["lastMessage"], {"reasons": reasons})
    return job


def recover_stale_jobs(queue_dir: Path) -> int:
    """@brief Lease süresi dolan running görevleri queued durumuna geri döndürür."""
    recovered = 0
    recovery_runner_id = f"{worker_id()}-recovery"
    for path in sorted(Path(queue_dir).glob("*.json")):
        if path.name in QUEUE_METADATA_FILES:
            continue
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") != "running" or not is_expired(job.get("leaseUntil")):
            continue
        lock_path = acquire_lock(path, recovery_runner_id)
        if lock_path is None:
            continue
        try:
            job = read_job(path)
            if job.get("status") != "running" or not is_expired(job.get("leaseUntil")):
                continue
            cancel_requested = is_cancel_requested(path, job)
            if cancel_requested:
                set_job_state(job, "cancelled", int(job.get("progress") or 0), "Worker lease süresi doldu; iptal isteği uygulandı.")
                job["cancelRequested"] = True
                event_type = "run.cancelled"
            else:
                set_job_state(job, "queued", 0, "Worker lease süresi doldu; görev yeniden kuyruğa alındı.")
                job.pop("cancelRequested", None)
                cancel_marker_path(path).unlink(missing_ok=True)
                event_type = "run.recovered_stale"
            job.pop("runnerId", None)
            job.pop("workerPid", None)
            job.pop("heartbeatAt", None)
            job.pop("leaseUntil", None)
            write_job(path, job)
            append_event(path.parent, job, event_type, job["lastMessage"])
            recovered += 1
        finally:
            release_lock(lock_path)
    return recovered


def append_worker_event(job: dict[str, Any], status: str, message: str) -> None:
    """@brief Göreve worker durum akışı ekler; UI ve test takibini kolaylaştırır."""
    events = job.setdefault("workerLog", [])
    if isinstance(events, list):
        events.append(
            {
                "status": status,
                "message": message,
                "at": now_iso(),
                "worker": WORKER_NAME,
            }
        )


def set_job_state(job: dict[str, Any], status: str, progress: int, message: str) -> None:
    """@brief Görev durumunu, ilerlemeyi ve son yürütme bilgisini günceller."""
    job["status"] = status
    job["progress"] = max(0, min(100, int(progress)))
    job["updatedAt"] = now_iso()
    job["lastMessage"] = message
    stage_by_status = {
        "queued": "intake",
        "running": "executing",
        "passed": "delivery",
        "review_required": "reviewing",
        "failed": "reviewing",
        "cancelled": "blocked",
        "blocked": "blocked",
    }
    job.setdefault("stage", stage_by_status.get(status, "executing"))
    if status in {"passed", "review_required", "failed", "cancelled", "blocked"}:
        job["stage"] = stage_by_status.get(status, job.get("stage"))
    append_worker_event(job, status, message)


def _domain_evidence_status(result: dict[str, Any]) -> tuple[str | None, str | None]:
    """@brief Teknik resim/BOM/DFM alan kanıtına göre daha katı nihai durumu belirler."""
    evidence_items = [result.get("drawingEvidence"), result.get("bomEvidence"), result.get("dfmEvidence")]
    statuses = {str(item.get("status")) for item in evidence_items if isinstance(item, dict) and item.get("status")}
    if "blocked" in statuses:
        return "blocked", "Teknik resim, BOM veya DFM ortam/yetenek kapısı teslimatı engelliyor"
    if "failed" in statuses or "fail" in statuses:
        return "failed", "Teknik resim, BOM veya DFM incelemesi başarısız; görev teslim edilemez"
    if any(isinstance(item, dict) and item.get("manual_review_required") for item in evidence_items):
        return "review_required", "Teknik resim, BOM veya DFM üretildi; ancak insan incelemesi hâlâ gerekli"
    return None, None


def mock_create_shell(job: dict[str, Any]) -> dict[str, Any]:
    """@brief Mock kabuk üretim görevi; ileride SolidWorks COM handler ile değiştirilecek."""
    return {
        "mode": "mock",
        "message": "Kabuk, gerçek delik açma ve 3D baskı temel kontrolleri için mock akışı tamamlandı.",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def mock_import_model(job: dict[str, Any]) -> dict[str, Any]:
    """@brief Mock model içe aktarma görevi; ileride model ayrıştırma handler'ı ile değiştirilecek."""
    return {
        "mode": "mock",
        "message": "Model yolu kaydedildi ve proje bağlamı mock sonucu oluşturuldu.",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def mock_delivery_package(job: dict[str, Any]) -> dict[str, Any]:
    """@brief Mock teslimat paketi görevi; ileride gerçek dışa aktarma ve paketleme handler'ı ile değiştirilecek."""
    return {
        "mode": "mock",
        "message": "STEP, STL, PDF ve DWG teslimat listesi mock özeti tamamlandı.",
        "outputs": [],
        "projectPath": job.get("projectPath"),
    }


def build_codex_prompt(job: dict[str, Any]) -> str:
    """@brief Grafik yapılandırma görevini Codex'in yürütebileceği prompt'a dönüştürür."""
    return compile_codex_prompt(job, profile=DEFAULT_PROFILE)


def _artifact_roots(job: dict[str, Any], cwd: Path) -> list[Path]:
    """@brief Görevin teslimat bildirebileceği çalışma alanını, çıktı dizinini ve girdi dosyası dizinlerini döndürür."""
    roots = [cwd.resolve()]
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    output_dir = ui_config.get("outputDir")
    if output_dir:
        candidate = Path(str(output_dir)).expanduser()
        roots.append((candidate if candidate.is_absolute() else cwd / candidate).resolve())
    project_path = job.get("projectPath")
    if project_path:
        candidate = Path(str(project_path)).expanduser()
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        roots.append((candidate.parent if candidate.suffix else candidate).resolve())
    return roots


def _path_in_roots(path: Path, roots: list[Path]) -> bool:
    """@brief Yolun izin verilen kök dizinlerden herhangi birinde olup olmadığına karar verir."""
    return any(root == path or root in path.parents for root in roots)


def _resolve_job_path(value: Any, base_dir: Path) -> Path | None:
    """@brief Görev girdisindeki yolları mutlak yollara çözümler."""
    if not value:
        return None
    candidate = Path(str(value)).expanduser()
    return (candidate if candidate.is_absolute() else base_dir / candidate).resolve()


def _dfm_input_path(job: dict[str, Any], base_dir: Path) -> Path | None:
    """@brief NeutralCadDocument'ı Job 2.0 girdisinden, UI yapılandırmasından veya proje yolundan bulur."""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    for key in ("neutralDocumentPath", "cadstudioPath", "inputPath"):
        candidate = _resolve_job_path(ui_config.get(key), base_dir)
        if candidate and candidate.is_file():
            return candidate
    for item in job.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path") or item.get("inputPath") or item.get("documentPath") or item.get("neutralDocumentPath") or item.get("source")
        candidate = _resolve_job_path(raw_path, base_dir)
        if candidate and candidate.is_file() and candidate.suffix.lower() == ".json":
            name = candidate.name.lower()
            input_type = str(item.get("type") or item.get("kind") or "").lower()
            if "cadstudio" in name or "neutral" in input_type or "cadstudio" in input_type:
                return candidate
    project_path = _resolve_job_path(job.get("projectPath"), base_dir)
    if project_path and project_path.is_file() and project_path.suffix.lower() == ".json":
        return project_path
    return None


def _dfm_output_path(job: dict[str, Any], source: Path, base_dir: Path) -> Path:
    """@brief DFM raporunun varsayılan çıktı yolunu döndürür."""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    raw_output = ui_config.get("dfmReportPath") or job.get("dfmReportPath")
    if raw_output:
        candidate = _resolve_job_path(raw_output, base_dir)
        if candidate:
            return candidate
    output_dir = _resolve_job_path(ui_config.get("outputDir"), base_dir)
    if output_dir is None:
        runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
        job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else base_dir / "job.json"
        output_dir = job_path.parent / "dfm-reports"
    return output_dir / f"{source.stem}_dfm_report.json"


def _dfm_synthetic_document(job: dict[str, Any], base_dir: Path) -> Path | None:
    """@brief UI ölçü yapılandırmasından izlenebilir DFM taslak belgesi üretir."""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    geometry = ui_config.get("geometry") if isinstance(ui_config.get("geometry"), dict) else {}
    manufacturing = ui_config.get("manufacturing") if isinstance(ui_config.get("manufacturing"), dict) else {}
    try:
        length = float(geometry.get("length") or 0)
        width = float(geometry.get("width") or 0)
        height = float(geometry.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if length <= 0 or width <= 0 or height <= 0:
        return None
    output_dir = _resolve_job_path(ui_config.get("outputDir"), base_dir)
    if output_dir is None:
        runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
        job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else base_dir / "job.json"
        output_dir = job_path.parent / "dfm-reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_run_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(job.get("runId") or job.get("id") or uuid.uuid4().hex))[:120]
    target = output_dir / f"{safe_run_id}_ui_config.cadstudio.json"
    payload = {
        "documentId": safe_run_id,
        "title": job.get("title") or "CAD Studio UI DFM taslağı",
        "units": manufacturing.get("unit") or "mm",
        "features": [
            {
                "id": "ui-envelope",
                "type": "box",
                "name": "UI yapılandırma zarfı",
                "parameters": {"length": length, "width": width, "height": height},
                "evidenceRefs": ["uiConfig.geometry"],
            }
        ],
        "metadata": {
            "source": "ui_config_synthetic_neutral_document",
            "manufacturing": {
                "process": manufacturing.get("process"),
                "material": "" if manufacturing.get("material") == "auto" else manufacturing.get("material"),
                "wallThickness": geometry.get("wallThickness"),
            },
        },
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def run_dfm_review_job(job: dict[str, Any]) -> dict[str, Any]:
    """@brief NeutralCadDocument DFM incelemesini yerel olarak yürütür; SolidWorks/AutoCAD'e bağımlı değildir."""
    base_dir = Path(str(job.get("cwd") or Path.cwd())).expanduser().resolve()
    source = _dfm_input_path(job, base_dir)
    if source is None:
        source = _dfm_synthetic_document(job, base_dir)
    if source is None:
        evidence = {
            "schemaVersion": "1.0",
            "status": "blocked",
            "stage": "dfm_review",
            "process": "unknown",
            "checks": [],
            "missingInputs": ["inputs[].path"],
            "artifacts": [],
            "manualReviewRequired": True,
            "manual_review_required": True,
            "retryable": False,
            "error_code": "dfm_input_missing",
            "message": "NeutralCadDocument .cadstudio.json girdisi bulunamadı.",
        }
        return {
            "mode": "local-dfm",
            "message": "DFM incelemesi engellendi: NeutralCadDocument girdisi eksik.",
            "outputs": [],
            "artifacts": [],
            "dfmEvidence": evidence,
            "reviewFindings": [evidence],
            "projectPath": job.get("projectPath"),
        }
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    process = str(job.get("process") or ui_config.get("process") or "auto")
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from dfm_review import write_dfm_report

    evidence = write_dfm_report(source, _dfm_output_path(job, source, base_dir), process=process)
    return {
        "mode": "local-dfm",
        "message": "DFM inceleme raporu üretildi; makine kuralları yalnızca risk uyarısı içindir, insan onayı hâlâ gereklidir.",
        "outputs": evidence.get("artifacts", []),
        "artifacts": evidence.get("artifacts", []),
        "checks": evidence.get("checks", []),
        "dfmEvidence": evidence,
        "reviewFindings": evidence.get("reviewFindings", []),
        "projectPath": job.get("projectPath"),
    }


def _snapshot_cad_artifacts(roots: list[Path], limit: int = 10000, *,
                            extensions: frozenset[str] | None = DELIVERY_FILE_EXTENSIONS) -> dict[str, Any]:
    """@brief Yürütme öncesi teslimat dosyası karmalarını kaydeder ve taramanın eksiksiz olup olmadığını açıkça belirtir."""
    entries: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    complete = True
    truncated = False
    visited: set[Path] = set()
    canonical_roots: list[Path] = []
    scopes: list[dict[str, str]] = []
    for root in roots:
        try:
            canonical = Path(root).expanduser().resolve()
            canonical_roots.append(canonical)
            scopes.append({"path": os.path.normcase(str(canonical)), "kind": "file" if canonical.is_file() else "directory"})
        except (OSError, RuntimeError, ValueError) as error:
            complete = False
            errors.append(f"Taban çizgisi kök dizini normalleştirilemedi: {root}: {error}")

    for root in canonical_roots:
        if root in visited:
            continue
        visited.add(root)
        try:
            if not root.exists():
                continue
            def scan_error(error):
                nonlocal complete
                complete = False
                errors.append(f"Dizin taraması kesildi: {error}")

            def files():
                # rglob bazı Python sürümlerinde erişim hatalarını sessizce yok sayar; walk'ın onerror'u kaydetmek zorundadır.
                for folder, directories, names in os.walk(root, onerror=scan_error, followlinks=False):
                    directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()
                                      and not (hasattr(Path(folder) / name, "is_junction") and (Path(folder) / name).is_junction())]
                    for name in names:
                        yield Path(folder) / name

            candidates = [root] if root.is_file() else files()
            iterator = iter(candidates)
            while True:
                try:
                    candidate = next(iterator)
                except StopIteration:
                    break
                except OSError as error:
                    complete = False
                    errors.append(f"Dizin taraması kesildi: {root}: {error}")
                    break
                try:
                    if not candidate.is_file() or (extensions is not None and candidate.suffix.lower() not in extensions):
                        continue
                    resolved = candidate.resolve(strict=True)
                    # Taban çizgisi yalnızca izin verilen kök dizinler içinde kalan gerçek dosyalar için oluşturulur.
                    if not _path_in_roots(resolved, canonical_roots):
                        continue
                    if len(entries) >= limit:
                        complete = False
                        truncated = True
                        break
                    stat = resolved.stat()
                    key = os.path.normcase(os.path.normpath(str(resolved)))
                    entries[key] = {
                        "sizeBytes": stat.st_size,
                        "mtimeNs": stat.st_mtime_ns,
                        "sha256": sha256_file(resolved),
                    }
                except (OSError, RuntimeError, ValueError) as error:
                    complete = False
                    errors.append(f"Taban çizgisi dosyası okunamadı: {candidate}: {error}")
            if truncated:
                break
        except OSError as error:
            complete = False
            errors.append(f"Taban çizgisi kök dizini taranamadı: {root}: {error}")

    return {
        "schemaVersion": "2.0",
        "entries": entries,
        "roots": scopes,
        "extensions": sorted(extensions) if extensions is not None else ["*"],
        "complete": complete,
        "truncated": truncated,
        "scannedCount": len(entries),
        "errors": errors[:50],
    }


def _validate_codex_result(value: Any) -> dict[str, Any]:
    """@brief Codex nihai JSON'unu sıkı doğrular; yalnızca alan varlığını kontrol ederek teslimat kapısına geçilmesini önler."""
    if not isinstance(value, dict):
        raise RuntimeError("Codex yapılandırılmış sonucu bir JSON nesnesi olmalıdır")
    required_fields = {"summary", "changedFiles", "verification", "risks", "nextSteps"}
    missing_fields = sorted(required_fields.difference(value))
    if missing_fields:
        raise RuntimeError(f"Codex yapılandırılmış sonucunda eksik alanlar: {', '.join(missing_fields)}")
    if not isinstance(value["summary"], str):
        raise RuntimeError("Codex yapılandırılmış sonucunda summary bir dize olmalıdır")
    for field in ("changedFiles", "risks", "nextSteps"):
        if not isinstance(value[field], list) or not all(isinstance(item, str) for item in value[field]):
            raise RuntimeError(f"Codex yapılandırılmış sonucunda {field} bir dize dizisi olmalıdır")
    if not isinstance(value["verification"], list):
        raise RuntimeError("Codex yapılandırılmış sonucunda verification bir dizi olmalıdır")
    for index, item in enumerate(value["verification"]):
        if not isinstance(item, dict):
            raise RuntimeError(f"verification[{index}] bir nesne olmalıdır")
        if set(item) != {"command", "status", "note"}:
            raise RuntimeError(f"verification[{index}] alanları şemaya uymuyor")
        if not isinstance(item["command"], str) or not isinstance(item["note"], str):
            raise RuntimeError(f"verification[{index}] command/note dize olmalıdır")
        if item["status"] not in {"passed", "failed", "skipped"}:
            raise RuntimeError(f"verification[{index}] status geçersiz: {item['status']}")
    return value


def _provider_id_for_job(job: dict[str, Any]) -> str:
    """@brief Provider'ı birleşik görev protokolünden okur; eski Codex görevleri otomatik uyumludur."""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    agent_runtime = ui_config.get("agentRuntime") if isinstance(ui_config.get("agentRuntime"), dict) else {}
    return str(agent_runtime.get("provider") or "codex").strip().lower()


def record_provider_verification(queue_dir: Path, provider: AgentProvider) -> Path:
    """@brief Gerçek yapılandırılmış görev başarı kanıtını kaydeder; masaüstü sağlık durumu tarafından okunur."""
    verification_path = Path(queue_dir) / PROVIDER_VERIFICATION_FILE
    try:
        current = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.is_file() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        current = {}
    providers = current.get("providers") if isinstance(current, dict) and isinstance(current.get("providers"), dict) else {}
    providers[provider.id] = {
        "verified": True,
        "verifiedAt": now_iso(),
        "protocol": provider.protocol,
        "resultSchema": "codex_final_response.schema.json",
    }
    atomic_write_json(verification_path, {"schemaVersion": "1.0", "providers": providers})
    return verification_path


def previous_engineering_plan(job: dict[str, Any]) -> dict[str, Any] | None:
    """@brief Aynı kuyruğun önceki tur diyalog görevinden DAG'ı geri yükler ve bu turun gereksinimlerine göre yerel yeniden planlama yapar."""
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    source_job_id = str(ui_config.get("sourceJobId") or "").strip()
    retry_policy = job.get("retryPolicy") if isinstance(job.get("retryPolicy"), dict) else {}
    run_history = job.get("runHistory") if isinstance(job.get("runHistory"), list) else []
    if retry_policy and run_history:
        latest = run_history[-1] if isinstance(run_history[-1], dict) else {}
        latest_result = latest.get("result") if isinstance(latest.get("result"), dict) else {}
        payload = latest_result.get("engineeringPlan") if isinstance(latest_result.get("engineeringPlan"), dict) else None
        retry_from_stage = str(retry_policy.get("retryFromStage") or "").strip()
        if payload is not None:
            try:
                plan = engineering_plan_from_dict(payload)
                known_phases = {phase.id for phase in plan.phases}
                affected = [retry_from_stage] if retry_from_stage in known_phases else None
                return replan_for_local_change(
                    plan,
                    f"{retry_from_stage or 'başarısız aşama'} aşamasından yeniden üret ve eski sürümü koru",
                    affected_phase_ids=affected,
                ).to_dict()
            except (KeyError, TypeError, ValueError):
                pass
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    current_job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else None
    if not source_job_id or current_job_path is None or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", source_job_id) is None:
        return None
    source_path = current_job_path.parent / f"{source_job_id}.json"
    try:
        source_job = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    result = source_job.get("result") if isinstance(source_job, dict) and isinstance(source_job.get("result"), dict) else {}
    payload = result.get("engineeringPlan") if isinstance(result.get("engineeringPlan"), dict) else None
    if payload is None:
        return None
    objective = str(job.get("objective") or job.get("detail") or "").strip()
    try:
        return replan_for_local_change(engineering_plan_from_dict(payload), objective).to_dict()
    except (KeyError, TypeError, ValueError):
        return None


def run_agent_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    allow_full_access: bool = False,
) -> dict[str, Any]:
    """@brief Yerel Agent CLI'yi birleşik Provider Adapter üzerinden çağırır."""
    cwd = validate_codex_job(job)
    provider_id = _provider_id_for_job(job)
    if runner is None:
        provider = resolve_provider(provider_id)
    else:
        names = {
            "codex": "Codex",
            "claude": "Claude Code",
            "gemini": "Gemini CLI",
            "opencode": "OpenCode",
            "lmstudio": "LM Studio",
        }
        protocols = {
            "codex": "codex-exec-v1",
            "claude": "claude-print-v1",
            "gemini": "gemini-headless-v1",
            "opencode": "opencode-jsonl-v1",
            "lmstudio": "lmstudio-openai-v1",
        }
        if provider_id not in names:
            raise ValueError(f"Desteklenmeyen Agent Provider: {provider_id}")
        provider = AgentProvider(
            provider_id,
            names[provider_id],
            protocols[provider_id],
            provider_id in {"codex", "claude", "lmstudio"},
            provider_id != "lmstudio",
            (provider_id,),
        )
    prompt_job = dict(job)
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    job_path = Path(str(runtime["jobPath"])) if runtime.get("jobPath") else None
    try:
        prompt_job["_knowledgeContext"] = build_job_knowledge_context(
            job, cancelled=(lambda: is_cancel_requested(job_path)) if job_path else None)
    except Exception as exc:
        from scripts.sw_api_lookup import LookupCancelled
        if isinstance(exc, LookupCancelled):
            raise JobCancelled(str(exc)) from exc
        raise
    if job_path and prompt_job["_knowledgeContext"].get("warnings"):
        warning = "；".join(str(item)[:300] for item in prompt_job["_knowledgeContext"]["warnings"][:8])
        append_event(job_path.parent, job, "knowledge.warning", warning)
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    orchestration = ui_config.get("engineeringOrchestration") if isinstance(ui_config.get("engineeringOrchestration"), dict) else {}
    objective = str(job.get("objective") or job.get("detail") or "")
    orchestration_mode = str(orchestration.get("mode") or "auto_dag")
    if orchestration_mode != "off":
        continued_plan = previous_engineering_plan(job)
        if continued_plan is not None:
            prompt_job["_engineeringPlan"] = continued_plan
        elif requires_engineering_orchestration(objective):
            prompt_job["_engineeringPlan"] = build_engineering_plan(objective).to_dict()
    prompt = build_codex_prompt(prompt_job)
    legacy_codex = job.get("executor") == "codex" and provider.id == "codex"
    output_path = codex_output_path(job, cwd) if legacy_codex else agent_output_path(job, cwd)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    engineering_plan_path: Path | None = None
    if isinstance(prompt_job.get("_engineeringPlan"), dict):
        engineering_plan_path = output_path.with_suffix(".engineering-plan.json")
        engineering_plan_path.write_text(
            json.dumps(prompt_job["_engineeringPlan"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    allowed_roots = _artifact_roots(job, cwd)
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    artifact_baseline = runtime.get("artifactBaseline")
    if not isinstance(artifact_baseline, dict):
        artifact_baseline = _snapshot_cad_artifacts(allowed_roots)
    policy = job.get("policy") if isinstance(job.get("policy"), dict) else {}
    requested_sandbox = policy.get("sandbox")
    sandbox = "danger-full-access" if allow_full_access and requested_sandbox == "danger-full-access" else "workspace-write"

    agent_runtime = ui_config.get("agentRuntime") if isinstance(ui_config.get("agentRuntime"), dict) else {}
    model = str(agent_runtime.get("model") or "").strip() or None
    command = build_provider_command(
        provider,
        prompt,
        cwd,
        output_path,
        DEFAULT_PROFILE.policy.output_schema_path,
        sandbox,
        model=model,
    )
    if runner is None and job.get("_runtime"):
        completed = _run_command_with_runtime(command, cwd, timeout_seconds, job)
    else:
        active_runner = runner or _run_command
        completed = active_runner(command, cwd, timeout_seconds)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError((stderr or stdout or f"{provider.name} failed with code {completed.returncode}").strip())

    structured = _validate_codex_result(parse_provider_result(provider, stdout, output_path))
    if runner is None:
        runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
        job_path = Path(str(runtime.get("jobPath"))) if runtime.get("jobPath") else None
        queue_dir = job_path.parent if job_path else default_tauri_queue_dir()
        record_provider_verification(queue_dir, provider)

    changed_files = structured.get("changedFiles") if isinstance(structured.get("changedFiles"), list) else []
    artifacts: list[dict[str, Any]] = []
    rejected_artifacts: list[str] = []
    for raw_path in changed_files:
        candidate = Path(str(raw_path)).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        candidate = candidate.resolve()
        if not _path_in_roots(candidate, allowed_roots):
            rejected_artifacts.append(str(candidate))
            continue
        artifacts.append({"kind": candidate.suffix.lstrip(".") or "file", "path": str(candidate)})
    artifacts.append({"kind": "agent_output", "path": str(output_path)})
    if engineering_plan_path is not None:
        artifacts.append({"kind": "engineering_plan", "path": str(engineering_plan_path)})
    risks = structured.get("risks") if isinstance(structured.get("risks"), list) else []
    if rejected_artifacts:
        risks = [*risks, "Çalışma alanı, çıktı dizini veya girdi dosyası dizini dışındaki teslimat yolları reddedildi: " + "; ".join(rejected_artifacts)]

    return {
        "mode": "codex" if legacy_codex else "agent",
        "provider": provider.to_dict(),
        "message": str(structured.get("summary") or f"{provider.name} yürütmeyi tamamladı; sonuç yerel çıktı dosyasına geri yazıldı."),
        "command": command[:2] + ["..."],
        "cwd": str(cwd),
        "sandbox": sandbox,
        "artifactBaseline": artifact_baseline,
        "outputPath": str(output_path),
        "outputs": artifacts,
        "artifacts": artifacts,
        "verification": structured.get("verification") if isinstance(structured.get("verification"), list) else [],
        "risks": risks,
        "nextSteps": structured.get("nextSteps") if isinstance(structured.get("nextSteps"), list) else [],
        "knowledgeContext": prompt_job["_knowledgeContext"],
        "engineeringPlan": prompt_job.get("_engineeringPlan"),
        "engineeringPlanPath": str(engineering_plan_path) if engineering_plan_path else None,
        "stdoutTail": stdout[-4000:],
        "stderrTail": stderr[-4000:],
    }


def run_codex_job(
    job: dict[str, Any],
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS,
    allow_full_access: bool = False,
) -> dict[str, Any]:
    """@brief Eski çağrı adıyla uyumluluk sağlar; gerçekte birleşik Agent Provider Runtime kullanılır."""
    return run_agent_job(job, runner=runner, timeout_seconds=timeout_seconds, allow_full_access=allow_full_access)


def _run_command(command: Sequence[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    """@brief Harici komutu çalıştırır; testlerde kolayca değiştirilebilir."""
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _run_command_with_runtime(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    job: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    """@brief Agent sürecini çalıştırır; heartbeat, lease ve iptal semantiğini yönetir."""
    runtime = job.get("_runtime") if isinstance(job.get("_runtime"), dict) else {}
    job_path = Path(str(runtime.get("jobPath")))
    runner_id = str(runtime.get("runnerId") or job.get("runnerId") or worker_id())
    lease_seconds = int(runtime.get("leaseSeconds") or DEFAULT_LEASE_SECONDS)
    heartbeat_interval = max(1.0, min(10.0, lease_seconds / 3))
    started_at = time.monotonic()
    next_heartbeat = 0.0
    stdout_path, stderr_path = log_paths_for(job_path.parent, job.get("id"))
    event_prefix = "agent" if job.get("executor") == "agent" else "codex"
    process_label = "Codex" if event_prefix == "codex" else "Agent"

    append_event(job_path.parent, job, f"{event_prefix}.started", f"{process_label} süreci başlatıldı", {"cwd": str(cwd), "stdout": str(stdout_path), "stderr": str(stderr_path)})
    ui_config = job.get("uiConfig") if isinstance(job.get("uiConfig"), dict) else {}
    knowledge = ui_config.get("knowledgeBase") if isinstance(ui_config.get("knowledgeBase"), dict) else {}
    child_env = os.environ.copy()
    if knowledge.get("officialApiDocsEnabled", True) is not True:
        child_env["SW_API_LOOKUP_NETWORK"] = "off"
    if knowledge.get("parallelApiFallbackEnabled", True) is not True:
        child_env["SW_API_LOOKUP_PARALLEL"] = "off"
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=child_env,
        )

        while process.poll() is None:
            now = time.monotonic()
            if now - started_at > timeout_seconds:
                terminate_process(process)
                append_event(job_path.parent, job, f"{event_prefix}.timeout", f"{process_label} yürütmesi zaman aşımına uğradı; sonlandırma istendi")
                raise TimeoutError(f"{process_label} yürütme zaman aşımı: {timeout_seconds}s")
            if now >= next_heartbeat:
                try:
                    refresh_job_heartbeat(job_path, runner_id, lease_seconds, f"{process_label} yürütülüyor; worker lease'i yeniledi.")
                except JobCancelled:
                    terminate_process(process)
                    append_event(job_path.parent, job, f"{event_prefix}.cancelled", f"İptal isteği alındı; {process_label} süreci sonlandırıldı")
                    raise
                next_heartbeat = now + heartbeat_interval
            time.sleep(0.25)

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
    completed = subprocess.CompletedProcess(list(command), process.returncode or 0, stdout=stdout, stderr=stderr)
    append_event(
        job_path.parent,
        job,
        f"{event_prefix}.completed",
        f"{process_label} süreci sonlandı",
        {"returnCode": completed.returncode},
    )
    return completed


def terminate_process(process: subprocess.Popen[str]) -> None:
    """@brief Alt süreci elden geldiğince sonlandırır ve kaynakları geri alır."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            text=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


MOCK_HANDLERS: Mapping[str, JobHandler] = {
    "create_shell": mock_create_shell,
    "import_model": mock_import_model,
    "delivery_package": mock_delivery_package,
}
DEFAULT_HANDLERS: Mapping[str, JobHandler] = {"dfm_review": run_dfm_review_job}


def _primary_capability(job: dict[str, Any]) -> str | None:
    """@brief Görevin bildirdiği ilk yetenek ID'sini alır (Execution Core bağlamı için)."""
    capabilities = job.get("capabilities")
    if isinstance(capabilities, list) and capabilities:
        return str(capabilities[0])
    return None


def _execute_handler_with_core(handler: JobHandler, kind: str, job: dict[str, Any], path: Path) -> dict[str, Any]:
    """@brief Handler çağrısını Execution Core ile sarmalar (uyumluluk öncelikli; istisnalar olduğu gibi yükseltilir)."""
    try:
        from core.execution import execute_with_core
    except Exception:
        # Execution Core kullanılamıyorsa doğrudan handler çağrısına geri dönülür; üretim davranışı değişmez.
        return handler(job)
    assessment = execute_with_core(
        handler=handler,
        handler_arg=job,
        run_id=str(job.get("id") or "unknown"),
        tool_name=str(kind),
        capability_id=_primary_capability(job),
        requires_review=False,
        trace_dir=path.parent,
        defer_completion=True,
    )
    job["executionAssessment"] = assessment.to_dict()
    if assessment.exception is not None:
        raise assessment.exception
    if not assessment.execution_result.success:
        message = assessment.execution_result.message or assessment.execution_result.error_code or "Handler yürütmesi başarısız"
        if isinstance(assessment.raw_result, dict) and assessment.raw_result.get("status") == "blocked":
            raise JobBlocked(message)
        raise RuntimeError(message)
    return assessment.raw_result


def _record_verification_assessment(path: Path, job: dict[str, Any], review: dict[str, Any]) -> None:
    """@brief Mevcut Reviewer Gate sonucunu Verification/Recovery Adapter ile standartlaştırır (sidecar; nihai durumu değiştirmez)."""
    try:
        from core.recovery import decide
        from core.verification import verify
    except Exception:
        return
    run_id = str(job.get("id") or "unknown")
    capability_id = _primary_capability(job)
    verification = verify(
        reviewer_result=review,
        capability_id=capability_id,
        trace_dir=path.parent,
        run_id=run_id,
    )
    job["verificationAssessment"] = verification.to_dict()
    if verification.status.value == "FAIL":
        review["status"] = "fail"
    elif verification.status.value in {"WARN", "BLOCKED"} or verification.manual_review_required:
        review["status"] = "warning"
    decision = decide(
        verification_result=verification.to_dict(),
        capability_id=capability_id,
        trace_dir=path.parent,
        run_id=run_id,
    )
    if decision is not None:
        job["recoveryDecision"] = decision.to_dict()


def process_job(
    path: Path,
    handlers: Mapping[str, JobHandler] | None = None,
    runner_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """@brief Bir queued görevi yürütür; nihai durumdaki görevler atlanır."""
    path = Path(path)
    job = read_job(path)
    if job.get("status") != "queued":
        return None

    active_handlers = handlers or DEFAULT_HANDLERS
    try:
        job_id = job.get("id")
        kind = job.get("kind")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("Görevde id eksik")
        if kind not in KNOWN_JOB_KINDS:
            raise ValueError(f"Bilinmeyen görev türü: {kind}")
        blocked_reasons = _capability_block_reasons(job)
        if blocked_reasons:
            message = "Görev yetenek kapısı tarafından engellendi: " + "; ".join(blocked_reasons)
            job["blockedReasons"] = blocked_reasons
            job["stage"] = "blocked"
            set_job_state(job, "blocked", int(job.get("progress") or 0), message)
            append_event(path.parent, job, "run.blocked", message, {"reasons": blocked_reasons})
            write_job(path, job)
            return job
        if job.get("executor") in {"codex", "agent"}:
            approval_reasons = require_policy_approval(job)
            if approval_reasons:
                return mark_approval_required(path, job, approval_reasons)
            executor_kind = "codex_task" if job.get("executor") == "codex" else "agent_task"
            if executor_kind not in active_handlers:
                flag = "--enable-codex" if executor_kind == "codex_task" else "--enable-agent"
                raise ValueError(f"Agent yürütücüsü etkin değil; worker'a {flag} ekleyin")
            kind = executor_kind

        if kind not in active_handlers:
            raise ValueError(f"Görev türü için handler yapılandırılmamış: {kind}")

        mark_job_claimed(job, runner_id or worker_id(), lease_seconds)
        set_job_state(job, "running", 12, "Worker görevi aldı; yerel CAD yürütme ortamı hazırlanıyor.")
        write_job(path, job)
        append_event(path.parent, job, "run.claimed", "Görev worker tarafından sahiplenildi")
        append_event(path.parent, job, "step.started", "Görev yürütmesi başladı")

        job["_runtime"] = {"jobPath": str(path), "runnerId": job.get("runnerId"), "leaseSeconds": lease_seconds}
        # Kanıt, yürütmeden önce worker tarafından toplanır ve tüm üretim arka uçlarını kapsar; handler'ın kendi bildirdiği tazelik taban çizgisine güvenilmez.
        baseline = None
        if job.get("executor", "mock") != "mock":
            base_dir = Path(str(job.get("cwd") or Path.cwd())).expanduser()
            baseline = _snapshot_cad_artifacts(_artifact_roots(job, base_dir))
            job["_runtime"]["artifactBaseline"] = baseline
        result = _execute_handler_with_core(active_handlers[kind], kind, job, path)
        if isinstance(result, dict) and baseline is not None:
            result["artifactBaseline"] = baseline
        if is_cancel_requested(path):
            raise JobCancelled("Görev için iptal istendi")
        job.pop("_runtime", None)
        job["result"] = result
        # Job 2.0 alan kanıtı üst düzeyde tutulur; böylece UI, CLI ve sonraki yeniden denemeler yürütücünün özel result'ını ayrıştırmak zorunda kalmaz.
        if isinstance(result, dict):
            for evidence_key in ("drawingEvidence", "bomEvidence", "dfmEvidence", "reviewFindings", "artifactRelations"):
                if evidence_key in result:
                    job[evidence_key] = result[evidence_key]
        ledger = write_artifact_ledger(path.parent, job, result)
        job["artifactLedgerPath"] = ledger["ledgerPath"]
        job["artifacts"] = ledger["artifacts"]
        append_event(path.parent, job, "artifact.ledger_written", "Teslimat defteri yazıldı", {"ledgerPath": ledger["ledgerPath"]})
        review = write_reviewer_gate(path.parent, ledger)
        if is_cancel_requested(path):
            raise JobCancelled("Görev için iptal istendi")
        job["reviewGate"] = review
        job["reviewGatePath"] = review["reviewPath"]
        append_event(path.parent, job, "review.gate_completed", "Reviewer Gate tamamlandı", {"status": review["status"], "reviewPath": review["reviewPath"]})
        _record_verification_assessment(path, job, review)
        if review["status"] == "fail":
            message = "Teslimat dosyası kontrolü geçemedi; görev teslim edilemez. İnceleme kaydını kontrol edip düzeltin."
            job["error"] = message
            set_job_state(job, "failed", 100, message)
            append_event(path.parent, job, "run.failed", message)
        else:
            message = str(result.get("message", "Görev tamamlandı"))
            if review["status"] == "warning":
                message = f"{message} Dosya düzeyi kontrolde uyarılar var; CAD yerel veya insan incelemesi hâlâ gerekli."
            domain_status, domain_message = _domain_evidence_status(result)
            status = domain_status or ("review_required" if review["status"] == "warning" else "passed")
            if domain_message:
                message = f"{message} {domain_message}。"
            if status == "blocked":
                job["blockedReasons"] = [domain_message or message]
                job["stage"] = "blocked"
            elif status == "failed":
                job["error"] = domain_message or message
            set_job_state(job, status, 100, message)
            event_name = "run.blocked" if status == "blocked" else "run.failed" if status == "failed" else "run.review_required" if status == "review_required" else "run.passed"
            append_event(path.parent, job, event_name, message)
    except JobCancelled as error:
        job.pop("_runtime", None)
        job["cancelRequested"] = True
        set_job_state(job, "cancelled", int(job.get("progress") or 0), str(error))
        append_event(path.parent, job, "run.cancelled", str(error))
    except JobBlocked as error:
        job.pop("_runtime", None)
        job["blockedReasons"] = [str(error)]
        job["stage"] = "blocked"
        set_job_state(job, "blocked", int(job.get("progress") or 0), str(error))
        append_event(path.parent, job, "run.blocked", str(error))
    except Exception as error:  # noqa: BLE001 - worker tek görev hatasını kuyruğa geri yazmalıdır; kuyruğun sessizce kesilmesine izin verilemez.
        job.pop("_runtime", None)
        job["error"] = str(error)
        set_job_state(job, "failed", 100, str(error))
        append_event(path.parent, job, "run.failed", str(error))

    assessment = job.get("executionAssessment")
    if isinstance(assessment, dict):
        # Kuyruk zamanlamadan sorumludur; Core nihai durumu, mevcut Review ve alan kanıtı tamamlandıktan sonra kaydedilmelidir.
        verification = job.get("verificationAssessment") or {}
        completed = job.get("status") == "passed" and verification.get("status") == "PASS" and not verification.get("manual_review_required")
        assessment["status"] = "completed" if completed else "failed" if job.get("status") == "failed" else "blocked"
        assessment["step"]["status"] = "success" if completed else assessment["status"]
    write_job(path, job)
    return job


def build_handlers(
    enable_codex: bool = False,
    enable_agent: bool = False,
    codex_full_access: bool = False,
    enable_mock: bool = False,
) -> Mapping[str, JobHandler]:
    """@brief CLI parametrelerine göre görev dağıtıcısını oluşturur."""
    handlers: dict[str, JobHandler] = dict(DEFAULT_HANDLERS)
    if enable_mock:
        handlers.update(MOCK_HANDLERS)
    if enable_codex:
        handlers["codex_task"] = lambda job: run_agent_job(job, allow_full_access=codex_full_access)
    if enable_agent:
        handlers["agent_task"] = lambda job: run_agent_job(job, allow_full_access=codex_full_access)
    return handlers


def process_queue(
    queue_dir: Path,
    limit: int | None = None,
    handlers: Mapping[str, JobHandler] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> list[dict[str, Any]]:
    """@brief Kuyruk dizinini tarar ve queued görevleri yürütür."""
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    recovered = recover_stale_jobs(queue_dir)
    processed: list[dict[str, Any]] = []
    runner_id = worker_id()
    last_error: str | None = None

    for path in sorted(queue_dir.glob("*.json")):
        if path.name in QUEUE_METADATA_FILES:
            continue
        if limit is not None and len(processed) >= limit:
            break
        try:
            job = read_job(path)
        except Exception as error:
            quarantine_bad_job(path, error)
            continue
        if job.get("status") in NON_EXECUTABLE_STATES or job.get("status") != "queued":
            continue
        lock_path = acquire_lock(path, runner_id, lease_seconds)
        if lock_path is None:
            continue
        try:
            result = process_job(path, handlers=handlers, runner_id=runner_id, lease_seconds=lease_seconds)
            if result is not None:
                processed.append(result)
                if result.get("status") == "failed":
                    last_error = str(result.get("error") or result.get("lastMessage") or "Görev başarısız")
        finally:
            release_lock(lock_path)
    write_worker_health(queue_dir, runner_id, processed_count=len(processed), recovered_count=recovered, last_error=last_error)
    return processed


def watch_queue(
    queue_dir: Path,
    interval_seconds: float = 1.0,
    handlers: Mapping[str, JobHandler] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    """@brief Kuyruk dizinini sürekli izler; ileride arka plan sürecine dönüştürülmeye uygundur."""
    runner_id = worker_id()
    while True:
        processed = process_queue(queue_dir, handlers=handlers, lease_seconds=lease_seconds)
        write_worker_health(queue_dir, runner_id, processed_count=len(processed))
        time.sleep(interval_seconds)


def main() -> int:
    """@brief Komut satırı girişi."""
    parser = argparse.ArgumentParser(description="CAD Studio yerel otomasyon kuyruğu worker'ı")
    parser.add_argument("--queue-dir", type=Path, default=default_tauri_queue_dir(), help="Kuyruk JSON dizini")
    parser.add_argument("--watch", action="store_true", help="Kuyruğu sürekli izle")
    parser.add_argument("--limit", type=int, default=None, help="Tek seferde işlenecek en fazla görev sayısı")
    parser.add_argument("--interval", type=float, default=1.0, help="İzleme yoklama aralığı (saniye)")
    parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS, help="Görev sahiplenme lease süresi (saniye)")
    parser.add_argument("--enable-codex", action="store_true", help="Worker'ın görevleri codex exec ile yürütmesine izin ver")
    parser.add_argument("--enable-agent", action="store_true", help="Worker'ın seçili yerel Agent Provider'ı çağırmasına izin ver")
    parser.add_argument("--codex-full-access", action="store_true", help="Codex'in danger-full-access sandbox kullanmasına izin ver")
    parser.add_argument("--enable-mock", action="store_true", help="Yalnızca geliştirme testi: gerçek CAD dosyası üretmeyen mock handler'ı etkinleştir")
    args = parser.parse_args()
    handlers = build_handlers(
        enable_codex=args.enable_codex,
        enable_agent=args.enable_agent,
        codex_full_access=args.codex_full_access,
        enable_mock=args.enable_mock,
    )

    if args.watch:
        watch_queue(args.queue_dir, interval_seconds=args.interval, handlers=handlers, lease_seconds=args.lease_seconds)
        return 0

    processed = process_queue(args.queue_dir, limit=args.limit, handlers=handlers, lease_seconds=args.lease_seconds)
    print(f"processed {len(processed)} job(s) from {args.queue_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
