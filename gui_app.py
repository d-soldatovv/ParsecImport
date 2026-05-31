from __future__ import annotations

import sys
import os
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot, QDate, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QFileDialog, QTextEdit, QLabel,
    QCheckBox, QDateEdit, QMessageBox, QProgressBar,
    QTabWidget, QTableWidget, QTableWidgetItem, QComboBox
)

from importer_core import run_import, scan_photo_files, check_connection, load_access_groups


class ImportWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int, str, str)   
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, base_root: Path, config_path: Path,
                 access_group_id: str | None, access_group_name: str | None,
                 use_period: bool, valid_from: datetime | None, valid_to: datetime | None):
        super().__init__()
        self.base_root = base_root
        self.config_path = config_path
        self.access_group_id = access_group_id
        self.access_group_name = access_group_name
        self.use_period = use_period
        self.valid_from = valid_from
        self.valid_to = valid_to
        self._prev_group_id = None

    @Slot()
    def run(self):
        try:
            tasks = scan_photo_files(self.base_root)
            self.progress.emit(0, len(tasks), "", "")

            vf = self.valid_from if self.use_period else None
            vt = self.valid_to if self.use_period else None

            result = run_import(
                base_root=self.base_root,
                config_path=self.config_path,
                access_group_id=self.access_group_id,
                access_group_name=self.access_group_name,
                valid_from=vf,
                valid_to=vt,
                tasks=tasks,
                on_log=lambda m: self.log.emit(m),
                on_progress=lambda c, t, f, fio: self.progress.emit(c, t, f, fio),
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class ConnWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = config_path

    @Slot()
    def run(self):
        ok, msg = check_connection(self.config_path)
        self.finished.emit(ok, msg)


class GroupsWorker(QObject):
    finished = Signal(list)  
    failed = Signal(str)

    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = config_path

    @Slot()
    def run(self):
        try:
            groups = load_access_groups(self.config_path)
            self.finished.emit(groups)
        except Exception as e:
            self.failed.emit(str(e))


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Parsec Import (Desktop)")

        self.last_log_path: Path | None = None

        self.config_edit = QLineEdit(str(Path.cwd() / "connection_config.json"))
        self.base_edit = QLineEdit(str(Path.cwd() / "Новгу" / "Политех"))

        self.btn_config = QPushButton("Файл config…")
        self.btn_base = QPushButton("Папка Политех…")
        self.btn_check = QPushButton("Проверить соединение")

        self.group_combo = QComboBox()
        self.group_combo.addItem("— не назначать группу —", None)
        self.btn_reload_groups = QPushButton("Загрузить группы")

        self.use_period = QCheckBox("Установить период действия (VALID_FROM/VALID_TO)")
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for d in (self.date_from, self.date_to):
            d.setCalendarPopup(True)
            d.setDate(QDate.currentDate())

        self.start_btn = QPushButton("Старт")

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setMaximum(1)
        self.progress_label = QLabel("0 / 0")

        self.btn_open_report = QPushButton("Открыть отчёт")
        self.btn_open_logs = QPushButton("Открыть папку logs")
        self.btn_open_report.setEnabled(False)
        self.btn_open_logs.setEnabled(False)

        self.current_file_lbl = QLabel("Файл: -")
        self.current_fio_lbl = QLabel("ФИО: -")
        for lbl in (self.current_file_lbl, self.current_fio_lbl):
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setWordWrap(True)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)

        self.tabs = QTabWidget()
        self.tbl_dups = QTableWidget(0, 5)
        self.tbl_dups.setHorizontalHeaderLabels(["Группа", "ФИО", "Файл", "Кол-во в 'Временный'", "IDs"])
        self.tbl_dups.setWordWrap(False)

        self.tbl_errs = QTableWidget(0, 1)
        self.tbl_errs.setHorizontalHeaderLabels(["Ошибка"])

        self.tabs.addTab(self.tbl_dups, "Дубликаты")
        self.tabs.addTab(self.tbl_errs, "Ошибки")
        self.tabs.addTab(self.log_view, "Лог")

        root = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("connection_config.json:"))
        row1.addWidget(self.config_edit, 1)
        row1.addWidget(self.btn_config)
        row1.addWidget(self.btn_check)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Папка с группами (…/Новгу/Политех):"))
        row2.addWidget(self.base_edit, 1)
        row2.addWidget(self.btn_base)
        root.addLayout(row2)

        rowg = QHBoxLayout()
        rowg.addWidget(QLabel("Группа доступа:"))
        rowg.addWidget(self.group_combo, 1)
        rowg.addWidget(self.btn_reload_groups)
        root.addLayout(rowg)

        row3 = QHBoxLayout()
        row3.addWidget(self.use_period)
        row3.addWidget(QLabel("c:"))
        row3.addWidget(self.date_from)
        row3.addWidget(QLabel("по:"))
        row3.addWidget(self.date_to)
        root.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(self.start_btn)
        row4.addWidget(self.progress, 1)
        row4.addWidget(self.progress_label)
        row4.addWidget(self.btn_open_report)
        row4.addWidget(self.btn_open_logs)
        root.addLayout(row4)

        root.addWidget(self.current_file_lbl)
        root.addWidget(self.current_fio_lbl)
        root.addWidget(self.tabs)

        self.btn_config.clicked.connect(self.pick_config)
        self.btn_base.clicked.connect(self.pick_base)
        self.btn_check.clicked.connect(self.check_conn_clicked)
        self.btn_reload_groups.clicked.connect(self.reload_groups)
        self.start_btn.clicked.connect(self.start_import)
        self.btn_open_report.clicked.connect(self.open_report)
        self.btn_open_logs.clicked.connect(self.open_logs)

        self.import_thread: QThread | None = None
        self.import_worker: ImportWorker | None = None

        self.conn_thread: QThread | None = None
        self.conn_worker: ConnWorker | None = None

        self.groups_thread: QThread | None = None
        self.groups_worker: GroupsWorker | None = None

    def append_log(self, text: str):
        self.log_view.append(text)

    def pick_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор connection_config.json", "", "JSON (*.json)")
        if path:
            self.config_edit.setText(path)

    def pick_base(self):
        path = QFileDialog.getExistingDirectory(self, "Выбор папки …/Новгу/Политех")
        if path:
            self.base_edit.setText(path)

    def _validate_paths(self) -> tuple[Path, Path] | None:
        base_root = Path(self.base_edit.text().strip())
        config_path = Path(self.config_edit.text().strip())
        if not base_root.is_dir():
            QMessageBox.critical(self, "Ошибка", f"Папка не найдена:\n{base_root}")
            return None
        if not config_path.is_file():
            QMessageBox.critical(self, "Ошибка", f"Файл config не найден:\n{config_path}")
            return None
        return base_root, config_path

    def set_busy(self, busy: bool):
        self.start_btn.setEnabled(not busy)
        self.btn_check.setEnabled(not busy)
        self.btn_reload_groups.setEnabled(not busy)
        self.btn_config.setEnabled(not busy)
        self.btn_base.setEnabled(not busy)
        self.group_combo.setEnabled(not busy)
        self.use_period.setEnabled(not busy)
        self.date_from.setEnabled(not busy)
        self.date_to.setEnabled(not busy)

    def check_conn_clicked(self):
        validated = self._validate_paths()
        if not validated:
            return
        _, config_path = validated

        self.btn_check.setEnabled(False)

        self.conn_thread = QThread()
        self.conn_worker = ConnWorker(config_path)
        self.conn_worker.moveToThread(self.conn_thread)

        self.conn_thread.started.connect(self.conn_worker.run)
        self.conn_worker.finished.connect(self.on_conn_finished)

        self.conn_worker.finished.connect(self.conn_thread.quit)
        self.conn_thread.finished.connect(self.conn_thread.deleteLater)

        self.conn_thread.start()

    @Slot(bool, str)
    def on_conn_finished(self, ok: bool, msg: str):
        self.btn_check.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Соединение", msg)
        else:
            QMessageBox.critical(self, "Соединение", msg)

    def reload_groups(self):
        validated = self._validate_paths()
        if not validated:
            return
        _, config_path = validated

        self.btn_reload_groups.setEnabled(False)
        self.group_combo.setEnabled(False)

        self._prev_group_id = self.group_combo.currentData()

        self.groups_thread = QThread()
        self.groups_worker = GroupsWorker(config_path)
        self.groups_worker.moveToThread(self.groups_thread)

        self.groups_thread.started.connect(self.groups_worker.run)

        self.groups_worker.finished.connect(self.on_groups_loaded, Qt.QueuedConnection)
        self.groups_worker.failed.connect(self.on_groups_failed, Qt.QueuedConnection)

        self.groups_worker.finished.connect(self.groups_thread.quit)
        self.groups_worker.failed.connect(self.groups_thread.quit)
        self.groups_thread.finished.connect(self.groups_thread.deleteLater)

        self.groups_thread.start()

    @Slot(list)
    def on_groups_loaded(self, groups: list):
        self.btn_reload_groups.setEnabled(True)
        self.group_combo.setEnabled(True)

        prev_id = self._prev_group_id

        self.group_combo.clear()
        self.group_combo.addItem("— не назначать группу —", None)

        for g in groups:
            self.group_combo.addItem(g["NAME"], g["ID"])

        if prev_id:
            for i in range(self.group_combo.count()):
                if self.group_combo.itemData(i) == prev_id:
                    self.group_combo.setCurrentIndex(i)
                    break

        QMessageBox.information(self, "Группы доступа", f"Загружено групп: {len(groups)}")

    @Slot(str)
    def on_groups_failed(self, err: str):
        self.btn_reload_groups.setEnabled(True)
        self.group_combo.setEnabled(True)
        QMessageBox.critical(self, "Группы доступа", err)

    def start_import(self):
        validated = self._validate_paths()
        if not validated:
            return
        base_root, config_path = validated

        access_group_id = self.group_combo.currentData()
        access_group_name = self.group_combo.currentText() if access_group_id else None

        use_period = self.use_period.isChecked()
        valid_from = valid_to = None
        if use_period:
            if not access_group_id:
                QMessageBox.critical(self, "Ошибка", "Для периода действия нужно выбрать группу доступа.")
                return
            valid_from = datetime.combine(self.date_from.date().toPython(), datetime.min.time())
            valid_to = datetime.combine(self.date_to.date().toPython(), datetime.min.time())

        self.set_busy(True)
        self.btn_open_report.setEnabled(False)
        self.btn_open_logs.setEnabled(False)
        self.last_log_path = None

        self.progress.setValue(0)
        self.progress.setMaximum(1)
        self.progress_label.setText("0 / 0")
        self.current_file_lbl.setText("Файл: -")
        self.current_fio_lbl.setText("ФИО: -")

        self.log_view.clear()
        self.tbl_dups.setRowCount(0)
        self.tbl_errs.setRowCount(0)
        self.tabs.setCurrentWidget(self.log_view)
        self.append_log("Запуск импорта...")

        self.import_thread = QThread()
        self.import_worker = ImportWorker(
            base_root=base_root,
            config_path=config_path,
            access_group_id=access_group_id,
            access_group_name=access_group_name,
            use_period=use_period,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        self.import_worker.moveToThread(self.import_thread)

        self.import_thread.started.connect(self.import_worker.run)
        self.import_worker.log.connect(self.append_log)
        self.import_worker.progress.connect(self.on_progress)
        self.import_worker.finished.connect(self.on_finished)
        self.import_worker.failed.connect(self.on_failed)

        self.import_worker.finished.connect(self.import_thread.quit)
        self.import_worker.failed.connect(self.import_thread.quit)
        self.import_thread.finished.connect(self.import_thread.deleteLater)

        self.import_thread.start()

    @Slot(int, int, str, str)
    def on_progress(self, current: int, total: int, cur_file: str, cur_fio: str):
        if total <= 0:
            self.progress.setMaximum(1)
            self.progress.setValue(0)
            self.progress_label.setText("0 / 0")
        else:
            self.progress.setMaximum(total)
            self.progress.setValue(current)
            self.progress_label.setText(f"{current} / {total}")

        if cur_file:
            self.current_file_lbl.setText(f"Файл: {cur_file}")
        if cur_fio:
            self.current_fio_lbl.setText(f"ФИО: {cur_fio}")

    def _fill_duplicates_table(self, duplicates: list[dict]):
        self.tbl_dups.setRowCount(len(duplicates))
        for r, d in enumerate(duplicates):
            self.tbl_dups.setItem(r, 0, QTableWidgetItem(str(d.get("group", ""))))
            self.tbl_dups.setItem(r, 1, QTableWidgetItem(str(d.get("fio", ""))))
            self.tbl_dups.setItem(r, 2, QTableWidgetItem(str(d.get("file", ""))))
            self.tbl_dups.setItem(r, 3, QTableWidgetItem(str(d.get("count_in_temp", ""))))
            ids = d.get("ids", [])
            self.tbl_dups.setItem(r, 4, QTableWidgetItem(", ".join(map(str, ids))))
        self.tbl_dups.resizeColumnsToContents()

    def _fill_errors_table(self, errors: list[str]):
        self.tbl_errs.setRowCount(len(errors))
        for r, e in enumerate(errors):
            self.tbl_errs.setItem(r, 0, QTableWidgetItem(str(e)))
        self.tbl_errs.resizeColumnsToContents()

    @Slot(dict)
    def on_finished(self, result: dict):
        self.set_busy(False)

        self.last_log_path = Path(result["log_path"])
        self.btn_open_report.setEnabled(True)
        self.btn_open_logs.setEnabled(True)

        stats = result["stats"]
        self.append_log("")
        self.append_log("Готово.")
        self.append_log(
            f"Файлов: {stats['total_files']}, создано: {stats['created_new']}, "
            f"дублей: {stats['duplicates']}, пропущено: {stats['skipped']}, ошибок: {stats['errors']}"
        )
        self.append_log(f"Отчёт: {result['log_path']}")

        self._fill_duplicates_table(result.get("duplicates") or [])
        self._fill_errors_table(result.get("errors") or [])

        if result.get("errors"):
            self.tabs.setCurrentWidget(self.tbl_errs)
        else:
            self.tabs.setCurrentWidget(self.tbl_dups)

        QMessageBox.information(self, "Импорт завершён", f"Отчёт:\n{result['log_path']}")

    @Slot(str)
    def on_failed(self, err: str):
        self.set_busy(False)
        QMessageBox.critical(self, "Ошибка", err)

    def open_report(self):
        if not self.last_log_path or not self.last_log_path.exists():
            QMessageBox.warning(self, "Отчёт", "Отчёт не найден.")
            return
        os.startfile(str(self.last_log_path))

    def open_logs(self):
        if self.last_log_path and self.last_log_path.exists():
            os.startfile(str(self.last_log_path.parent))
        else:
            os.startfile(str(Path.cwd() / "logs"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.resize(1150, 760)
    w.show()
    sys.exit(app.exec())
