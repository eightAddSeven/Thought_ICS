import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thought_ics.eval.batch_eval import (
    run_iterative_correction_with_cached_chain,
)
from thought_ics.metrics import compute_metrics


class ConfidenceSafeguardTests(unittest.TestCase):
    def run_case(
        self,
        initial_answer,
        generated_answer,
        verify_decisions,
        localization_decisions,
        max_iterations,
        safeguard,
    ):
        with (
            patch(
                "thought_ics.eval.batch_eval.verify_solution_correctness",
                side_effect=[
                    (decision, f"verify-{index}")
                    for index, decision in enumerate(verify_decisions)
                ],
            ),
            patch(
                "thought_ics.eval.batch_eval.identify_error_step",
                side_effect=[
                    (decision, f"localize-{index}")
                    for index, decision in enumerate(localization_decisions)
                ],
            ),
            patch(
                "thought_ics.eval.batch_eval.generate_from_prefix",
                return_value=[f"corrected \\\\boxed{{{generated_answer}}}"],
            ),
        ):
            return run_iterative_correction_with_cached_chain(
                manager=object(),
                problem="test problem",
                ground_truth="42",
                initial_chain=[f"initial \\\\boxed{{{initial_answer}}}"],
                autonomy_level=3,
                max_iterations=max_iterations,
                verify=True,
                confidence_safeguard=safeguard,
            )

    def test_v_l_disagreement_resets_to_initial_answer(self):
        result = self.run_case(
            initial_answer="42",
            generated_answer="7",
            verify_decisions=[False, False],
            localization_decisions=[1, 0],
            max_iterations=2,
            safeguard=True,
        )

        self.assertEqual(result["termination_reason"], "v_l_disagreement")
        self.assertEqual(result["thought_ics_s_answer"], "7")
        self.assertFalse(result["thought_ics_s_correct"])
        self.assertEqual(result["thought_ics_a_answer"], "42")
        self.assertTrue(result["thought_ics_a_correct"])
        self.assertTrue(result["safeguard_applied"])
        self.assertEqual(result["final_answer"], "42")
        self.assertTrue(result["success"])

    def test_verified_accuracy_keeps_corrected_answer(self):
        result = self.run_case(
            initial_answer="7",
            generated_answer="42",
            verify_decisions=[False, True],
            localization_decisions=[1],
            max_iterations=2,
            safeguard=True,
        )

        self.assertEqual(result["termination_reason"], "verified_accuracy")
        self.assertEqual(result["thought_ics_s_answer"], "42")
        self.assertEqual(result["thought_ics_a_answer"], "42")
        self.assertFalse(result["safeguard_applied"])
        self.assertTrue(result["success"])

    def test_max_iterations_resets_to_initial_answer(self):
        result = self.run_case(
            initial_answer="42",
            generated_answer="7",
            verify_decisions=[False],
            localization_decisions=[1],
            max_iterations=1,
            safeguard=True,
        )

        self.assertEqual(result["termination_reason"], "max_iterations")
        self.assertEqual(result["thought_ics_s_answer"], "7")
        self.assertEqual(result["thought_ics_a_answer"], "42")
        self.assertTrue(result["safeguard_applied"])
        self.assertTrue(result["success"])

    def test_metrics_report_paired_s_and_a_accuracy(self):
        results = {
            "results": [
                {
                    "iterations": [
                        {"iteration": 0, "correct": True, "error_step": None, "chain": ["a"]},
                        {"iteration": 1, "correct": False, "error_step": 1, "chain": ["b"]},
                    ],
                    "success": True,
                    "final_correct": True,
                    "thought_ics_s_correct": False,
                    "thought_ics_a_correct": True,
                    "termination_reason": "max_iterations",
                },
                {
                    "iterations": [
                        {"iteration": 0, "correct": False, "error_step": None, "chain": ["c"]},
                        {"iteration": 1, "correct": True, "error_step": 1, "chain": ["d"]},
                    ],
                    "success": True,
                    "final_correct": True,
                    "thought_ics_s_correct": True,
                    "thought_ics_a_correct": True,
                    "termination_reason": "verified_accuracy",
                },
            ]
        }
        config = {
            "dataset": "amc23",
            "max_iterations": 1,
            "confidence_safeguard": True,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            experiment_dir = Path(temp_dir)
            (experiment_dir / "results.json").write_text(
                json.dumps(results),
                encoding="utf-8",
            )
            (experiment_dir / "config.json").write_text(
                json.dumps(config),
                encoding="utf-8",
            )
            metrics = compute_metrics(experiment_dir)

        comparison = metrics["autonomous_variant_comparison"]
        self.assertEqual(comparison["thought_ics_s"]["accuracy"], 0.5)
        self.assertEqual(comparison["thought_ics_a"]["accuracy"], 1.0)
        self.assertEqual(comparison["a_minus_s"], 0.5)
        self.assertEqual(metrics["overall_performance"]["final_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
