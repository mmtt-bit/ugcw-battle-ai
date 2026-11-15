# Token usage

Two parts: the figures of 0.1.4-beta, measured on recorded battles and estimated on their replay, then the earlier
estimates of 0.1.2-beta and 0.1.3-beta, kept for history. The server prints the real figures after every call and
in the battle report (`tokens`, `llm_calls`, `quiet_turns_skipped`): prefer those.

## 0.1.4-beta

### WIP4 (2026-11-11): the 15:27 battle, measured and replayed

Measured in game (WIP3, 41 calls, 119 minutes): 400,084 tokens written to the cache, 894,160 read, 26,244 out;
85 quiet turns skipped. The replay estimate of the same server gives 347,449 written (87 % of the measure).

| | WIP3 (replay) | WIP4 (replay) |
|---|---|---|
| System prompt, written once | 22,488 | 24,010 (+1,522: capture, garrisons, rotation limit, ammunition check, outnumbered) |
| Turn prompts, 41 calls | 324,960 | 303,245 (-6.7 %) |
| Total written | 347,449 | 327,255 (-5.8 %) |

Where it comes from: no ASSAULT PLAN block once the assault is abandoned (about 1,100 tokens a call from minute 20),
one "cannot march" line instead of one line per battery (about 500 tokens a call). The ammunition check adds no text
to the turn prompt (UNITS LOW ON AMMUNITION was already there, about 540 tokens at eight units); the weapon table
adds nothing for single-shot weapons and one or two words for the others. The larger system prompt is also read from
the cache at every call (a tenth of the input price): 1,522 x 40 calls = about 6,100 tokens' worth of reads.

### What is measured, what is estimated

- **Measured in game (0.1.3 builds of 2026-11-10, Claude Code backend, model `sonnet`)**: the `usage` block Claude
  Code returns for every call, stored in `logs/battle-*.jsonl`.
- **Estimated on replay (0.1.4)**: `tools/bench.py` replays the recorded states and events against the new server
  with the recorded model answers, and counts the characters of every prompt it would have sent
  (0.568 token per character for the turn prompt, 0.42 for the system prompt). Applied to the prompts 0.1.3 really
  sent, this estimate gives 100.8 %, 100.2 % and 95.7 % of the cache writes Claude Code reported for the three
  battles below. (The 0.1.2 estimates further down used 3 to 4 characters per token, without a tokenizer: about
  +/-20 %.)
- A replay cannot show what the new orders would have changed in the battle: the units move as they did in the
  recorded game. Calls, prompt sizes and rewrites are reliable; the course of the battle is not.
- **Not measured yet**: a battle played with the 0.1.4 server and DLL.

### Where the tokens go

Every call is a new Claude Code session. The system prompt (rules, perks, terrain, roster, briefing: about 21,000
tokens) is written to the prompt cache at the first call of a battle and read from it afterwards. The turn prompt is
written to the cache at every call and never read again. In the recorded battles Claude Code used the one-hour cache
(`ephemeral_1h_input_tokens`), whose writes cost twice the normal input price; cache reads cost a tenth of it.
So the cost of a battle is, in order: the turn prompts (number of calls x size), the system prompt (once, and again
at every change of its text), the answers.

(The 0.1.2 estimates below counted the battle state as "input not cached": with Claude Code it is written to the
cache at every call, which costs more than plain input.)

### Three recorded battles

| Battle (log) | 0.1.3 as played: calls / tokens written / cost | 0.1.3 final, replay | 0.1.4, replay |
|---|---|---|---|
| 15:54 Shiloh phase 3 | 29 / 419,556 / $1.86 | 17 calls, 231,000 | 12 calls, 118,000 |
| 17:05 same battle resumed | 16 / 249,092 / $1.11 | 17 calls, 264,000 | 14 calls, 142,000 |
| 11:42 | 25 / 281,784 (5 system prompt writes) / $1.28 | 16 calls, 207,000 (5 writes) | 12 calls, 77,000 (1 write) |

The 15:54 battle was played with a build that called the model at every state. The "0.1.3 final" column is the
replay made during the review with the published 0.1.3 server. Against it, 0.1.4 writes 49 %, 46 % and 63 % fewer
tokens.

Average turn prompt: 24,500 / 25,200 / 12,700 characters in the recorded battles; 14,200 / 15,100 / 8,200 on the
0.1.4 replays.

### What gives the saving

1. Fewer calls: the model is called for decisions (`economy.min_call_gap_s`, `max_gap_s`), the server's staff work
   runs at every state without it.
2. Compact turn prompt: normal cases are not written.
3. A system prompt that stays identical: briefing frozen at the first call, and late brigades no longer added to
   the cached roster. On the 11:42 replay one addition rewrote 21,800 tokens to save 6,100 over the rest of the battle
   (it would pay back after about 40 further calls). `economy.roster_max_folds` is 0 by default for that reason.

### Levers (0.1.4)

- `economy.min_call_gap_s` (150) and `economy.max_gap_s` (420): the main lever. 240 / 600 for fewer calls, 90 / 240
  for more model control.
- `economy.morale_drop`, `morale_drop_units`, `loss_share`, `new_enemy_men`: what counts as a reason to call the
  model once `min_call_gap_s` has passed.
- `scale.large`: the radii and caps of the compact prompt.
- `assessment.enabled` / `min_calls`: the after-action review is one more call per battle.
- `claude_code.effort`: try a lower effort and compare results on the scoreboard.
- `timing.staff_interval_s` does not change the tokens: the states it sets run the server's staff work, not the model.

### Not done, with the expected gain

- `claude_code.cache_ttl: "5m"`: writes at 1.25 times the input price instead of 2 (about a third off the write
  cost), but a cache that expired rewrites the system prompt. It wins as long as fewer than about one call in five
  comes after a break of more than five minutes. To be tried in a real battle.
- MISSION GOALS and the AMBITION text are repeated at every call (about 500 to 900 characters, 4 to 8 % of a turn
  prompt): their fixed part could move to the system prompt.
- Name and kind of your own units are in the roster and in every unit table (about 5 % of a turn prompt); kept,
  because the model writes its reasoning with the names.
- The after-action review sends up to 12,000 characters of the two instruction files (one call per battle, about
  6 to 10 % of a battle): `assessment.enabled: false` removes it.
- About 2/3 of the answer tokens are reasoning; answers are a small part of the cost (about 440 tokens a call).

## Earlier estimates (kept for history)

### 0.1.2-beta: synthetic battles

Measured on synthetic battles built by cloning a real mid-battle state (v0.1.2-beta). Characters were
converted at about 3 characters per token for the battle state and 4 for the system prompt (no tokenizer
was used: count on +/-20 %). Answer sizes are assumptions; the model's own thinking is not included.

"Typical" = 40 % of your units in the rear and 70 % of the enemy visible; "worst" = everything at the front.

#### Per model call

| | 25 brigades (small) | 60 brigades, full prompt | 60 brigades, `large` profile |
|---|---|---|---|
| System prompt (cached by Claude) | ~7,500 | ~8,400 | ~8,400 |
| Battle state, typical | ~4,700 | ~10,100 | ~8,300 |
| Battle state, worst | ~5,700 | ~11,300 | ~9,400 |
| Answer (assumed) | ~500 | ~900 | ~900 |

The system prompt measured on the recorded battles of 0.1.3 was about 21,000 tokens (perks, terrain, roster and
briefing were added since).

#### Per hour of engaged battle (about 57 calls: one per minute, a few quiet turns skipped)

| | 25 brigades | 60 brigades, `large` |
|---|---|---|
| Input not cached | ~270,000 (worst ~325,000) | ~470,000 (worst ~535,000) |
| Read from cache | ~430,000 | ~480,000 |
| Answers | ~28,000 | ~51,000 |

#### Levers (0.1.2 / 0.1.3; replaced by the 0.1.4 levers above)

- `timing.engaged_interval_s`: 60 to 90 seconds cuts the calls by a third, at the cost of slower reactions.
  (0.1.4: with the 0.1.4 DLL this interval no longer sets the number of model calls.)
- `economy.morale_drop`: 0.15 or 0.2 skips more quiet turns in heavy fighting.
- `scale.large`: the radii and caps of the compact prompt.
- `claude_code.effort`: try a lower effort and compare results on the scoreboard.

### 0.1.3-beta: reflexes

The plugin's reflexes cost no tokens when they act. The model only reads what they did: about 300 tokens of rules in
the cached system prompt and, per turn, at most 8 event lines (about 100 to 250 tokens). Because urgent reactions no
longer wait for a turn, turns in contact come every 90 s instead of 60: about 38 calls per hour of engaged battle
instead of 57. For 25 brigades: about 190,000 tokens not cached per hour instead of 270,000 (-30 %), answers about
20,000 instead of 28,000.
