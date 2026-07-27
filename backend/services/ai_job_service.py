"""
AI Test Generator — Job Servisi (Faz 1: Mobil)
CRUD + çalıştırma motoru + zamanlayıcı.
"""
import asyncio
import json as _json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from models.db_models import (
    AiJob, AiJobScenario, AiJobDevice, AiJobSchedule,
    AiJobRun, AiJobRunResult,
)


class JobAlreadyRunningError(Exception):
    pass


# ══════════════════════════════════════════════════════════════
# GUVENLIK: SENARYO KLASOR ADI DOGRULAMA
# ══════════════════════════════════════════════════════════════
# Senaryo klasörleri diskte ai_scenarios/{folder} olarak tutuluyor ve klasör adı
# ai_test_generator_router._sanitize_folder_name() ile üretiliyor (yalnız \w, - ve
# boşluk→_ ). Job kaydında ise klasör adı kullanıcıdan gelen serbest bir string;
# doğrulanmazsa "../../baska_kullanici/..." gibi bir değerle workspace dışına
# çıkılabilir (path traversal). Bu yüzden kabul anında (create_job/update_job)
# aynı desene uymayan değerler reddedilir.
_SAFE_FOLDER_RE = re.compile(r'^[\w-]{1,64}$', re.UNICODE)


def _validate_scenario_folders(folders: list[str]) -> list[str]:
    """Klasör adlarını doğrular; güvenli olmayan değerde ValueError fırlatır."""
    clean: list[str] = []
    for f in folders:
        s = (f or "").strip()
        if not _SAFE_FOLDER_RE.match(s):
            raise ValueError(f"Geçersiz senaryo klasör adı: {f!r}")
        clean.append(s)
    return clean


_WEB_BROWSERS = {"chrome", "firefox", "edge"}


def _normalize_device_ids(platform: str, device_ids: list[str]) -> list[tuple[str, str]]:
    """Platforma gore (device_id, device_name) ciftleri uretir.

    - mobile: ADB serial'i hem id hem ad olarak kullanilir, en az bir tane sarttir.
    - web: sadece {chrome, firefox, edge} kabul edilir (kucuk harfe normalize edilir),
      en az bir tane sarttir.
    - desktop: kullanicidan device_ids gelse bile yok sayilir — global desktop kilidi
      yuzunden paralellik yok, tek sabit sozde-birim doner.
    """
    if platform == "desktop":
        return [("desktop", "Masaüstü")]

    if platform == "web":
        clean: list[tuple[str, str]] = []
        for d in device_ids:
            name = (d or "").strip().lower()
            if name not in _WEB_BROWSERS:
                raise ValueError(f"Geçersiz tarayıcı: {d!r}")
            clean.append((name, name))
        if not clean:
            raise ValueError("En az bir tarayıcı seçilmeli")
        return clean

    # mobile (varsayilan)
    if not device_ids:
        raise ValueError("En az bir cihaz seçilmeli")
    return [(d, d) for d in device_ids]


def _build_job_generate_request(
    platform: str, steps_list: list, params: dict, device_id: str, system_port: int | None,
):
    """Job hucresi icin GenerateRequest olusturur. Salt Python — DB/network/async yok,
    bu yuzden bagimsiz test edilebilir. GenerateRequest import'u fonksiyon ici (lazy):
    ai_test_generator_router agir bir modul, module-level import ai_job_service'i
    gereksiz yere ona baglar (bkz. _generate_cell_script'teki ayni desen)."""
    from routers.ai_test_generator_router import GenerateRequest

    if platform == "mobile":
        return GenerateRequest(
            steps_list=steps_list, platform="mobile", device_id=device_id, system_port=system_port,
            app_package=params.get("app_package", ""), app_activity=params.get("app_activity", ""),
            appium_url=params.get("appium_url") or "http://localhost:4723",
        )
    if platform == "web":
        return GenerateRequest(
            steps_list=steps_list, platform="web", browser=device_id,
            target_url=params.get("target_url", ""),
        )
    if platform == "desktop":
        return GenerateRequest(
            steps_list=steps_list, platform="desktop",
            app_path=params.get("app_path", ""), window_title=params.get("window_title", ""),
            reuse_instance=params.get("reuse_instance", True),
        )
    raise ValueError(f"Bilinmeyen platform: {platform!r}")


# ══════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════

def create_job(
    db: Session, user_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None, platform: str = "mobile",
) -> AiJob:
    scenario_folders = _validate_scenario_folders(scenario_folders)
    device_pairs = _normalize_device_ids(platform, device_ids)
    job = AiJob(user_id=user_id, name=name, platform=platform)
    db.add(job)
    db.commit()
    db.refresh(job)

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job.id, scenario_folder=folder))
    for device_id, device_name in device_pairs:
        db.add(AiJobDevice(job_id=job.id, device_id=device_id, device_name=device_name))
    if schedule:
        db.add(AiJobSchedule(
            job_id=job.id,
            schedule_type=schedule["schedule_type"],
            run_at=datetime.fromisoformat(schedule["run_at"]),
            enabled=True,
        ))
    db.commit()
    db.refresh(job)
    return job


def list_jobs(db: Session, user_id: int, platform: str | None = None) -> list[AiJob]:
    q = db.query(AiJob).filter(AiJob.user_id == user_id)
    if platform:
        q = q.filter(AiJob.platform == platform)
    return q.order_by(AiJob.created_at.desc()).all()


def get_job(db: Session, job_id: int, user_id: int) -> AiJob | None:
    return db.query(AiJob).filter(AiJob.id == job_id, AiJob.user_id == user_id).first()


def update_job(
    db: Session, job_id: int, name: str,
    scenario_folders: list[str], device_ids: list[str],
    schedule: dict | None, platform: str = "mobile",
) -> AiJob:
    scenario_folders = _validate_scenario_folders(scenario_folders)
    device_pairs = _normalize_device_ids(platform, device_ids)
    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    job.name = name
    job.platform = platform

    db.query(AiJobScenario).filter(AiJobScenario.job_id == job_id).delete()
    db.query(AiJobDevice).filter(AiJobDevice.job_id == job_id).delete()
    db.query(AiJobSchedule).filter(AiJobSchedule.job_id == job_id).delete()

    for folder in scenario_folders:
        db.add(AiJobScenario(job_id=job_id, scenario_folder=folder))
    for device_id, device_name in device_pairs:
        db.add(AiJobDevice(job_id=job_id, device_id=device_id, device_name=device_name))
    if schedule:
        db.add(AiJobSchedule(
            job_id=job_id,
            schedule_type=schedule["schedule_type"],
            run_at=datetime.fromisoformat(schedule["run_at"]),
            enabled=True,
        ))

    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: int) -> None:
    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    if job:
        db.delete(job)
        db.commit()


def job_to_dict(job: AiJob) -> dict:
    sched = job.schedule[0] if job.schedule else None
    return {
        "id": job.id,
        "name": job.name,
        "platform": job.platform,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "scenarios": [s.scenario_folder for s in job.scenarios],
        "devices": [{"device_id": d.device_id, "device_name": d.device_name} for d in job.devices],
        "schedule": ({
            "schedule_type": sched.schedule_type,
            # run_at DB'de UTC duvar saati olarak (naive) tutuluyor. Sonuna "Z"
            # eklenmezse tarayıcıdaki new Date(...) bunu YEREL saat sanar ve
            # gösterim UTC farkı kadar kayar.
            "run_at": sched.run_at.isoformat() + "Z",
            "enabled": sched.enabled,
            "last_triggered_at": sched.last_triggered_at.isoformat() if sched.last_triggered_at else None,
        } if sched else None),
    }


# ══════════════════════════════════════════════════════════════
# CANLI GUNCELLEME PUB/SUB (in-memory, run_id -> Queue listesi)
# ══════════════════════════════════════════════════════════════

_run_event_queues: dict[int, list[asyncio.Queue]] = {}
# cell_id -> süreç tutamacı. İki farklı tip olabilir (bkz. _start_cell_process):
# asyncio.subprocess.Process veya _ClassicProcHandle. Her ikisi de aynı arayüzü
# sunar: .returncode (çalışıyorsa None) ve .terminate().
_active_procs: dict[int, object] = {}
_stopped_runs: set[int] = set()

# ── UiAutomator2 systemPort ayrımı ─────────────────────────────
# Aynı Appium sunucusunda eşzamanlı oturumlar aynı systemPort'u paylaşamaz.
# Port tahsisi KOŞUMA değil CİHAZA bağlıdır: koşum başına (base + slot) şeklinde
# hesaplansaydı eşzamanlı iki koşum (ör. aynı turda tetiklenen iki zamanlanmış job
# ya da zamanlanmış bir koşumla çakışan manuel koşum) FARKLI cihazlar için AYNI
# portu (ikisi de slot 0 → 8200) tahsis edip çakışırdı. Bu yüzden atama process
# ömrü boyunca global ve cihaz kimliğine göre kalıcıdır.
# Taban 8200 DEĞİL 8201'dir: systemPort verilmeyen akışlar (manuel /execute) için
# UiAutomator2 varsayılanı 8200'dür; havuzu 8201'den başlatmak job hücrelerinin
# ilgisiz bir manuel koşumla çakışmasını da engeller.
_SYSTEM_PORT_BASE = 8201
_SYSTEM_PORT_RANGE = 100
_device_system_ports: dict[str, int] = {}


def _acquire_system_port(device_id: str) -> int:
    """Cihaza kalıcı bir systemPort atar (process ömrü boyunca aynı kalır).

    Aynı cihaz her zaman aynı portu alır (hata ayıklamayı öngörülebilir kılar ve
    hücre bitince "port serbest bırakma" ihtiyacını ortadan kaldırır: aynı cihazın
    hücreleri zaten sırayla koşuyor). Farklı cihazlar asla aynı portu almaz.

    Fonksiyon içinde `await` YOKTUR; tek thread'li asyncio altında kontrol-ve-atama
    bölümü bölünemez, bu yüzden ayrıca kilide gerek kalmaz.
    """
    port = _device_system_ports.get(device_id)
    if port is not None:
        return port
    used = set(_device_system_ports.values())
    for candidate in range(_SYSTEM_PORT_BASE, _SYSTEM_PORT_BASE + _SYSTEM_PORT_RANGE):
        if candidate not in used:
            _device_system_ports[device_id] = candidate
            return candidate
    # Havuz tükendi (>100 farklı cihaz): deterministik bir değere düş. Teorik olarak
    # çakışabilir ama bu ölçekte tek bir Appium sunucusu zaten yetmez.
    fallback = _SYSTEM_PORT_BASE + (abs(hash(device_id)) % _SYSTEM_PORT_RANGE)
    _device_system_ports[device_id] = fallback
    return fallback


def subscribe(run_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _run_event_queues.setdefault(run_id, []).append(q)
    return q


def unsubscribe(run_id: int, q: asyncio.Queue) -> None:
    subs = _run_event_queues.get(run_id, [])
    if q in subs:
        subs.remove(q)
    if run_id in _run_event_queues and not _run_event_queues[run_id]:
        _run_event_queues.pop(run_id, None)


async def _publish(run_id: int, event: dict) -> None:
    for q in list(_run_event_queues.get(run_id, [])):
        await q.put(event)


def stop_run(run_id: int) -> None:
    """Kuyruktaki hücrelerin başlamasını engeller, çalışanları terminate eder."""
    _stopped_runs.add(run_id)
    from database import SessionLocal
    db = SessionLocal()
    try:
        cells = db.query(AiJobRunResult).filter(
            AiJobRunResult.job_run_id == run_id,
            AiJobRunResult.status.in_(["queued", "running"]),
        ).all()
        for c in cells:
            proc = _active_procs.get(c.id)
            # Tutamaç asyncio.subprocess.Process ya da _ClassicProcHandle olabilir;
            # ikisinde de süreç hâlâ çalışıyorsa returncode None'dır.
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                except OSError:
                    # ProcessLookupError (POSIX) / PermissionError (Windows, süreç
                    # aramızda sonlandıysa) — yarış durumu, yok sayılır.
                    pass
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════
# TEK HUCRE: SCRIPT URETIMI + SUBPROCESS KOSUMU
# ══════════════════════════════════════════════════════════════

async def _generate_cell_script(
    platform: str, steps_data: dict, device_id: str, system_port: int | None = None,
) -> str:
    """steps.json icerigini hedef birime (cihaz/tarayici/masaustu) gore script'e derler
    (kayitli script.py KULLANILMAZ). system_port yalnizca mobile'da anlamlidir."""
    from routers.ai_test_generator_router import (
        StepItem, _generate_steps, _build_mobile_template, _build_web_template, _build_desktop_template,
    )
    params = steps_data.get("params", {}) or {}
    steps_list = [StepItem(**s) for s in steps_data.get("steps", [])]
    req = _build_job_generate_request(platform, steps_list, params, device_id, system_port)
    steps_code, _report = await _generate_steps(req)
    build_fn = {
        "mobile": _build_mobile_template,
        "web": _build_web_template,
        "desktop": _build_desktop_template,
    }[platform]
    return build_fn(req, steps_code)


class _ClassicProcHandle:
    """subprocess.Popen'i asyncio.subprocess.Process ile AYNI arayüze sarar.

    stop_run tek bir arayüz üzerinden çalışabilsin diye: .returncode (çalışıyorsa
    None) ve .terminate(). Popen.returncode yalnızca poll()/wait() sonrası güncellenir,
    bu yüzden property içinde poll() çağrılır.
    """

    __slots__ = ("_p",)

    def __init__(self, popen: subprocess.Popen):
        self._p = popen

    @property
    def returncode(self) -> int | None:
        return self._p.poll()

    def terminate(self) -> None:
        self._p.terminate()


# asyncio.create_subprocess_exec bu event loop'ta desteklenmiyorsa (bkz. aşağıdaki
# açıklama) her hücrede yeniden denemeyelim: ilk NotImplementedError'da işaretlenir.
_async_subprocess_unsupported = False


async def _start_cell_process(tmp: str):
    """Hücre script'i için subprocess başlatır ve (tutamaç, satırlar, bekle) döndürür.

    HIZLI YOL — asyncio.create_subprocess_exec: burada bilerek subprocess.Popen +
    run_in_executor(None, readline) KULLANILMAZ. run_in_executor(None, ...) asyncio'nun
    paylaşılan varsayılan ThreadPoolExecutor'ını kullanır; her hücre bir thread'i tüm
    ömrü boyunca işgal eder ve yeterli sayıda eşzamanlı hücrede havuz tükenerek
    uygulamanın geri kalanını (ör. "adb devices") bloklar.

    YEDEK YOL — Popen + run_in_executor: Windows'ta SelectorEventLoop altında
    asyncio.create_subprocess_exec NotImplementedError fırlatır. uvicorn reload=True
    (projede `DEV_RELOAD=1 python main.py`) Windows'ta WindowsSelectorEventLoopPolicy'yi
    zorlar; bu modda hızlı yol HER hücrede patlar ve tüm özellik bozuk görünürdü.
    Bu durumda eski thread havuzlu yönteme düşülür — geliştirme modunda daha az
    verimli ama çalışır.

    Dönüş: (handle, lines, wait)
      handle: _active_procs'a konacak, .returncode/.terminate() sunan nesne
      lines : ham (bytes) satırları veren async generator
      wait  : çıkış kodunu döndüren coroutine fonksiyonu
    """
    global _async_subprocess_unsupported

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    if not _async_subprocess_unsupported:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                limit=1024 * 1024,   # uzun satırlar readline limitine takılmasın
                creationflags=creationflags,
            )
        except NotImplementedError:
            _async_subprocess_unsupported = True
            print("[AI-JOB] asyncio subprocess bu event loop'ta desteklenmiyor "
                  "(muhtemelen Windows + reload/SelectorEventLoop); "
                  "thread havuzlu yedek yola geçiliyor.")
        else:
            async def _async_lines():
                while True:
                    try:
                        line = await proc.stdout.readline()
                    except ValueError:
                        # Satır limitin üstünde — StreamReader veriyi tüketip ValueError
                        # atar, sonsuz döngü riski yok; bu satırı atlayıp devam ediyoruz.
                        continue
                    if not line:
                        break
                    yield line

            return proc, _async_lines(), proc.wait

    popen = subprocess.Popen(
        [sys.executable, tmp],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=creationflags,
    )
    loop = asyncio.get_running_loop()

    async def _classic_lines():
        while True:
            line = await loop.run_in_executor(None, popen.stdout.readline)
            if not line:
                break
            yield line

    async def _classic_wait():
        code = await loop.run_in_executor(None, popen.wait)
        try:
            popen.stdout.close()
        except Exception:
            pass
        return code

    return _ClassicProcHandle(popen), _classic_lines(), _classic_wait


async def _run_cell(script: str, cell_id: int) -> dict:
    """Script'i bagimsiz bir subprocess olarak calistirir, adim sonuclarini toplar.
    /execute endpoint'inden bagimsizdir (SSE yok) — job motoru paralel hucreler icin bunu kullanir."""
    step_outcomes: dict[int, str] = {}
    terminal_lines: list[str] = []

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8", prefix="ai_job_cell_"
    ) as f:
        f.write(script)
        tmp = f.name

    proc, lines, wait = await _start_cell_process(tmp)
    _active_procs[cell_id] = proc
    exit_code = -1
    try:
        # Ayrıştırma döngüsü TEK: satır kaynağı hangi yoldan geldiğinden bağımsız.
        async for line in lines:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text.startswith("STEP_DONE:"):
                idx_s = text.split(":", 1)[1].strip()
                try: step_outcomes[int(idx_s)] = "pass"
                except ValueError: pass
            elif text.startswith("STEP_FAIL:"):
                idx_s = text.split(":", 1)[1].strip()
                try: step_outcomes[int(idx_s)] = "fail"
                except ValueError: pass
            elif not text.startswith("STEP_START:"):
                terminal_lines.append(text)

        exit_code = await wait()
    finally:
        _active_procs.pop(cell_id, None)
        try:
            os.unlink(tmp)
        except Exception:
            pass

    if exit_code == 0 and all(v == "pass" for v in step_outcomes.values()):
        status = "pass"
    elif exit_code == 0:
        status = "fail"
    else:
        status = "error"

    return {
        "status": status,
        "exit_code": exit_code,
        "steps": [{"index": i, "status": v} for i, v in sorted(step_outcomes.items())],
        "terminal": "\n".join(terminal_lines[-200:]),
    }


# ══════════════════════════════════════════════════════════════
# HUCRE KOORDINASYONU + RUN_JOB MOTORU
# ══════════════════════════════════════════════════════════════

async def _execute_cell(
    run_id: int, cell_id: int, steps_data: dict | None,
    device_id: str, system_port: int | None, platform: str,
) -> None:
    """Bu fonksiyon HİÇBİR istisnayı çağırana sızdırmamalıdır: run_job bunları
    asyncio.gather(...) ile paralel bekliyor; burada yakalanmayan bir hata gather'ı
    ve dolayısıyla tüm run_job'u kesintiye uğratıp AiJobRun'ı 'running' durumunda
    kilitli bırakır. Bu yüzden dış try/except, script üretimi/koşumu için zaten var
    olan iç try/except'in ÜSTÜNE, DB sorgusu/commit/_publish çağrılarını da kapsayacak
    şekilde eklenmiştir."""
    db = None
    try:
        from database import SessionLocal
        db = SessionLocal()
        try:
            cell = db.query(AiJobRunResult).filter(AiJobRunResult.id == cell_id).first()
            if not cell:
                return

            if run_id in _stopped_runs:
                cell.status = "error"
                cell.log_json = _json.dumps({"error": "Koşum durduruldu"})
                db.commit()
                await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
                return

            cell.status = "running"
            cell.started_at = datetime.utcnow()
            db.commit()
            await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "running"})

            if not steps_data:
                cell.status = "error"
                cell.ended_at = datetime.utcnow()
                cell.log_json = _json.dumps({"error": "Senaryo dosyası okunamadı"})
                db.commit()
                await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
                return

            try:
                script = await _generate_cell_script(platform, steps_data, device_id, system_port)
                result = await _run_cell(script, cell_id)
                cell.status = result["status"]
                cell.log_json = _json.dumps(result)
            except Exception as e:
                cell.status = "error"
                cell.log_json = _json.dumps({"error": str(e)})

            cell.ended_at = datetime.utcnow()
            db.commit()
            await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": cell.status})
        except Exception as outer_e:
            # Sorgu/status="running" commit/_publish gibi iç try/except'in DIŞINDA kalan
            # bir adım patladı. Hücreyi en iyi çaba (best-effort) ile "error"a çek; bu
            # fallback'in kendisi de patlarsa yut — hiçbir şekilde yukarı sızdırma.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                cell = db.query(AiJobRunResult).filter(AiJobRunResult.id == cell_id).first()
                if cell:
                    cell.status = "error"
                    cell.ended_at = datetime.utcnow()
                    cell.log_json = _json.dumps({"error": f"Hücre çalıştırılamadı: {outer_e}"})
                    db.commit()
            except Exception:
                pass
            try:
                await _publish(run_id, {"type": "cell_update", "cell_id": cell_id, "status": "error"})
            except Exception:
                pass
    except Exception:
        # SessionLocal() açılışı bile başarısız olursa buraya düşer; bu fonksiyon için
        # "hiçbir istisna sızdırma" garantisini korumak amacıyla yutulur. _run_job_cells
        # kendi try/finally'sinde AiJobRun'ı yine de terminal bir duruma taşıyacaktır.
        pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _read_scenario_steps(ws_local_path: str, folder: str) -> dict | None:
    """ai_scenarios/{folder}/steps.json okur.

    Savunma amaçlı ikinci katman: klasör adları create_job/update_job'da zaten
    doğrulanıyor, burada ayrıca çözümlenmiş yolun ai_scenarios tabanının ALTINDA
    kaldığı doğrulanır (eski kayıtlar / DB'ye başka yoldan girmiş değerler için)."""
    try:
        base = (Path(ws_local_path) / "ai_scenarios").resolve()
        steps_file = (base / folder / "steps.json").resolve()
        if base not in steps_file.parents:
            print(f"[AI-JOB] Güvenli olmayan senaryo klasörü atlandı: {folder!r}")
            return None
        if not steps_file.exists():
            return None
        return _json.loads(steps_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[AI-JOB] Senaryo okunamadı ({folder!r}): {e}")
        return None


async def _finalize_run(run_id: int, interrupted: bool) -> None:
    """AiJobRun'ı HER koşulda terminal duruma taşır ve run_completed yayınlar.

    Kendi DB oturumunu açar (arka plan görevinden çağrıldığı için istek kapsamındaki
    session artık kapalı olabilir) ve hiçbir istisna sızdırmaz."""
    from database import SessionLocal
    db = None
    passed = failed = total = 0
    status = "interrupted" if interrupted else "completed"
    try:
        db = SessionLocal()
        run = db.query(AiJobRun).filter(AiJobRun.id == run_id).first()
        if run is not None:
            try:
                results = db.query(AiJobRunResult).filter(AiJobRunResult.job_run_id == run_id).all()
                run.passed_cells = sum(1 for r in results if r.status == "pass")
                run.failed_cells = sum(1 for r in results if r.status in ("fail", "error"))
            except Exception:
                # Tally'nin kendisi patladı — run'ı yine de "running"da bırakma.
                status = "interrupted"
            run.status = status
            run.ended_at = datetime.utcnow()
            try:
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            passed, failed, total = run.passed_cells or 0, run.failed_cells or 0, run.total_cells or 0
    except Exception as e:
        print(f"[AI-JOB] run {run_id} sonlandırılamadı: {e}")
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    try:
        await _publish(run_id, {
            "type": "run_completed", "run_id": run_id,
            "passed": passed, "failed": failed, "total": total,
        })
    except Exception:
        pass


async def _run_job_cells(
    run_id: int, device_groups: list[list[dict]], scenario_data: dict[str, dict], platform: str,
) -> None:
    """FAZ 2 (arka plan): hücreleri koşturur ve run'ı sonlandırır.

    device_groups: her eleman TEK bir cihaza/tarayıcıya ait hücre listesidir. Gruplar
    birbirine paralel, grup İÇİ hücreler ise SIRAYLA koşar. Desktop'ta grup sayısı
    her zaman 1'dir (tek sözde-birim) — bu yüzden desktop zaten doğal olarak tam
    sıralı çalışır; global _get_desktop_lock() burada AYRICA tutulur ki bu run
    sürerken manuel bir "Test Et" çalıştırması (AI Test Generator sayfası) veya
    başka bir desktop job'ı araya giremesin.

    Bu fonksiyon asyncio.create_task ile fire-and-forget çağrıldığı için HİÇBİR
    istisnayı dışarı sızdırmamalıdır (aksi halde "Task exception was never retrieved").
    """
    interrupted = False
    desktop_lock = None
    lock_held = False
    try:
        if platform == "desktop":
            from routers.ai_test_generator_router import _get_desktop_lock
            desktop_lock = _get_desktop_lock()
            try:
                await asyncio.wait_for(desktop_lock.acquire(), timeout=30)
                lock_held = True
            except asyncio.TimeoutError:
                raise RuntimeError("Başka bir desktop testi çalışıyor, koşum iptal edildi")

        async def _device_sequence(cells: list[dict]) -> None:
            for c in cells:
                await _execute_cell(
                    run_id, c["cell_id"], scenario_data.get(c["scenario_folder"]),
                    c["device_id"], c["system_port"], platform,
                )

        await asyncio.gather(*[_device_sequence(g) for g in device_groups])
    except Exception as e:
        interrupted = True
        print(f"[AI-JOB] run {run_id} koşumu kesintiye uğradı: {e}")
    finally:
        # Yalnizca BU koşumun gerçekten aldığı kilit serbest bırakılır — .locked()
        # kontrolü kilit SAHİPLİĞİNİ bilmez, başka bir tutucunun kilidini serbest
        # bırakabilirdi (ör. acquire() beklerken bu görev iptal edilirse).
        if lock_held:
            try:
                desktop_lock.release()
            except RuntimeError:
                pass
        _stopped_runs.discard(run_id)
        try:
            await _finalize_run(run_id, interrupted)
        except Exception as e:
            print(f"[AI-JOB] run {run_id} finalize hatası: {e}")


async def run_job(job_id: int, db: Session, trigger_type: str = "manual") -> int:
    """FAZ 1 (hızlı): doğrulama + AiJobRun/hücre kayıtları + run_started yayını.

    Hücrelerin asıl koşumu asyncio.create_task ile ARKA PLANDA sürer; bu fonksiyon
    run_id'yi neredeyse anında döndürür. Böylece HTTP yanıtı hemen döner, frontend
    WebSocket'e bağlanıp canlı matrisi ve "Durdur" butonunu görebilir; zamanlayıcı da
    bir job'ı beklemeden diğer zamanı gelmiş job'lara geçer.

    NOT: Buradaki `db` istek kapsamlı bir session'dır (FastAPI yanıt dönünce kapatır),
    bu yüzden arka plan fazı ASLA bu session'ı kullanmaz — _execute_cell ve
    _finalize_run kendi SessionLocal()'larını açar.
    """
    from routers.ai_test_generator_router import _get_user_workspace

    job = db.query(AiJob).filter(AiJob.id == job_id).first()
    if not job:
        raise ValueError("Job bulunamadı")

    already = db.query(AiJobRun).filter(AiJobRun.job_id == job_id, AiJobRun.status == "running").first()
    if already:
        raise JobAlreadyRunningError(f"Job {job_id} zaten çalışıyor (run_id={already.id})")

    if job.platform == "desktop":
        from routers.ai_test_generator_router import _get_desktop_lock
        if _get_desktop_lock().locked():
            raise JobAlreadyRunningError("Başka bir desktop testi şu anda çalışıyor, lütfen bekleyin")

    scenario_folders = [s.scenario_folder for s in job.scenarios]
    devices = [(d.device_id, d.device_name) for d in job.devices]
    if not scenario_folders or not devices:
        raise ValueError("Job'da senaryo veya cihaz tanımlı değil")

    ws = _get_user_workspace(job.user_id, db)
    if not ws:
        raise ValueError("Kullanıcının git workspace'i bulunamadı")

    run = AiJobRun(
        job_id=job_id, started_at=datetime.utcnow(), status="running",
        trigger_type=trigger_type, total_cells=len(scenario_folders) * len(devices),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    # Bu noktadan sonra AiJobRun DB'de status="running". Faz 1'in geri kalanında bir
    # hata olursa run "running"a kilitli kalmasın diye _finalize_run ile terminal
    # duruma taşınır ve hata yukarı fırlatılır (router 400/500'e çevirir).
    try:
        ws_path = ws.local_path
        scenario_data: dict[str, dict] = {}
        for folder in scenario_folders:
            data = _read_scenario_steps(ws_path, folder)
            # Senaryonun kaydedilmiş platformu job'un platformuyla eşleşmiyorsa
            # ATLA: aksi halde ör. bir web senaryosunun boş app_path/window_title'ı
            # bir desktop hücresine sızar ve _build_desktop_template boş
            # _WINDOW_TITLE ile TAM EKRAN eşleşme/tıklama yapar (final review bulgusu).
            if data is not None and data.get("platform") == job.platform:
                scenario_data[folder] = data

        cells: list[AiJobRunResult] = []
        for folder in scenario_folders:
            data = scenario_data.get(folder)
            name = data.get("name", folder) if data else folder
            for device_id, device_name in devices:
                cell = AiJobRunResult(
                    job_run_id=run_id, scenario_folder=folder, scenario_name=name,
                    device_id=device_id, device_name=device_name or device_id, status="queued",
                )
                db.add(cell)
                cells.append(cell)
        db.commit()
        for c in cells:
            db.refresh(c)

        # Hücreleri cihaza göre grupla (cihaz sırası korunur)
        device_groups: list[list[dict]] = []
        group_index: dict[str, int] = {}
        for c in cells:
            plan = {
                "cell_id": c.id,
                "scenario_folder": c.scenario_folder,
                "device_id": c.device_id,
                # Port yalnizca mobile'da anlamlidir (UiAutomator2 systemPort). Web/desktop
                # icin gereksiz port tahsis etmeyelim (bkz. _acquire_system_port).
                "system_port": _acquire_system_port(c.device_id) if job.platform == "mobile" else None,
            }
            if c.device_id not in group_index:
                group_index[c.device_id] = len(device_groups)
                device_groups.append([])
            device_groups[group_index[c.device_id]].append(plan)

        await _publish(run_id, {"type": "run_started", "run_id": run_id, "total": len(cells)})

        # FAZ 2: arka plana devret — çağıran (router/zamanlayıcı) beklemez.
        asyncio.create_task(_run_job_cells(run_id, device_groups, scenario_data, job.platform))
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        _stopped_runs.discard(run_id)
        await _finalize_run(run_id, interrupted=True)
        raise

    return run_id


def list_runs(db: Session, job_id: int) -> list[AiJobRun]:
    return db.query(AiJobRun).filter(AiJobRun.job_id == job_id).order_by(AiJobRun.started_at.desc()).all()


def get_run(db: Session, run_id: int) -> AiJobRun | None:
    return db.query(AiJobRun).filter(AiJobRun.id == run_id).first()


def run_to_dict(run: AiJobRun, include_cells: bool = False) -> dict:
    d = {
        "id": run.id,
        "job_id": run.job_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "total_cells": run.total_cells,
        "passed_cells": run.passed_cells,
        "failed_cells": run.failed_cells,
    }
    if include_cells:
        d["cells"] = [
            {
                "id": c.id,
                "scenario_folder": c.scenario_folder,
                "scenario_name": c.scenario_name,
                "device_id": c.device_id,
                "device_name": c.device_name,
                "status": c.status,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "ended_at": c.ended_at.isoformat() if c.ended_at else None,
                "log": _json.loads(c.log_json) if c.log_json else None,
            }
            for c in run.results
        ]
    return d


# ══════════════════════════════════════════════════════════════
# ZAMANLAYICI (main.py lifespan'de asyncio.create_task ile başlatılır)
# ══════════════════════════════════════════════════════════════

def cleanup_interrupted_runs() -> None:
    """Sunucu yeniden başlarken yarım kalan koşumları 'interrupted' işaretler."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        stuck_runs = db.query(AiJobRun).filter(AiJobRun.status == "running").all()
        for r in stuck_runs:
            r.status = "interrupted"
            r.ended_at = datetime.utcnow()
        db.query(AiJobRunResult).filter(
            AiJobRunResult.status.in_(["queued", "running"])
        ).update({"status": "error"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _advance_schedule(sched: AiJobSchedule, now: datetime) -> None:
    """Tetiklenen bir zamanlamayı BİR SONRAKİ gelecek zamana taşır.

    Sunucu uzun süre kapalı kaldıysa (ya da run_at bir şekilde eskidiyse) tek tek
    ilerletmek her 30sn'lik turda bir koşum başlatır (30 gün geride kalan bir daily
    zamanlama 30 koşum tetikler). Bu yüzden kaçırılan TÜM aralıklar tek adımda atlanır.
    """
    if sched.schedule_type == "once":
        sched.enabled = False
        return
    delta = timedelta(days=1) if sched.schedule_type == "daily" else (
        timedelta(days=7) if sched.schedule_type == "weekly" else None
    )
    if delta is None:
        return
    while sched.run_at <= now:
        sched.run_at = sched.run_at + delta


async def ai_job_scheduler_loop() -> None:
    """30sn'de bir zamanı gelmis job'lari tetikler. main.py'deki _session_idle_reaper deseniyle ayni."""
    from database import SessionLocal

    while True:
        await asyncio.sleep(30)
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            due = db.query(AiJobSchedule).filter(
                AiJobSchedule.enabled == True,   # noqa: E712
                AiJobSchedule.run_at <= now,
            ).all()
            for sched in due:
                try:
                    # run_job artık hücreleri arka planda koşturur ve run_id'yi hemen
                    # döndürür → bir job'ın bitmesi beklenmeden diğer zamanı gelmiş
                    # job'lar tetiklenir.
                    await run_job(sched.job_id, db, trigger_type="scheduled")
                except Exception as e:
                    print(f"[AI-JOB-SCHEDULER] job {sched.job_id} tetiklenemedi: {e}")

                sched.last_triggered_at = now
                _advance_schedule(sched, now)
                db.commit()
        except Exception as e:
            print(f"[AI-JOB-SCHEDULER] döngü hatası: {e}")
        finally:
            db.close()
