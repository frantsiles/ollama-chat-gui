"""Skills manager — carga y gestiona agent skills desde .agents/skills/"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


_FRONT_MATTER_RE = re.compile(r"\A\s*---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    content: str
    path: Path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }


class SkillsManager:
    SKILLS_DIR = ".agents/skills"

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.skills_dir = self.workspace_root / self.SKILLS_DIR

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_skills(self) -> List[Skill]:
        if not self.skills_dir.exists():
            return []
        skills = []
        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill = self._parse_skill(entry / "SKILL.md")
            if skill:
                skills.append(skill)
        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._parse_skill(self.skills_dir / name / "SKILL.md")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_skill(self, name: str, description: str, content: str) -> Skill:
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        full = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}"
        skill_file.write_text(full, encoding="utf-8")
        return Skill(name=name, description=description, content=full, path=skill_file)

    def update_skill(self, name: str, description: str, content: str) -> Optional[Skill]:
        skill_file = self.skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return None
        full = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}"
        skill_file.write_text(full, encoding="utf-8")
        return Skill(name=name, description=description, content=full, path=skill_file)

    def delete_skill(self, name: str) -> bool:
        skill_dir = self.skills_dir / name
        if not skill_dir.exists():
            return False
        shutil.rmtree(skill_dir)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_skill_prompt(self, name: str) -> Optional[str]:
        """Retorna el contenido del skill para inyectar en el system prompt."""
        skill = self.get_skill(name)
        return skill.content if skill else None

    def _parse_skill(self, path: Path) -> Optional[Skill]:
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        name = path.parent.name
        description = ""

        m = _FRONT_MATTER_RE.match(content)
        if m:
            for line in m.group(1).splitlines():
                if line.startswith("name:"):
                    name = line[5:].strip()
                elif line.startswith("description:"):
                    description = line[12:].strip()

        return Skill(name=name, description=description, content=content, path=path)
