from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_ID_ATTEMPTS = 8

# What was exported, per argument file, in the library's .noesis/: a
# discussion in Roxana is public dialectic and belongs to no one, so it is
# never replaced; exporting the same argument again names the discussion it
# already has (rvanegas-site CLAUDE.md, *Public dialectic has no owner*).
EXPORTS = "exports.json"


def _primary(companion: Path) -> Path:
    return companion.with_suffix("").with_suffix(".md")


def _layout_entry(index: int, sentence_id: str, goal: list[str] | None = None) -> dict:
    return {
        "index": index,
        "id": sentence_id,
        "status": "committed",
        "accepted": [],
        "rejected": [],
        "cleared": [],
        "goal": goal or [],
        "hidden": False,
    }


def _sender() -> str | None:
    """Who sends the argument: the server names its run's caller; on the Mac, nobody."""
    return os.environ.get("NOESIS_CALLER") or None


def _goals_summary(conclusion: str, goal: list[str]) -> str:
    """Roxana's goalsSummary for one goal, as its getGoalsSummary (data.tsx) writes it."""
    content = re.match(r"^\s*(.*?)\.*\s*$", conclusion, re.DOTALL).group(1)
    return f"{content} ({', '.join(goal)})" if goal else ""


def _argument_contents(argument: list[dict]) -> list[str]:
    """Roxana argument sentences: space-joined indices, justifiers first, conclusion last."""
    justified = [s for s in argument if s.get("justifiers")]
    justified.sort(key=lambda s: int(s["symbol"]))
    return [" ".join([*s["justifiers"], s["symbol"]]) for s in justified]


def _analysis_results(companion: Path, argument: list[dict]) -> dict[int, dict]:
    """Parse the .analysis.md companion into Roxana's analysisResults shape.

    Roxana keys analysisResults by 1-based argument position; noesis keys analysis
    blocks by conclusion proposition number. Positions here MUST follow the same
    ordering as _argument_contents (ascending conclusion symbol), which is also
    the assign_argument_labels convention.
    """
    from noesis.analysis import parse_analysis_result
    from noesis.cmd_analyze import _parse_analysis_blocks

    analysis_path = companion.with_suffix("").with_suffix(".analysis.md")
    if not analysis_path.exists():
        return {}

    blocks = _parse_analysis_blocks(analysis_path.read_text(encoding="utf-8"))
    justified = sorted((s for s in argument if s.get("justifiers")),
                       key=lambda s: int(s["symbol"]))
    position_by_prop = {int(s["symbol"]): pos for pos, s in enumerate(justified, start=1)}

    return {position_by_prop[prop_num]: parse_analysis_result(body)
            for prop_num, body in blocks.items()
            if prop_num in position_by_prop}


def _digest(propositions: list[str], arguments: list[str], analyses: dict) -> str:
    payload = json.dumps([propositions, arguments, analyses], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _exports_path(library: Path | None) -> Path | None:
    from noesis.config import library_state_dir
    return library_state_dir(library) / EXPORTS if library else None


def _export_key(companion: Path, library: Path | None) -> str:
    try:
        return companion.resolve().relative_to(library.resolve()).as_posix() if library else companion.name
    except ValueError:
        return companion.resolve().as_posix()


def _load_exports(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _discussion_link(web_url: str | None, discussion_id: str) -> str:
    return f"{web_url.rstrip('/')}/discussions/{discussion_id}" if web_url else f"discussion {discussion_id}"


def run_export(path: Path, dry_run: bool = False, new: bool = False) -> int:
    from noesis.argue import markdown_to_argument
    from noesis.config import load_config
    from noesis import roxana_client

    if path.name.endswith(".argument.md"):
        companion = path
    elif path.name.endswith(".document.md") or path.suffix.lower() == ".md":
        companion = path.with_suffix("").with_suffix(".argument.md")
    else:
        print(f"Error: '{path}' does not have a .md extension.")
        return 1

    if not companion.exists():
        print(f"Error: '{companion.name}' does not exist. Run 'noesis argue {_primary(companion).name}' first.")
        return 1

    try:
        args_dict = markdown_to_argument(companion.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    argument = args_dict["argument"]
    proposition_contents = [s["proposition"] for s in sorted(argument, key=lambda s: int(s["symbol"]))]
    argument_contents = _argument_contents(argument)
    analysis_results = _analysis_results(companion, argument)
    # The whole argument's conclusion is its last proposition (dianoia's
    # extraction puts it there), set as the sender's goal in Roxana.
    conclusion = len(proposition_contents)

    if dry_run:
        print("Propositions:")
        for i, content in enumerate(proposition_contents, start=1):
            print(f"  {i}: {content}")
        print("Arguments:")
        for i, content in enumerate(argument_contents, start=1):
            print(f"  {i}: {content}")
        if analysis_results:
            print(f"Analyses: positions {', '.join(str(p) for p in sorted(analysis_results))}")
        print(f"Goal: proposition {conclusion}")
        print("Dry run — nothing sent to Roxana.")
        return 0

    config = load_config()
    if not config.roxana_api_url or not config.roxana_api_key:
        print("Error: set roxana_api_url and roxana_api_key in ~/.config/noesis/config.toml.")
        return 1
    url, api_key = config.roxana_api_url, config.roxana_api_key
    goal = [sender] if (sender := _sender()) else []

    exports_path = _exports_path(config.library_path)
    exports = _load_exports(exports_path)
    key = _export_key(companion, config.library_path)
    digest = _digest(proposition_contents, argument_contents, analysis_results)
    previous = exports.get(key)
    if previous and not new:
        link = _discussion_link(config.roxana_web_url, previous["discussion_id"])
        if previous["digest"] == digest:
            print(f"Already in Roxana as discussion {previous['discussion_id']}, sent {previous['exported_at']};"
                  " unchanged since.")
            print(link)
            return 0
        print(f"Sent to Roxana before, as discussion {previous['discussion_id']} ({previous['exported_at']}),"
              f" and {companion.name} has changed since. A discussion is not replaced: what people"
              " have accepted or rejected there stands. Send it again with --new to start another"
              " discussion.")
        print(link)
        return 1

    try:
        for _ in range(_ID_ATTEMPTS):
            discussion_id = roxana_client.generate_discussion_id()
            if not roxana_client.discussion_exists(url, api_key, discussion_id):
                break
        else:
            print("Error: could not find an available discussion id.", file=sys.stderr)
            return 1

        created_ids: list[str] = []
        try:
            proposition_entries = []
            for index, content in enumerate(proposition_contents, start=1):
                sentence_id = roxana_client.create_sentence(url, api_key, content, discussion_id)
                created_ids.append(sentence_id)
                proposition_entries.append(
                    _layout_entry(index, sentence_id, goal if index == conclusion else None))
            argument_entries = []
            for index, content in enumerate(argument_contents, start=1):
                sentence_id = roxana_client.create_sentence(url, api_key, content, discussion_id)
                created_ids.append(sentence_id)
                argument_entries.append(_layout_entry(index, sentence_id))
            layout = json.dumps({"propositions": proposition_entries, "arguments": argument_entries})
            roxana_client.create_discussion(
                url, api_key, discussion_id, layout,
                analysis_results=json.dumps(analysis_results) if analysis_results else None,
                goals_summary=_goals_summary(proposition_contents[-1], goal),
            )
        except RuntimeError:
            for sentence_id in created_ids:
                try:
                    roxana_client.delete_sentence(url, api_key, sentence_id)
                except RuntimeError:
                    pass
            raise
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    exported_analyses = f", {len(analysis_results)} analyses" if analysis_results else ""
    print(f"Exported {len(proposition_entries)} propositions, {len(argument_entries)} arguments"
          f"{exported_analyses} to discussion {discussion_id}.")
    if goal:
        print(f"Proposition {conclusion}, the conclusion, is {goal[0]}'s goal.")
    else:
        print(f"Proposition {conclusion}, the conclusion, is nobody's goal: only a run on the server knows who sent it.")
    if exports_path is not None:
        earlier = [*previous.get("earlier", []), previous["discussion_id"]] if previous else []
        exports[key] = {
            "discussion_id": discussion_id,
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "digest": digest,
            **({"earlier": earlier} if earlier else {}),
        }
        exports_path.parent.mkdir(parents=True, exist_ok=True)
        exports_path.write_text(json.dumps(exports, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(_discussion_link(config.roxana_web_url, discussion_id))
    return 0
