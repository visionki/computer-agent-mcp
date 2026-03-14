from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path


@dataclass(slots=True)
class RunDebugRecorder:
    enabled: bool
    run_id: str
    run_dir: Path
    save_images: bool = True

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "images").mkdir(parents=True, exist_ok=True)

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    def record(self, event: str, payload: dict, image_bytes: bytes | None = None) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now(UTC)
        image_path = None
        if image_bytes is not None and self.save_images:
            image_name = f"{timestamp.strftime('%Y%m%d_%H%M%S_%f')}_{event.replace('.', '_')}.png"
            image_path = self.run_dir / "images" / image_name
            image_path.write_bytes(image_bytes)
        entry = {
            "timestamp": timestamp.isoformat(),
            "event": event,
            "payload": payload,
        }
        if image_path is not None:
            entry["image_path"] = str(image_path)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def write_text(self, name: str, content: str) -> None:
        if not self.enabled:
            return
        (self.run_dir / name).write_text(content, encoding="utf-8")

    def write_json(self, name: str, payload: object) -> None:
        if not self.enabled:
            return
        (self.run_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


@dataclass(slots=True)
class DebugRecorder:
    enabled: bool
    base_dir: Path
    save_images: bool = True

    def create_run(self, run_id: str) -> RunDebugRecorder:
        run_dir = self.base_dir / run_id
        return RunDebugRecorder(
            enabled=self.enabled,
            run_id=run_id,
            run_dir=run_dir,
            save_images=self.save_images,
        )

