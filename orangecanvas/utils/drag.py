"""
Non-blocking drag-and-drop via synthetic events.

Replaces ``QDrag.exec()`` (which enters a nested event loop) with mouse
tracking through an application-level event filter.  On mouse release the
session dispatches synthetic ``QDragEnterEvent`` / ``QDropEvent`` to the
widget under the cursor.

This works on all platforms — desktop and WASM alike.
"""
from typing import Optional, Callable

from AnyQt.QtWidgets import QApplication, QWidget, QLabel, QAbstractScrollArea
from AnyQt.QtGui import (
    QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent, QPixmap,
)
from AnyQt.QtCore import (
    Qt, QObject, QEvent, QMimeData, QPoint, QPointF, QCoreApplication,
)

__all__ = ["start_drag", "drag_source"]

# Property key that carries the source widget reference on the QMimeData.
# QDropEvent.source() only works with a real QDrag; our synthetic events
# use this property instead.
_SOURCE_PROPERTY = "_drag_source"


def start_drag(
    source: QWidget,
    mime_data: QMimeData,
    supported_actions: Qt.DropAction = Qt.DropAction.CopyAction,
    default_action: Qt.DropAction = Qt.DropAction.IgnoreAction,
    pixmap=None,
    hot_spot: Optional[QPoint] = None,
    on_completed: Optional[Callable] = None,
) -> None:
    """Start a drag-and-drop operation.

    The function returns immediately.  When the user releases the mouse
    (or presses Escape), *on_completed* is called with the resulting
    ``Qt.DropAction``.

    Parameters
    ----------
    source : QWidget
        The widget initiating the drag.
    mime_data : QMimeData
        The payload.
    supported_actions : Qt.DropAction
        Allowed drop actions.
    default_action : Qt.DropAction
        The preferred action.
    pixmap : QPixmap, optional
        Shown next to the cursor during the drag.
    hot_spot : QPoint, optional
        Offset from the cursor to the pixmap's top-left corner.
    on_completed : callable(Qt.DropAction), optional
        Called when the drag finishes.
    """
    mime_data.setProperty(_SOURCE_PROPERTY, source)
    _DragSession(
        source, mime_data, supported_actions, default_action,
        pixmap, hot_spot, on_completed,
    )


def drag_source(event) -> Optional[QWidget]:
    """Retrieve the drag source widget from a drop event.

    ``QDropEvent.source()`` only works with a real ``QDrag``.  Since
    ``start_drag`` uses synthetic events, use this helper instead::

        source = event.source() or drag_source(event)
    """
    prop = event.mimeData().property(_SOURCE_PROPERTY)
    if isinstance(prop, QWidget):
        return prop
    return None


class _DragSession(QObject):
    """Mouse-tracking drag session."""

    _active: Optional["_DragSession"] = None

    def __init__(self, source, mime_data, supported_actions, default_action,
                 pixmap, hot_spot, on_completed):
        super().__init__()
        if _DragSession._active is not None:
            _DragSession._active._cancel()

        self._source = source
        self._mime_data = mime_data
        self._supported_actions = supported_actions
        self._default_action = default_action
        self._on_completed = on_completed
        self._current_target: Optional[QWidget] = None
        self._feedback: Optional[QLabel] = None

        # Visual feedback: floating pixmap that follows the cursor
        if pixmap is not None and not pixmap.isNull():
            label = QLabel(
                None,
                Qt.WindowType.ToolTip
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint,
            )
            label.setPixmap(pixmap)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.resize(pixmap.size())
            self._feedback = label
            self._hot_spot = hot_spot or QPoint(0, 0)
            # Position will be set on first MouseMove

        _DragSession._active = self
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------
    # Event filter
    # ------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()

        if etype == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()

            if self._feedback is not None:
                self._feedback.move(global_pos - self._hot_spot)
                if not self._feedback.isVisible():
                    self._feedback.show()

            target = self._drop_target_at(global_pos)

            if target is not self._current_target:
                if self._current_target is not None:
                    self._send_leave(self._current_target)
                if target is not None:
                    local = target.mapFromGlobal(global_pos)
                    self._send_enter(target, local)
                self._current_target = target
            elif target is not None:
                local = target.mapFromGlobal(global_pos)
                self._send_move(target, local)

            return True

        if etype == QEvent.Type.MouseButtonRelease:
            global_pos = event.globalPosition().toPoint()
            target = self._drop_target_at(global_pos)
            if target is not None:
                local = target.mapFromGlobal(global_pos)
                if target is not self._current_target:
                    self._send_enter(target, local)
                result = self._send_drop(target, local)
            else:
                result = Qt.DropAction.IgnoreAction
            self._finish(result)
            return True

        if etype == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._finish(Qt.DropAction.IgnoreAction)
            return True

        return False

    # ------------------------------------------------------------------
    # Synthetic event helpers
    # ------------------------------------------------------------------

    def _send_enter(self, target: QWidget, pos: QPoint) -> bool:
        ev = QDragEnterEvent(
            pos, self._supported_actions, self._mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        ev.setAccepted(False)
        QCoreApplication.sendEvent(target, ev)
        return ev.isAccepted()

    def _send_move(self, target: QWidget, pos: QPoint) -> None:
        ev = QDragMoveEvent(
            pos, self._supported_actions, self._mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(target, ev)

    def _send_leave(self, target: QWidget) -> None:
        QCoreApplication.sendEvent(target, QDragLeaveEvent())

    def _send_drop(self, target: QWidget, pos: QPoint) -> Qt.DropAction:
        ev = QDropEvent(
            QPointF(pos), self._supported_actions, self._mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        ev.setAccepted(False)
        QCoreApplication.sendEvent(target, ev)
        if ev.isAccepted():
            return ev.dropAction()
        return Qt.DropAction.IgnoreAction

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _drop_target_at(global_pos: QPoint) -> Optional[QWidget]:
        widget = QApplication.widgetAt(global_pos)
        if widget is None:
            # QApplication.widgetAt() fails on WASM (Qt platform plugin
            # limitation).  Fall back to manual traversal: find the
            # top-level window containing the point, then walk down
            # via childAt().
            for w in QApplication.topLevelWidgets():
                if not w.isVisible():
                    continue
                if w.testAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                    continue
                local = w.mapFromGlobal(global_pos)
                if w.rect().contains(local):
                    child = w.childAt(local)
                    widget = child if child is not None else w
                    break
        if widget is None:
            return None
        while widget is not None:
            if widget.acceptDrops():
                return widget
            # QAbstractScrollArea viewports proxy events to the scroll area
            # via viewportEvent().  The viewport itself may not have
            # acceptDrops=True, but sending drag events to it still works
            # because the scroll area (e.g. QGraphicsView) handles them.
            parent = widget.parentWidget()
            if (isinstance(parent, QAbstractScrollArea)
                    and parent.viewport() is widget):
                return widget
            widget = parent
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _finish(self, result: Qt.DropAction) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._feedback is not None:
            self._feedback.close()
            self._feedback.deleteLater()
            self._feedback = None
        if self._current_target is not None:
            self._send_leave(self._current_target)
            self._current_target = None
        if self._on_completed is not None:
            self._on_completed(result)
        _DragSession._active = None
        self.deleteLater()

    def _cancel(self) -> None:
        self._finish(Qt.DropAction.IgnoreAction)
