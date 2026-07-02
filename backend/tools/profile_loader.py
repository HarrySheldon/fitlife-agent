from __future__ import annotations

import json
from pathlib import Path

from backend.schemas import UserProfile


def load_profile(path: str | Path) -> UserProfile:
    profile_path = Path(path)
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    return UserProfile.model_validate(data)


def save_profile(path: str | Path, profile: UserProfile) -> None:
    profile_path = Path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
