"""Skill manifest validation: frontmatter + path-mirrored names."""
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


def _skill_dirs():
    return [p.parent for p in SKILLS.rglob("SKILL.md")]


def test_expected_skill_contracts():
    assert set(_skill_dirs()) == {
        SKILLS / "geno-tt",
        SKILLS / "workspaces" / "check-retirement",
    }


def test_frontmatter_valid():
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text()
        assert text.startswith("---"), f"{d}: missing frontmatter"
        fm = yaml.safe_load(text[3:text.index("---", 3)])
        assert fm.get("name"), f"{d}: missing name"
        assert fm.get("description"), f"{d}: missing description"


def test_name_mirrors_path():
    # The single visible entry point is the required umbrella skill.
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text()
        name = yaml.safe_load(text[3:text.index("---", 3)])["name"]
        if d == SKILLS / "geno-tt":
            assert name == "geno-tt"
            continue
        assert name.startswith("geno-tt-"), f"{d}: name {name!r} not geno-tt-*"
        assert name.endswith(f"-{d.name}"), f"{d}: name {name!r} should end -{d.name}"


def test_root_skill_links_to_umbrella():
    root_skill = REPO / "SKILL.md"
    umbrella = SKILLS / "geno-tt" / "SKILL.md"
    assert root_skill.is_symlink()
    assert root_skill.resolve() == umbrella.resolve()
