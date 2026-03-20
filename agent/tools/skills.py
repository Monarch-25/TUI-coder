from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    root: Path
    references: list[str]
    scripts: list[str]


class SkillLibrary:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or SKILLS_DIR

    def list(self) -> list[SkillSpec]:
        skills: list[SkillSpec] = []
        if not self.root.exists():
            return skills
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            skill = self.get(child.name)
            if skill is not None:
                skills.append(skill)
        return skills

    def get(self, skill_name: str) -> SkillSpec | None:
        skill_root = self.root / skill_name
        skill_file = skill_root / "SKILL.md"
        if not skill_file.exists():
            return None
        text = skill_file.read_text(encoding="utf-8")
        metadata = self._parse_frontmatter(text)
        references = [
            path.relative_to(skill_root).as_posix()
            for path in sorted(skill_root.glob("*.md"))
            if path.name != "SKILL.md"
        ]
        scripts = [
            path.relative_to(skill_root).as_posix()
            for path in sorted(skill_root.glob("scripts/**/*.py"))
        ]
        return SkillSpec(
            name=metadata.get("name", skill_name),
            description=metadata.get("description", "No description provided."),
            root=skill_root,
            references=references[:8],
            scripts=scripts[:12],
        )

    def available_names(self) -> list[str]:
        return [skill.name for skill in self.list()]

    def summarize(self, skill_name: str, goal: str | None = None) -> str:
        skill = self.get(skill_name)
        if skill is None:
            names = ", ".join(self.available_names()) or "none"
            return f"Skill not found: {skill_name}\nAvailable skills: {names}"
        lines = [
            f"Skill: {skill.name}",
            f"Description: {skill.description}",
        ]
        if goal:
            lines.append(f"Requested goal: {goal}")
        if skill.references:
            lines.append("Reference docs:")
            lines.extend(f"- {ref}" for ref in skill.references)
        if skill.scripts:
            lines.append("Scripts:")
            lines.extend(f"- {script}" for script in skill.scripts[:8])
        return "\n".join(lines)

    def match_for_query(self, query: str) -> SkillSpec | None:
        lowered = query.lower()
        triggers = {
            "pdf": (".pdf", " pdf ", "ocr", "fillable form", "merge pdf", "split pdf"),
            "docx": (".docx", "word doc", "word document", "tracked changes", "report", "memo", "letterhead"),
            "xlsx": (".xlsx", ".xlsm", ".csv", ".tsv", "spreadsheet", "excel", "workbook"),
        }
        padded = f" {lowered} "
        for name, hints in triggers.items():
            if any(hint in padded or hint in lowered for hint in hints):
                return self.get(name)
        for candidate in re.findall(r"\b[a-z0-9_-]+\b", lowered):
            skill = self.get(candidate)
            if skill is not None:
                return skill
        return None

    def _parse_frontmatter(self, text: str) -> dict[str, str]:
        if not text.startswith("---\n"):
            return {}
        _, _, remainder = text.partition("---\n")
        block, _, _ = remainder.partition("\n---")
        metadata: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"').strip("'")
        return metadata
