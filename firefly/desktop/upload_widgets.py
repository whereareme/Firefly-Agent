"""Upload preview widgets for the Firefly chat composer."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


def upload_preview_widget(
    parent: QWidget,
    path: Path,
    image_extensions: set[str],
    revoke_upload: Callable[[Path], None],
) -> QWidget:
    card = QFrame(parent)
    card.setObjectName("uploadPreviewCard")
    card.setToolTip(str(path))
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(4, 4, 4, 4)
    card_layout.setSpacing(2)
    close = QPushButton("x", card)
    close.setObjectName("uploadPreviewClose")
    close.clicked.connect(lambda _checked=False, value=path: revoke_upload(value))
    card_layout.addWidget(close, 0, Qt.AlignRight)
    body = QLabel(card)
    body.setAlignment(Qt.AlignCenter)
    body.setFixedSize(76, 50)
    if path.suffix.lower() in image_extensions:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            body.setPixmap(pixmap.scaled(76, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            body.setText(path.name[:12])
    else:
        body.setText(path.name[:18])
        body.setWordWrap(True)
    card_layout.addWidget(body)
    return card
