# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime

from zeep.helpers import serialize_object
from zeep import xsd

from main import IntegrationalServiceSession


PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png")
FAR_FUTURE = datetime(2099, 12, 31, 23, 59, 59)


def parse_fio_from_filename(filename: str):
    """Разбор ФИО из имени файла: 'Фамилия Имя Отчество.(jpg|png)', '_' -> пробелы."""
    stem = Path(filename).stem
    stem = stem.replace("_", " ")
    stem = stem.strip(" .-")
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        raise ValueError(f"Не удалось разобрать ФИО из имени файла: {filename}")

    parts = stem.split(" ")
    if len(parts) < 2:
        raise ValueError(f"Не удалось разобрать ФИО (мало частей) из имени файла: {filename}")

    norm_parts = [p[:1].upper() + p[1:].lower() for p in parts]
    last_name = norm_parts[0]
    first_name = norm_parts[1]
    middle_name = " ".join(norm_parts[2:]) if len(norm_parts) > 2 else ""
    return last_name, first_name, middle_name


def get_org_units(session: IntegrationalServiceSession):
    raw = session.GetOrgUnitsHierarhy(session.sessionId)
    data = serialize_object(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        orgs = data.get("OrgUnit") or []
        return orgs if isinstance(orgs, list) else [orgs]
    return []


def get_temp_orgunit_id(session: IntegrationalServiceSession) -> str:
    orgs = get_org_units(session)
    for ou in orgs:
        name = (ou.get("NAME") or "").strip()
        if name == "Временный":
            return ou["ID"]
    raise RuntimeError("Не найдено подразделение 'Временный'.")


def get_person_extra_field_templates(session: IntegrationalServiceSession):
    raw = session.GetPersonExtraFieldTemplates(session.sessionId)
    data = serialize_object(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        tpls = data.get("PersonExtraFieldTemplate") or []
        return tpls if isinstance(tpls, list) else [tpls]
    return []


def get_email_template_id(session: IntegrationalServiceSession):
    templates = get_person_extra_field_templates(session)
    for t in templates:
        name = (t.get("NAME") or "").strip().lower()
        if name == "email":
            return t["ID"]
    return None


def find_people_by_fio(session: IntegrationalServiceSession,
                       last_name: str, first_name: str, middle_name: str):
    res = session.FindPeople(session.sessionId, last_name, first_name, middle_name)
    if not res:
        return []
    data = serialize_object(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        persons = data.get("Person") or []
        return persons if isinstance(persons, list) else [persons]
    return []


def create_person(session: IntegrationalServiceSession,
                  person_type,
                  org_unit_id: str,
                  last_name: str, first_name: str, middle_name: str) -> str:
    person = person_type()
    person.ID = "00000000-0000-0000-0000-000000000000"
    person.FIRST_NAME = first_name
    person.LAST_NAME = last_name
    person.MIDDLE_NAME = middle_name
    person.TAB_NUM = ""
    person.ORG_ID = org_unit_id
    person.SUBJECT_TYPE = 0

    res = session.CreatePerson(session.sessionId, person)
    if res.Result != 0:
        raise RuntimeError(f"CreatePerson error: {res.ErrorMessage}")
    return str(res.Value)


# ---------- ГРУППЫ ДОСТУПА ----------

def get_access_groups(session: IntegrationalServiceSession):
    raw = session.GetAccessGroups(session.sessionId)
    data = serialize_object(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        groups = data.get("AccessGroup") or []
        return groups if isinstance(groups, list) else [groups]
    return []


# ---------- КАРТЫ / ИДЕНТИФИКАТОРЫ ----------

def add_card_identifier(session: IntegrationalServiceSession,
                        person_id: str,
                        access_group_id: str | None,
                        valid_from: datetime | None,
                        valid_to: datetime | None) -> str:
    """
    Если access_group_id задан — создаём StockIdentifier и назначаем группу доступа.
    В вашей системе VALID_FROM обязателен:
      - если valid_from None -> datetime.now()
      - если valid_to None -> 2099-12-31
    Если access_group_id не задан — BaseIdentifier (без группы).
    """
    code_res = session.GetUnique4bCardCode(session.sessionId)
    if code_res.Result != 0:
        raise RuntimeError(f"GetUnique4bCardCode error: {code_res.ErrorMessage}")
    card_code = code_res.Value

    if access_group_id:
        StockIdentifierType = session.type("StockIdentifier")
        if StockIdentifierType is None:
            raise RuntimeError("Не найден тип StockIdentifier в WSDL.")

        ident = StockIdentifierType()
        ident.CODE = card_code
        ident.PERSON_ID = person_id
        ident.IS_PRIMARY = True

        ident.ACCGROUP_ID = access_group_id
        ident.PRIVILEGE_MASK = 0
        ident.IDENTIFTYPE = 0
        ident.NAME = ""

        if valid_from is None:
            valid_from = datetime.now()
        ident.VALID_FROM = valid_from

        if valid_to is None:
            valid_to = FAR_FUTURE
        ident.VALID_TO = valid_to

    else:
        BaseIdentifierType = session.type("BaseIdentifier")
        if BaseIdentifierType is None:
            raise RuntimeError("Не найден тип BaseIdentifier в WSDL.")

        ident = BaseIdentifierType()
        ident.CODE = card_code
        ident.PERSON_ID = person_id
        ident.IS_PRIMARY = True

    edit_res = session.OpenPersonEditingSession(session.sessionId, person_id)
    if edit_res.Result != 0:
        raise RuntimeError(f"OpenPersonEditingSession (identifier) error: {edit_res.ErrorMessage}")
    edit_session_id = edit_res.Value

    try:
        add_res = session.AddPersonIdentifier(edit_session_id, ident)
        if add_res.Result != 0:
            raise RuntimeError(f"AddPersonIdentifier error: {add_res.ErrorMessage}")
    finally:
        session.ClosePersonEditingSession(edit_session_id)

    return card_code


# ---------- ФОТО + EMAIL ----------

def set_photo_and_email_for_person(session: IntegrationalServiceSession,
                                   person_id: str,
                                   email_template_id: str | None,
                                   email_value: str | None,
                                   photo_bytes: bytes):
    # Фото
    edit_res1 = session.OpenPersonEditingSession(session.sessionId, person_id)
    if edit_res1.Result != 0:
        raise RuntimeError(f"OpenPersonEditingSession (photo) error: {edit_res1.ErrorMessage}")
    edit_session_id1 = edit_res1.Value

    try:
        photo_res = session.SetPersonPhoto(edit_session_id1, photo_bytes)
        if photo_res.Result != 0:
            raise RuntimeError(f"SetPersonPhoto error: {photo_res.ErrorMessage}")
    finally:
        session.ClosePersonEditingSession(edit_session_id1)

    # Email
    if email_template_id and email_value:
        edit_res2 = session.OpenPersonEditingSession(session.sessionId, person_id)
        if edit_res2.Result != 0:
            raise RuntimeError(f"OpenPersonEditingSession (email) error: {edit_res2.ErrorMessage}")
        edit_session_id2 = edit_res2.Value

        try:
            email_any = xsd.AnyObject(xsd.String(), email_value)
            email_res = session.SetPersonExtraFieldValue(edit_session_id2, email_template_id, email_any)
            if email_res.Result != 0:
                raise RuntimeError(f"SetPersonExtraFieldValue error: {email_res.ErrorMessage}")
        finally:
            session.ClosePersonEditingSession(edit_session_id2)


# ---------- ОБРАБОТКА ФАЙЛА ----------

def process_student_file(session: IntegrationalServiceSession,
                         PersonType,
                         org_unit_id: str,
                         email_template_id: str | None,
                         access_group_id: str | None,
                         valid_from: datetime | None,
                         valid_to: datetime | None,
                         group_number: str,
                         path: Path,
                         stats: dict,
                         duplicates: list,
                         errors: list):
    if not path.is_file() or path.suffix.lower() not in PHOTO_EXTENSIONS:
        return

    try:
        last_name, first_name, middle_name = parse_fio_from_filename(path.name)
    except ValueError as e:
        stats["skipped"] += 1
        errors.append(f"[FIO_PARSE] {path} : {e}")
        return

    fio_str = f"{last_name} {first_name} {middle_name}".strip()
    email_value = f"Новгу / Политех / {group_number} / Студент"

    persons = find_people_by_fio(session, last_name, first_name, middle_name)
    persons_temp = [p for p in persons if p.get("ORG_ID") == org_unit_id]

    try:
        photo_bytes = path.read_bytes()
    except Exception as e:
        stats["errors"] += 1
        errors.append(f"[READ_PHOTO] {fio_str} ({path}) : {e}")
        return

    # Если уже есть в 'Временный' — дубликат
    if persons_temp:
        stats["duplicates"] += 1
        duplicates.append({
            "fio": fio_str,
            "group": group_number,
            "file": str(path),
            "count_in_temp": len(persons_temp),
            "ids": [p.get("ID") for p in persons_temp],
        })
        return

    # Создаём нового
    person_id = None
    try:
        person_id = create_person(
            session,
            PersonType,
            org_unit_id=org_unit_id,
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name,
        )
        add_card_identifier(session, person_id, access_group_id, valid_from, valid_to)
        set_photo_and_email_for_person(
            session,
            person_id=person_id,
            email_template_id=email_template_id,
            email_value=email_value if email_template_id else None,
            photo_bytes=photo_bytes,
        )
        stats["created_new"] += 1
    except Exception as e:
        stats["errors"] += 1
        errors.append(f"[PROCESS] {fio_str} ({path}) : {e}")

        # попытка отката (если метод есть)
        if person_id and hasattr(session, "DeletePerson"):
            try:
                session.DeletePerson(session.sessionId, person_id)
            except Exception:
                pass


# ---------- ЛОГИ ----------

def write_log(script_dir: Path,
              stats: dict,
              duplicates: list,
              errors: list,
              valid_from: datetime | None,
              valid_to: datetime | None,
              access_group_id: str | None,
              access_group_name: str | None):
    logs_dir = script_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"import_report_{ts}.txt"

    def fmt_dt(dt: datetime | None):
        return dt.strftime("%d.%m.%Y") if dt else "-"

    with log_path.open("w", encoding="utf-8") as f:
        f.write("=== Параметры запуска ===\n")
        f.write(f"Период действия карт: с {fmt_dt(valid_from)} по {fmt_dt(valid_to)}\n")
        f.write(f"Группа доступа: {access_group_name or '-'} [{access_group_id or '-'}]\n\n")

        f.write("=== Статистика ===\n")
        f.write(f"Всего файлов обработано: {stats['total_files']}\n")
        f.write(f"Новых пользователей создано: {stats['created_new']}\n")
        f.write(f"Дубликатов: {stats['duplicates']}\n")
        f.write(f"Пропущено: {stats['skipped']}\n")
        f.write(f"Ошибок: {stats['errors']}\n\n")

        f.write("=== Дубликаты ===\n")
        if not duplicates:
            f.write("Нет дубликатов.\n")
        else:
            for d in duplicates:
                f.write(
                    f"Группа: {d['group']}, ФИО: {d['fio']}, файл: {d['file']}, "
                    f"в 'Временный': {d['count_in_temp']}, IDs: {', '.join(str(i) for i in d['ids'])}\n"
                )

        f.write("\n=== Ошибки ===\n")
        if not errors:
            f.write("Нет ошибок.\n")
        else:
            for e in errors:
                f.write(e + "\n")

    return log_path