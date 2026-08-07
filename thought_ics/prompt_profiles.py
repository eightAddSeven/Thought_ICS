"""Named prompt/protocol profiles for Thought-MDP generation.

The default ``recommended`` profile preserves the repository's refined
post-paper behavior. The ``paper`` profile reproduces the generation template
and decoding protocol documented in Appendix E of the ICLR 2026 paper.
"""

from dataclasses import dataclass
from typing import Tuple

from thought_ics import paper_prompts, recommended_prompts


@dataclass(frozen=True)
class ThoughtPromptProfile:
    """Generation settings that must change together for a prompt profile."""

    name: str
    cache_tag: str
    generation_prompt: str
    stop_sequences: Tuple[str, ...]
    max_tokens_per_thought: int
    number_thoughts: bool


def get_prompt_profile(
    name: str,
    max_tokens_per_thought: int = 150,
) -> ThoughtPromptProfile:
    """Return a validated Thought-MDP prompt profile."""

    normalized = name.strip().lower()
    if normalized == "recommended":
        return ThoughtPromptProfile(
            name="recommended",
            cache_tag="recommended_v1",
            generation_prompt=recommended_prompts.GENERATION_PROMPT_NO_EXAMPLES,
            stop_sequences=(recommended_prompts.THOUGHT_DELIMITER,),
            max_tokens_per_thought=max_tokens_per_thought,
            number_thoughts=False,
        )
    if normalized == "paper":
        return ThoughtPromptProfile(
            name="paper",
            cache_tag="paper_iclr2026_v2",
            generation_prompt=paper_prompts.GENERATION_PROMPT,
            stop_sequences=tuple(paper_prompts.PAPER_STOP_SEQUENCES),
            max_tokens_per_thought=paper_prompts.PAPER_MAX_TOKENS_PER_THOUGHT,
            number_thoughts=True,
        )
    raise ValueError(
        f"Unknown prompt profile '{name}'. Expected 'recommended' or 'paper'."
    )
