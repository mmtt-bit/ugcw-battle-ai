# Token usage (estimates)

Measured on synthetic battles built by cloning a real mid-battle state (v0.1.2-beta). Characters were
converted at about 3 characters per token for the battle state and 4 for the system prompt (no tokenizer
was used: count on +/-20 %). Answer sizes are assumptions; the model's own thinking is not included.
The server prints the real figures after every call and in the battle report: prefer those.

"Typical" = 40 % of your units in the rear and 70 % of the enemy visible; "worst" = everything at the front.

## Per model call

| | 25 brigades (small) | 60 brigades, full prompt | 60 brigades, `large` profile |
|---|---|---|---|
| System prompt (cached by Claude) | ~7,500 | ~8,400 | ~8,400 |
| Battle state, typical | ~4,700 | ~10,100 | ~8,300 |
| Battle state, worst | ~5,700 | ~11,300 | ~9,400 |
| Answer (assumed) | ~500 | ~900 | ~900 |

## Per hour of engaged battle (about 57 calls: one per minute, a few quiet turns skipped)

| | 25 brigades | 60 brigades, `large` |
|---|---|---|
| Input not cached | ~270,000 (worst ~325,000) | ~470,000 (worst ~535,000) |
| Read from cache | ~430,000 | ~480,000 |
| Answers | ~28,000 | ~51,000 |

## Levers

- `timing.engaged_interval_s`: 60 to 90 seconds cuts the calls by a third, at the cost of slower reactions.
- `economy.morale_drop`: 0.15 or 0.2 skips more quiet turns in heavy fighting.
- `scale.large`: the radii and caps of the compact prompt.
- `claude_code.effort`: try a lower effort and compare results on the scoreboard.

## Reflexes (v0.1.3-beta)

The plugin's reflexes cost no tokens when they act. The model only reads what they did: about 300 tokens of rules in
the cached system prompt and, per turn, at most 8 event lines (about 100 to 250 tokens). Because urgent reactions no
longer wait for a turn, turns in contact come every 90 s instead of 60: about 38 calls per hour of engaged battle
instead of 57. For 25 brigades: about 190,000 tokens not cached per hour instead of 270,000 (-30 %), answers about
20,000 instead of 28,000.
