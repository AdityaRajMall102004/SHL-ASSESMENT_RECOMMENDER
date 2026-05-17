"""
Convert markdown trace files (C1.md–C10.md) to JSON format
that evaluate_traces.py can consume.

USAGE:
  python tests/convert_traces.py
"""

import re
import json
from pathlib import Path

TRACES_DIR = Path(__file__).parent / "traces"


def parse_md_trace(md_text: str) -> dict:
    """
    Parse a markdown conversation trace into JSON structure:
    {
      "conversation": [{"role": "user"/"assistant", "content": "..."}],
      "expected_shortlist": ["Assessment Name 1", ...],
      "facts": {}
    }
    """
    conversation = []
    all_recommended_names = []

    # Split into turns
    turns = re.split(r"###\s+Turn\s+\d+", md_text)

    for turn_block in turns[1:]:  # skip header before Turn 1
        # Extract user message (lines starting with >)
        user_match = re.search(
            r"\*\*User\*\*\s*\n((?:\s*>\s*.+\n?)+)", turn_block
        )
        if user_match:
            raw_user = user_match.group(1)
            # Remove > prefix and join lines
            user_lines = []
            for line in raw_user.strip().split("\n"):
                cleaned = re.sub(r"^\s*>\s?", "", line).strip()
                if cleaned:
                    user_lines.append(cleaned)
            user_content = "\n".join(user_lines)
            conversation.append({"role": "user", "content": user_content})

        # Extract agent message (text after **Agent** until table or end)
        agent_match = re.search(
            r"\*\*Agent\*\*\s*\n(.*?)(?=_(?:No recommendations|`end_of_conversation`)|\Z)",
            turn_block,
            re.DOTALL,
        )
        if agent_match:
            agent_text = agent_match.group(1).strip()
            # Clean up the agent text — remove table formatting
            # but keep the gist
            clean_lines = []
            for line in agent_text.split("\n"):
                line = line.strip()
                if line.startswith("|") and ("---" in line or line == "|"):
                    continue
                if line.startswith("|"):
                    # Table row — skip for conversation but extract names
                    continue
                if line:
                    clean_lines.append(line)

            agent_content = "\n".join(clean_lines).strip()
            if agent_content:
                conversation.append(
                    {"role": "assistant", "content": agent_content}
                )

        # Extract assessment names from tables in this turn
        table_rows = re.findall(
            r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|", turn_block
        )
        for name in table_rows:
            name = name.strip()
            if name and name not in all_recommended_names:
                all_recommended_names.append(name)

    # The expected shortlist = names from the LAST table in the conversation
    # Find last turn with a table
    last_turn_names = []
    for turn_block in reversed(turns[1:]):
        names = re.findall(r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|", turn_block)
        names = [n.strip() for n in names if n.strip()]
        if names:
            last_turn_names = names
            break

    # Build facts from the conversation context
    facts = build_facts_from_conversation(conversation)

    return {
        "conversation": conversation,
        "expected_shortlist": last_turn_names if last_turn_names else all_recommended_names,
        "facts": facts,
    }


def build_facts_from_conversation(conversation: list) -> dict:
    """Extract contextual facts from user messages for the simulated user."""
    facts = {}
    all_user_text = " ".join(
        m["content"] for m in conversation if m["role"] == "user"
    ).lower()

    # Try to extract role
    role_patterns = [
        r"hiring\s+(?:a\s+)?(.+?)(?:\.|,|\s+for|\s+with|\s+—|\s+-|\s+who)",
        r"need\s+(?:a\s+)?(.+?)(?:\.|,|\s+for|\s+with)",
        r"(?:senior|mid|junior|entry)\s+(.+?)(?:\.|,|\s+for|\s+with)",
    ]
    for pattern in role_patterns:
        match = re.search(pattern, all_user_text)
        if match:
            facts["role"] = match.group(1).strip()
            break

    # Seniority
    if "senior" in all_user_text or "cxo" in all_user_text or "director" in all_user_text:
        facts["seniority"] = "senior"
    elif "entry" in all_user_text or "graduate" in all_user_text:
        facts["seniority"] = "entry-level"
    elif "mid" in all_user_text:
        facts["seniority"] = "mid-level"

    # Skills
    skills = []
    skill_words = [
        "java", "python", "sql", "angular", "spring", "aws", "docker",
        "excel", "word", "rust", "networking", "hipaa", "financial",
    ]
    for s in skill_words:
        if s in all_user_text:
            skills.append(s)
    if skills:
        facts["skills"] = ", ".join(skills)

    return facts


def main():
    md_files = sorted(TRACES_DIR.glob("*.md"))
    if not md_files:
        print("No .md files found in", TRACES_DIR)
        return

    print(f"Converting {len(md_files)} markdown traces to JSON...\n")

    for md_file in md_files:
        md_text = md_file.read_text(encoding="utf-8")
        trace = parse_md_trace(md_text)

        json_file = md_file.with_suffix(".json")
        json_file.write_text(
            json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        print(f"  {md_file.name} → {json_file.name}")
        print(f"    Turns: {len(trace['conversation'])}")
        print(f"    Expected: {trace['expected_shortlist']}")
        print()

    print("Done! JSON traces ready for evaluate_traces.py")


if __name__ == "__main__":
    main()
