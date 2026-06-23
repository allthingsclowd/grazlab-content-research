"""OKF v0.1 core — pure, stdlib-only (no PyYAML).

Open Knowledge Format (Google, knowledge-catalog/okf, v0.1 draft) is markdown +
YAML frontmatter, one concept file per finding, in a directory bundle. The only
hard rule: a non-empty ``type:`` in every non-reserved ``.md``; ``index.md`` is a
reserved directory listing. The frontmatter we emit is simple scalars plus a
string list, so a PyYAML dependency is unwarranted.

This is the **generic core** lifted verbatim from thegeekwiththepeak.com
(``content_pipeline/okf/builder.py``) — :class:`Concept`, :class:`Bundle`,
:func:`render_concept`, :func:`bundle_files`, :func:`flatten_for_judge`,
:func:`validate`, :func:`bundle_to_json`/:func:`bundle_from_json`. The site-
specific mappers (geek's CTEM vulnerability/advisory concepts, etc.) stay in each
repo; the library's per-run mapper lives in :mod:`okf_store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OKF_VERSION = "0.1"


@dataclass
class Concept:
    """One unit of knowledge = one markdown file. ``concept_id`` is the file path
    within the bundle, minus ``.md`` (e.g. ``candidates/01-foo``)."""

    concept_id: str
    type: str
    title: str = ""
    description: str = ""
    resource: str = ""
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""
    body: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    concepts: list[Concept]
    version: str = OKF_VERSION
    name: str = ""
    description: str = ""


def _scalar(value: str) -> str:
    """Emit a YAML plain scalar, single-quoting only when YAML would mis-parse it.
    URLs (``https://x``) stay plain — the colon is not followed by a space."""
    s = str(value)
    if s == "":
        return "''"
    risky = (
        s != s.strip()
        or ": " in s
        or s.endswith(":")
        or " #" in s
        or "\n" in s
        or s[0] in "#&*!|>%@`\"'[]{},?:-"
    )
    return "'" + s.replace("'", "''") + "'" if risky else s


def render_concept(c: Concept) -> str:
    """Render one concept to an OKF markdown document (frontmatter + body +
    Citations). Raises if ``type`` is empty — the single OKF hard requirement."""
    if not c.type.strip():
        raise ValueError(f"OKF concept {c.concept_id!r} has an empty 'type'")
    lines = ["---", f"type: {_scalar(c.type)}"]
    if c.title:
        lines.append(f"title: {_scalar(c.title)}")
    if c.description:
        lines.append(f"description: {_scalar(c.description)}")
    if c.resource:
        lines.append(f"resource: {_scalar(c.resource)}")
    if c.tags:
        lines.append("tags:")
        lines.extend(f"- {_scalar(t)}" for t in c.tags)
    if c.timestamp:
        lines.append(f"timestamp: '{c.timestamp}'")
    lines.append("---")
    fm = "\n".join(lines)
    body = (c.body or "").strip("\n")
    doc = f"{fm}\n\n{body}\n" if body else f"{fm}\n"
    if c.citations:
        cites = "\n".join(f"- {u}" for u in c.citations)
        doc += f"\n# Citations\n{cites}\n"
    return doc


def _index_md(
    title: str,
    entries: list[tuple[str, str, str]],
    *,
    root: bool = False,
    version: str = OKF_VERSION,
) -> str:
    """A reserved ``index.md`` directory listing. The bundle root MAY carry
    ``okf_version`` in frontmatter; sub-directory indexes carry none."""
    lines: list[str] = []
    if root:
        lines += ["---", f'okf_version: "{version}"', "---", ""]
    lines += [f"# {title}", ""]
    for rel, label, desc in entries:
        lines.append(f"* [{label}]({rel})" + (f" - {desc}" if desc else ""))
    return "\n".join(lines) + "\n"


def bundle_files(b: Bundle) -> dict[str, str]:
    """Render the full bundle to a ``{path: content}`` tree, including a reserved
    ``index.md`` at the root and in every sub-directory (progressive disclosure)."""
    files: dict[str, str] = {}
    by_dir: dict[str, list[Concept]] = {}
    for c in b.concepts:
        files[f"{c.concept_id}.md"] = render_concept(c)
        d = c.concept_id.rsplit("/", 1)[0] if "/" in c.concept_id else ""
        by_dir.setdefault(d, []).append(c)

    for d, concepts in by_dir.items():
        if not d:
            continue
        entries = [
            (f"{c.concept_id.rsplit('/', 1)[-1]}.md", c.title or c.concept_id, c.description)
            for c in concepts
        ]
        files[f"{d}/index.md"] = _index_md(d, entries)

    root_entries = [(f"{d}/index.md", d, "") for d in sorted(by_dir) if d]
    files["index.md"] = _index_md(
        b.name or "Knowledge Bundle", root_entries, root=True, version=b.version
    )
    return files


def flatten_for_judge(b: Bundle, *, budget: int = 6000) -> str:
    """Concatenate the bundle's concepts into ONE budgeted block for a one-shot
    judge (which cannot navigate ``index.md`` progressive disclosure). Concepts
    keep rank order so the most important findings survive a tight budget."""
    blocks: list[str] = []
    for c in b.concepts:
        head = f"### {c.concept_id} ({c.type})"
        meta = []
        if c.title:
            meta.append(c.title)
        if c.resource:
            meta.append(f"source: {c.resource}")
        body = (c.body or "").strip()
        blocks.append("\n".join([head, *meta, body]).strip())
    out = "\n\n".join(blocks).strip()
    return out if len(out) <= budget else out[: budget - 1] + "…"


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return None
    fm: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i] != "---":
        line = lines[i]
        if ":" in line and not line.startswith("- "):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
        i += 1
    if i >= len(lines):  # never found the closing fence
        return None
    return fm


def validate(files: dict[str, str]) -> list[str]:
    """OKF v0.1 conformance: every non-reserved ``.md`` has parseable frontmatter
    with a non-empty ``type``. Returns a list of problems (empty == conformant)."""
    problems: list[str] = []
    for path, content in sorted(files.items()):
        if not path.endswith(".md"):
            continue
        base = path.rsplit("/", 1)[-1]
        if base in ("index.md", "log.md"):  # reserved files
            continue
        fm = _parse_frontmatter(content)
        if fm is None:
            problems.append(f"{path}: missing/unparseable frontmatter")
        elif not fm.get("type", "").strip():
            problems.append(f"{path}: missing non-empty 'type'")
    return problems


def bundle_to_json(b: Bundle) -> dict[str, Any]:
    """A JSON-serializable envelope for the S3 working key."""
    return {
        "okf_version": b.version,
        "name": b.name,
        "description": b.description,
        "concepts": [
            {
                "concept_id": c.concept_id,
                "type": c.type,
                "title": c.title,
                "description": c.description,
                "resource": c.resource,
                "tags": list(c.tags),
                "timestamp": c.timestamp,
                "body": c.body,
                "citations": list(c.citations),
            }
            for c in b.concepts
        ],
    }


def bundle_from_json(data: dict[str, Any]) -> Bundle:
    return Bundle(
        version=data.get("okf_version", OKF_VERSION),
        name=data.get("name", ""),
        description=data.get("description", ""),
        concepts=[
            Concept(
                concept_id=d["concept_id"],
                type=d["type"],
                title=d.get("title", ""),
                description=d.get("description", ""),
                resource=d.get("resource", ""),
                tags=list(d.get("tags", [])),
                timestamp=d.get("timestamp", ""),
                body=d.get("body", ""),
                citations=list(d.get("citations", [])),
            )
            for d in data.get("concepts", [])
        ],
    )
