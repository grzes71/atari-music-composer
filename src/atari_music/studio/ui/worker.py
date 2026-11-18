"""Background QThreadPool workers for non-blocking WAV preview rendering and XEX export."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from atari_music.studio.exporter import ExportService, PreparedXexArrangement
from atari_music.studio.models import (
    CachedRenderEntry,
    LoadedCompositionState,
    StudioArrangementConfig,
    XexExportOptions,
    XexExportResult,
)
from atari_music.studio.renderer import RenderService


class RenderWorkerSignals(QObject):
    """Qt signals emitted by :class:`RenderWorker`."""

    finished = Signal(int, object)  # (request_id, CachedRenderEntry)
    failed = Signal(int, str)  # (request_id, error_message)


class RenderWorker(QRunnable):
    """Executes ``RenderService.render_preview`` off the GUI thread."""

    def __init__(
        self,
        request_id: int,
        render_service: RenderService,
        state: LoadedCompositionState,
        config: StudioArrangementConfig,
    ) -> None:
        super().__init__()
        self._request_id = int(request_id)
        self._render_service = render_service
        self._state = state
        self._config = config
        self.signals = RenderWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            entry: CachedRenderEntry = self._render_service.render_preview(
                self._state,
                self._config,
            )
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._request_id, str(exc))
            return
        self.signals.finished.emit(self._request_id, entry)


class ExportXexWorkerSignals(QObject):
    """Qt signals emitted by :class:`ExportXexWorker`."""

    finished = Signal(int, object)  # (request_id, XexExportResult)
    failed = Signal(int, str)  # (request_id, error_message)


class ExportXexWorker(QRunnable):
    """Executes ``ExportService.export_prepared_xex`` off the GUI thread."""

    def __init__(
        self,
        request_id: int,
        export_service: ExportService,
        prepared: PreparedXexArrangement,
        options: XexExportOptions,
    ) -> None:
        super().__init__()
        self._request_id = int(request_id)
        self._export_service = export_service
        self._prepared = prepared
        self._options = options
        self.signals = ExportXexWorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: XexExportResult = self._export_service.export_prepared_xex(
                self._prepared,
                self._options,
            )
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self._request_id, str(exc))
            return
        self.signals.finished.emit(self._request_id, result)
