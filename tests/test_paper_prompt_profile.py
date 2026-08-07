import unittest
from types import SimpleNamespace
from unittest.mock import patch

from thought_ics import paper_prompts
from thought_ics.chain_cache import get_cache_key
from thought_ics.localization.third_party_api import call_openai_api_generate
from thought_ics.prompt_profiles import get_prompt_profile
from thought_ics.self_correction import (
    _parse_localization_step,
    identify_error_step,
    identify_error_step_with_mv,
    verify_solution_correctness,
)
from thought_ics.thought_mdp import ToTAgent, ToTEnvironment


class RecordingManager:
    def __init__(self):
        self.prompts = []
        self.calls = []

    def generate(self, prompts, **kwargs):
        self.prompts.extend(prompts)
        self.calls.append(kwargs)
        return [r"Looks correct. \boxed{0}"] * len(prompts)


def completion(text, finish_reason):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(total_tokens=10, completion_tokens=5),
    )


class PaperPromptProfileTests(unittest.TestCase):
    def test_profile_uses_preserved_paper_prompt(self):
        profile = get_prompt_profile("paper")

        self.assertEqual(profile.generation_prompt, paper_prompts.GENERATION_PROMPT)
        self.assertEqual(
            profile.stop_sequences,
            tuple(paper_prompts.PAPER_STOP_SEQUENCES),
        )
        self.assertEqual(profile.max_tokens_per_thought, 150)
        self.assertTrue(profile.number_thoughts)
        self.assertEqual(paper_prompts.PAPER_MAX_DEPTH, 100)
        self.assertIn(
            "1. Total arrangements without restrictions",
            paper_prompts.GENERATION_PROMPT,
        )
        self.assertIn(
            "Append thoughts in the current state, if any",
            paper_prompts.GENERATION_PROMPT,
        )

    def test_paper_profile_numbers_appended_thought_history(self):
        profile = get_prompt_profile("paper")
        env = ToTEnvironment(
            max_depth=100,
            prompt_template=profile.generation_prompt,
            number_thoughts=profile.number_thoughts,
        )
        state = env.reset(
            "test question",
            initial_thoughts=["first thought", "second thought"],
        )

        prompt = env.state_to_prompt(state)

        self.assertTrue(
            prompt.endswith(
                "Append thoughts in the current state, if any\n"
                "1. first thought</thought>\n"
                "2. second thought</thought>\n"
            )
        )

    def test_paper_agent_strips_model_generated_thought_number(self):
        agent = ToTAgent(
            model_manager=object(),
            strip_leading_thought_number=True,
        )

        action = agent._parse_action("1. first thought")

        self.assertEqual(action.thought, "first thought")

    def test_paper_profile_uses_paper_localization_prompt(self):
        manager = RecordingManager()
        chain = ["first thought", r"answer \boxed{42}"]

        identify_error_step(
            manager,
            "problem",
            chain,
            "42",
            autonomy_level=3,
            prompt_profile="paper",
        )

        expected = paper_prompts.localization_prompt(
            "problem",
            chain,
            ground_truth="42",
            autonomy_level=3,
        )
        self.assertEqual(manager.prompts, [expected])
        self.assertNotIn("auto_expand_on_length", manager.calls[0])
        self.assertNotIn("generation_purpose", manager.calls[0])

    def test_mv_localization_also_uses_paper_prompt(self):
        manager = RecordingManager()
        chain = ["first thought", r"answer \boxed{42}"]

        identify_error_step_with_mv(
            manager,
            "problem",
            chain,
            "42",
            autonomy_level=3,
            mv_k=2,
            prompt_profile="paper",
        )

        expected = paper_prompts.localization_prompt(
            "problem",
            chain,
            ground_truth="42",
            autonomy_level=3,
        )
        self.assertEqual(manager.prompts, [expected])
        self.assertEqual(manager.calls[0]["n"], 2)

    def test_paper_cache_key_is_isolated(self):
        common = {
            "model_name": "Qwen/Qwen2.5-32B-Instruct",
            "dataset_name": "amc23",
            "n_problems": 40,
            "seed": 42,
            "temperature": 0.5,
            "max_depth": 100,
            "max_tokens_per_thought": 150,
        }

        legacy_key = get_cache_key(**common)
        paper_key = get_cache_key(
            **common,
            prompt_profile="paper_iclr2026_v2",
        )

        self.assertNotEqual(legacy_key, paper_key)

    def test_remote_generation_does_not_retry_length_finish(self):
        create = unittest.mock.Mock(
            return_value=completion("truncated", "length")
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create),
            )
        )

        with patch(
            "thought_ics.localization.third_party_api._create_openai_client",
            return_value=client,
        ):
            result = call_openai_api_generate(
                prompt="prompt",
                api_key="test-key",
                model="test-model",
                max_tokens=150,
                max_retries=3,
            )

        self.assertEqual(result, "truncated")
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["max_tokens"], 150)

    def test_verification_uses_remote_budget_without_auto_expand(self):
        manager = RecordingManager()
        manager.generate = unittest.mock.Mock(
            return_value=[r"Correct. \boxed{YES}"]
        )

        believed_correct, _ = verify_solution_correctness(
            manager,
            "problem",
            [r"answer \boxed{42}"],
        )

        self.assertTrue(believed_correct)
        kwargs = manager.generate.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], 1024)
        self.assertNotIn("auto_expand_on_length", kwargs)
        self.assertNotIn("generation_purpose", kwargs)

    def test_localization_clamps_boxed_value_to_last_step(self):
        self.assertEqual(
            _parse_localization_step(r"Answer is \boxed{265}", 8),
            8,
        )

    def test_localization_uses_last_integer_fallback(self):
        self.assertEqual(
            _parse_localization_step(
                "Step 1 seems fine. The final erroneous step is 3",
                8,
            ),
            3,
        )

    def test_localization_clamps_last_integer_fallback(self):
        self.assertEqual(
            _parse_localization_step(
                "Step 1 seems fine. The final answer was 265",
                8,
            ),
            8,
        )


if __name__ == "__main__":
    unittest.main()
