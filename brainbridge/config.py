"""Settings, loaded from a JSON config file (see example/config.json).

Relative paths in the config are resolved against the config file's own folder, so the
example runs the same on any machine.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


def project_key(name: str) -> str:
    """Comparison key for project names: 'Project A', 'project-a' and 'project_a' match."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").casefold())


@dataclass
class Settings:
    vault: Path                      # the notes vault (one folder per project under projects/)
    sources: list                    # folders holding project repos
    transcripts: Path                # AI session transcripts: <folder>/<session-id>.jsonl
    state_dir: Path                  # index, logs, locks, staging (never published)
    digest_out: Path                 # where the audited digest is published
    digest_remote: str = ""          # optional: the ONE git remote the digest may push to
    aliases: dict = field(default_factory=dict)  # project_key(alias) -> canonical project name

    @property
    def db_path(self) -> Path:
        return self.state_dir / "index.db"

    @property
    def log_path(self) -> Path:
        return self.state_dir / "bridge.log"

    @property
    def staging_path(self) -> Path:
        return self.state_dir / "digest-staging"

    @property
    def projects_dir(self) -> Path:
        return self.vault / "projects"

    @property
    def current_md(self) -> Path:
        return self.vault / "CURRENT.md"

    @property
    def review_md(self) -> Path:
        return self.vault / "inbox" / "INBOX-REVIEW.md"

    def canonical(self, name: str) -> str:
        return self.aliases.get(project_key(name), name)

    def names_for(self, project: str) -> list:
        """The project's own name plus every alias that points at it."""
        key = project_key(project)
        names = {project}
        names.update(a for a, canon in self._alias_names.items() if project_key(canon) == key)
        return sorted(names, key=str.casefold)

    _alias_names: dict = field(default_factory=dict, repr=False)


def load(path) -> Settings:
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    base = path.parent

    def p(value) -> Path:
        q = Path(value)
        return q if q.is_absolute() else (base / q).resolve()

    s = Settings(
        vault=p(raw["vault"]),
        sources=[p(x) for x in raw.get("sources", [])],
        transcripts=p(raw["transcripts"]),
        state_dir=p(raw["state_dir"]),
        digest_out=p(raw["digest_out"]),
        digest_remote=raw.get("digest_remote", ""),
    )
    for alias, canonical in raw.get("aliases", {}).items():
        s.aliases[project_key(alias)] = canonical
        s._alias_names[alias] = canonical
    return s
