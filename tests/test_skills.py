"""Skill manifest validation: frontmatter + path-mirrored names."""
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


def _skill_dirs():
    return [p.parent for p in SKILLS.rglob("SKILL.md")]


def test_at_least_one_skill():
    assert len(_skill_dirs()) >= 1


def test_frontmatter_valid():
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text()
        assert text.startswith("---"), f"{d}: missing frontmatter"
        fm = yaml.safe_load(text[3:text.index("---", 3)])
        assert fm.get("name"), f"{d}: missing name"
        assert fm.get("description"), f"{d}: missing description"


def test_name_mirrors_path():
    # leaf name ends with -<leaf-dir>; every skill is geno-tt-<category>-<name>
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text()
        name = yaml.safe_load(text[3:text.index("---", 3)])["name"]
        assert name.startswith("geno-tt-"), f"{d}: name {name!r} not geno-tt-*"
        assert name.endswith(f"-{d.name}"), f"{d}: name {name!r} should end -{d.name}"
