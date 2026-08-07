"""Original prompts as used in the published Thought-ICS paper — kept for REFERENCE.

These are the exact thought-by-thought generation template and error-localization prompts
used for the experiments in the paper. They are **not** the active defaults: the live pipeline
now loads the refined prompts in ``thought_ics.recommended_prompts``. This module is provided so
the original setup remains available for inspection or exact reproduction of the paper results.

To reproduce the paper exactly, pass these explicitly, e.g.:
    from thought_ics import paper_prompts
    env = ToTEnvironment(
        max_depth=paper_prompts.PAPER_MAX_DEPTH,
        prompt_template=paper_prompts.GENERATION_PROMPT,
        number_thoughts=True,
    )
and use ``paper_prompts.localization_prompt(...)`` in place of the default localizer.
"""

from typing import List

# Paper defaults from Appendix E.4-E.5: generation used in-context examples,
# a 100-step depth cap, and stop sequences ["</thought>", "\n\n"].
PAPER_MAX_DEPTH = 100
PAPER_MAX_TOKENS_PER_THOUGHT = 150
PAPER_STOP_SEQUENCES = ["</thought>", "\n\n"]

# --- Thought-by-thought generation (paper) -------------------------------------------
GENERATION_PROMPT = """You are solving a problem step-by-step.

Instructions:
1. State your next reasoning step (one observation, calculation, or deduction)
2. End each thought with </thought>
3. Continue until you reach the final answer, then write it in \\boxed{{answer}} format

Examples:

Q: In how many ways can 5 distinct books be arranged on a shelf if 2 specific books must not be adjacent?
1. Total arrangements without restrictions is 5! = 120</thought>
2. I need to subtract arrangements where the 2 specific books ARE adjacent</thought>
3. If I treat the 2 books as a single unit, I have 4 units to arrange: 4! = 24 ways</thought>
4. The 2 books within their unit can be arranged in 2! = 2 ways</thought>
5. So arrangements with the books adjacent = 24 × 2 = 48</thought>
6. Therefore, arrangements where they are NOT adjacent = 120 - 48 = \\boxed{{72}}</thought>

Q: A rectangle has area 48 and perimeter 28. What is the length of its diagonal?
1. Let length = l and width = w. From the area: lw = 48</thought>
2. From the perimeter: 2l + 2w = 28, so l + w = 14</thought>
3. From l + w = 14, we get w = 14 - l. Substituting into lw = 48: l(14 - l) = 48</thought>
4. Expanding: 14l - l² = 48, so l² - 14l + 48 = 0. Factoring: (l - 6)(l - 8) = 0</thought>
5. So l = 8 and w = 6 (or vice versa). Using the Pythagorean theorem: d² = 8² + 6² = 64 + 36 = 100</thought>
6. Therefore d = 10, so the answer is \\boxed{{10}}</thought>

Q: {question}

Append thoughts in the current state, if any
"""


# --- Error localization (paper) ------------------------------------------------------
def localization_prompt(problem: str, chain: List[str], ground_truth: str = None,
                        autonomy_level: int = 1) -> str:
    """Original paper localization prompt, by autonomy level (1=oracle, 2=binary, 3=autonomous)."""
    chain_text = ""
    for i, step in enumerate(chain, 1):
        chain_text += f"\nStep {i}: {step}"
    n = len(chain)

    if autonomy_level == 1:
        return (f"""Problem: {problem}

Current reasoning chain (WRONG - got incorrect answer):
{chain_text}

The correct answer should be {ground_truth}.

Analyze the reasoning chain step by step to identify where the error occurred. Which step number (1 to {n}) contains the first critical error that led to the wrong answer?

Provide your reasoning, then conclude with the step number in the format: \\boxed{{step_number}}
""")
    elif autonomy_level == 2:
        return (f"""Problem: {problem}

Current reasoning chain (WRONG - got incorrect answer):
{chain_text}

Your answer is incorrect. Analyze the reasoning chain step by step to identify where the error occurred. Which step number (1 to {n}) contains the first critical error (logical flaw, arithmetic error, or incorrect assumption)?

Provide your reasoning, then conclude with the step number in the format: \\boxed{{step_number}}
""")
    else:  # L3: exact Appendix E.2 autonomous localization prompt
        return (f"""You are given a reasoning trace: {chain_text.strip()}

Carefully verify your reasoning chain step by step. If you identify any errors (logical flaw, arithmetic error, or incorrect assumption), determine which step number (1 to {n}) contains the first critical error.

Also provide your reasoning. Then conclude with:
1. \\boxed{{step_number}} if you found an error
2. \\boxed{{0}} if the reasoning is correct
""")
