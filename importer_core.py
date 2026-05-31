# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

from main import ConnectionConfig, IntegrationalServiceSession

from import_photos_group import (
    PHOTO_EXTENSIONS,
    parse_fio_from_filename,
    get_temp_orgunit_id,
    get_email_template_id,
    get_access_groups,
    process_student_file,
    write_log,
)


@dataclass(frozen=True)
class PhotoTask:
    group_number: str
    path: Path


def scan_photo_files(base_root: Path) -> list[PhotoTask]:
    """
    Поддерживает:
      1) .../<группа>/Студент/*.jpg
      2) .../<группа>/*.jpg  (fallback)
    """
    tasks: list[PhotoTask] = []
    if not base_root.is_dir():
        return tasks

    group_dirs = sorted([d for d in base_root.iterdir() if d.is_dir()], key=lambda p: p.name)
    for group_dir in group_dirs:
        group_number = group_dir.name
        students_dir = group_dir / "Студент"
        photo_dir = students_dir if students_dir.is_dir() else group_dir

        for p in photo_dir.iterdir():
            if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS:
                tasks.append(PhotoTask(group_number=group_number, path=p))

    return tasks


def check_connection(config_path: Path) -> tuple[bool, str]:
    try:
        cfg = ConnectionConfig(str(config_path))
        session = IntegrationalServiceSession(cfg)
        sid = session.sessionId
        try:
            session.CloseSession(sid)
        except Exception:
            pass
        return True, f"ОК. SessionID={sid}"
    except Exception as e:
        return False, str(e)


def load_access_groups(config_path: Path) -> list[dict]:
    """
    Возвращает: [{"ID": "...", "NAME": "..."}]
    """
    cfg = ConnectionConfig(str(config_path))
    session = IntegrationalServiceSession(cfg)
    groups = get_access_groups(session)

    result = []
    for g in groups:
        gid = g.get("ID")
        name = (g.get("NAME") or "").strip()
        if gid and name:
            result.append({"ID": gid, "NAME": name})
    return result


def run_import(
    base_root: Path,
    config_path: Path,
    access_group_id: str | None,
    access_group_name: str | None,
    valid_from: Optional[datetime],
    valid_to: Optional[datetime],
    tasks: Optional[list[PhotoTask]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
):
    def log(msg: str):
        if on_log:
            on_log(msg)

    def progress(cur: int, total: int, cur_file: str = "", cur_fio: str = ""):
        if on_progress:
            on_progress(cur, total, cur_file, cur_fio)

    if tasks is None:
        tasks = scan_photo_files(base_root)

    total = len(tasks)
    progress(0, total, "", "")

    cfg = ConnectionConfig(str(config_path))
    session = IntegrationalServiceSession(cfg)

    PersonType = session.type("Person")
    org_unit_id = get_temp_orgunit_id(session)
    email_template_id = get_email_template_id(session)

    stats = {
        "total_files": total,
        "created_new": 0,
        "duplicates": 0,
        "skipped": 0,
        "errors": 0,
    }
    duplicates: list[dict] = []
    errors: list[str] = []

    if total == 0:
        log("Не найдено фото для импорта (проверьте папки и расширения).")

    for i, t in enumerate(tasks, start=1):
        fio_str = ""
        try:
            ln, fn, mn = parse_fio_from_filename(t.path.name)
            fio_str = f"{ln} {fn} {mn}".strip()
        except Exception:
            fio_str = ""

        progress(i - 1, total, str(t.path), fio_str)

        process_student_file(
            session=session,
            PersonType=PersonType,
            org_unit_id=org_unit_id,
            email_template_id=email_template_id,
            access_group_id=access_group_id,
            valid_from=valid_from,
            valid_to=valid_to,
            group_number=t.group_number,
            path=t.path,
            stats=stats,
            duplicates=duplicates,
            errors=errors,
        )

        progress(i, total, str(t.path), fio_str)

    script_dir = Path(__file__).parent
    log_path = write_log(
        script_dir=script_dir,
        stats=stats,
        duplicates=duplicates,
        errors=errors,
        valid_from=valid_from,
        valid_to=valid_to,
        access_group_id=access_group_id,
        access_group_name=access_group_name,
    )

    return {
        "stats": stats,
        "duplicates": duplicates,
        "errors": errors,
        "log_path": str(log_path),
        "access_group_id": access_group_id,
        "access_group_name": access_group_name,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }