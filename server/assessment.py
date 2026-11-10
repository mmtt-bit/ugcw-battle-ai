"""End-of-battle self assessment written by the LLM that commanded the army.

The model gets a compact digest of what happened (result, casualties, objective changes, how its
orders were used, what the server had to correct, a sample of its own reasoning) and the two
instruction files it was working with. It writes an after-action review and concrete suggestions.
The suggestions are only saved to a file: a human decides what to copy into strategy.md or
game_rules.md.
"""
import os
import time

ASSESSMENT_SYSTEM = """\\
You are the field commander of an army in Ultimate General: Civil War. The battle is over and
you now write your own after-action review for the human who built your command system.

Rules for the review:
- Be honest and critical. Base every statement on the numbers in the digest. Never claim a
  victory unless the digest says the AI side won. If the digest cannot show something (for
  example enemy losses outside your sight), say so instead of guessing.
- Judge your command, not luck: what you ordered, when, and with what effect.
- Be concrete. Quote units by name and times in minutes.
- Suggest improvements only if you can point to evidence for them.

Write the review in Markdown, in English, with exactly these sections:
## Result
One or two sentences: outcome, points, kill/death, objectives.
## What worked
Up to 4 bullets with evidence.
## What went wrong
Up to 6 bullets, most costly first, each with evidence and the cost (men, objective, time).
## Orders and rule corrections
What the server had to fix, and what that says about your orders.
## Recommended changes
Up to 6 bullets. Say whether each belongs in strategy.md (doctrine), game_rules.md (game
rules) or in the code/prompt, and write the exact line you would add or change.
## Confidence
One or two sentences on how much the data allows you to conclude.
"""


def _minutes(seconds):
    return f"{int(seconds // 60)} min"


def build_digest(result, journal, stats, owner_log, timeline, backend_name, strategy_text, rules_text):
    lines = [f"AI side: {result['ai_side']}. Backend/model: {backend_name}.",
             f"RESULT: {result['outcome'].upper()} for the AI ({result['outcome_source']}); "
             f"points {result['points']}; duration {_minutes(result['duration_s'])}.",
             f"Source of the result: {result['outcome_source']}. {result.get('outcome_reason') or ''} "
             f"Game text: {result['game_result_for_player']!r} (human player's point of view).",
             f"Objectives at the end: AI {result['objectives']['ai']} ({result['objectives']['ai_vp']} VP), "
             f"player {result['objectives']['player']} ({result['objectives']['player_vp']} VP), "
             f"unheld {result['objectives']['unheld']}.",
             f"Men lost by the AI: {result['own_men_lost']} of {result['own_men_start']}. Enemy men lost "
             f"(counted only while visible): at least {result['enemy_men_lost_seen']}. "
             f"Kill/death in men {result['kd_men']}; units broken or lost: AI {result['own_units_lost']}, "
             f"enemy {result['enemy_units_broken_seen']}. Verdict: {result['verdict']}."]
    if owner_log:
        lines.append("OBJECTIVE CHANGES:")
        lines += [f"- {_minutes(t)}: {name} {before} -> {after}" for t, name, before, after in owner_log[-15:]]
    if timeline:
        lines.append("CASUALTY TIMELINE (minute: AI men lost so far / enemy men lost so far, seen):")
        lines.append("; ".join(f"{_minutes(t)}: {own:.0f}/{foe:.0f}" for t, own, foe in timeline[-16:]))
    lines.append("AI BRIGADES (most losses first):")
    lines += [f"- {b['name']} ({b['kind']}): -{b['men_lost']} men, lowest morale {b['lowest_morale']}, end {b['end']}"
              for b in result["brigades"][:10]]
    if journal:
        totals = {}
        for j in journal:
            for cmd, n in j["orders"].items():
                totals[cmd] = totals.get(cmd, 0) + n
        lines.append(f"ORDERS GIVEN OVER {len(journal)} planning turns: "
                     + ", ".join(f"{k} {v}" for k, v in sorted(totals.items(), key=lambda kv: -kv[1])))
    if stats:
        lines.append("SERVER CORRECTIONS (orders the server had to change or drop):")
        lines += [f"- {k}: {v}" for k, v in sorted(stats.items(), key=lambda kv: -kv[1])]
    if journal:
        step = max(1, len(journal) // 14)
        lines.append("SAMPLE OF YOUR OWN REASONING (time: reasoning):")
        for j in journal[::step][:14]:
            lines.append(f"- {_minutes(j['time'])}: {j['reasoning'][:220]}")
    lines += ["", "THE INSTRUCTIONS YOU WERE GIVEN", "--- game_rules.md ---", rules_text.strip()[:6000],
              "--- strategy.md ---", strategy_text.strip()[:6000], "",
              "Write the after-action review now."]
    return "\n".join(lines)


def write_assessment(backend, backend_name, result, journal, stats, owner_log, timeline,
                     strategy_text, rules_text, report_dir="reports"):
    """Ask the model for the review and save it next to the battle report. Returns the text."""
    digest = build_digest(result, journal, stats, owner_log, timeline, backend_name,
                          strategy_text, rules_text)
    text = backend.complete(ASSESSMENT_SYSTEM, digest).strip()
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, time.strftime("assessment-%Y%m%d-%H%M%S.md"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# After-action review ({result['ended']}, {backend_name})\n\n{text}\n")
    return text, path
