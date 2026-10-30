"""
Unit test suite for externalized prompt loading and dynamic hot-reloading.
Verifies that:
1. All agent and task prompts exist as external markdown files in prompts/.
2. The prompt_loader utility safely loads, caches, and formats prompts without KeyError on JSON.
3. Disk changes to markdown prompts are detected and hot-reloaded automatically.
4. All backend agents and engines import and consume externalized prompts.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))

import prompt_loader
from agents.supervisor import supervisor_agent, get_supervisor_prompt
from agents.document_agent import DocumentAnalysisAgent, get_document_agent_prompt
from agents.retrieval_agent import RetrievalAgent, get_retrieval_agent_prompt
from agents.evaluation_agent import (
    EvaluationAgent,
    get_evaluation_agent_prompt,
    get_similarity_agent_prompt,
)
from agents.optimization_agent import OptimizationAndHarmonizationAgent, get_optimization_agent_prompt
from agents.validation_node_agent import ValidationDecisionAgent, get_validation_agent_prompt


class TestPromptExternalization(unittest.TestCase):

    def setUp(self):
        prompt_loader.clear_prompt_cache()

    def test_all_expected_prompts_exist(self):
        """Ensures all required agent markdown files exist in prompts/ and are non-empty."""
        expected = [
            "harmonization_agent",
            "scoring_agent",
            "single_sop_optimization",
            "similarity_agent",
            "orchestrator_agent",
            "rag_chat_agent",
            "document_agent",
            "validation_agent",
            "remediation_agent",
            "simplification_agent",
            "refinement_agent",
            "translation_to_english",
            "translation_to_target",
        ]
        available = prompt_loader.list_available_prompts()
        for p in expected:
            self.assertIn(p, available, f"Prompt '{p}.md' must exist in prompts/ directory")
            content = prompt_loader.load_prompt(p)
            self.assertGreater(len(content.strip()), 50, f"Prompt '{p}' must not be empty")

    def test_harmonization_agent_prompt_specifications(self):
        """Verifies Kenvue QMS/GMP authoring rules and language rules in harmonization_agent.md."""
        content = prompt_loader.load_prompt("harmonization_agent")
        # Language rules
        self.assertIn("Must", content)
        self.assertIn("Must Not", content)
        self.assertIn("Shall", content)
        self.assertIn("Should", content)
        self.assertIn("Will", content)
        # 10-tier mandatory structure
        self.assertIn("1.0 Purpose", content)
        self.assertIn("2.0 Scope", content)
        self.assertIn("3.0 Key Terms", content)
        self.assertIn("4.0 Roles and Responsibilities", content)
        self.assertIn("5.0 Requirements", content)
        self.assertIn("6.0 Process Flow", content)
        self.assertIn("7.0 Procedure", content)
        self.assertIn("8.0 References", content)
        self.assertIn("9.0 Appendices", content)
        self.assertIn("Document Revision History", content)

    def test_scoring_agent_prompt_specifications(self):
        """Verifies Kenvue 3-dimension rubric in scoring_agent.md."""
        content = prompt_loader.load_prompt("scoring_agent")
        self.assertIn("template_score", content)
        self.assertIn("readability_score", content)
        self.assertIn("quality_score", content)
        self.assertIn("sug_struct", content)
        self.assertIn("sug_imperative", content)
        self.assertIn("sug_tolerances", content)

    def test_format_prompt_safe_interpolation_with_json(self):
        """Verifies that format_prompt safely interpolates variables without KeyError on JSON syntax."""
        template_with_json = 'Title: {doc_title}\nReturn: {"heading": "{heading}", "items": [1, 2]}'
        formatted = prompt_loader.format_prompt(
            template_with_json,
            doc_title="Bottle Labeling SOP",
            heading="1.0 Purpose",
        )
        self.assertIn("Title: Bottle Labeling SOP", formatted)
        self.assertIn('"heading": "1.0 Purpose"', formatted)
        self.assertIn('"items": [1, 2]', formatted)

    def test_agent_getters_return_external_prompts(self):
        """Verifies that all agent helper functions load external prompts."""
        sup_prompt = get_supervisor_prompt()
        self.assertIn("Supervisor and Central Orchestrator Agent", sup_prompt)

        doc_prompt = get_document_agent_prompt()
        self.assertIn("Document Analysis", doc_prompt)

        eval_prompt = get_evaluation_agent_prompt()
        self.assertIn("Quality Systems and GMP Compliance Auditor", eval_prompt)

        opt_prompt = get_optimization_agent_prompt()
        self.assertIn("Kenvue SOP Harmonization Agent", opt_prompt)

        rag_prompt = get_retrieval_agent_prompt()
        self.assertIn("Kenvue RAG Chat", rag_prompt)

        val_prompt = get_validation_agent_prompt()
        self.assertIn("QA Validation & Compliance Decision Agent", val_prompt)

        sim_prompt = get_similarity_agent_prompt()
        self.assertIn("SOP Comparison & Similarity Assessment Agent", sim_prompt)

    def test_hot_reload_on_disk_change(self):
        """Verifies that modifying a prompt file on disk is immediately loaded on the next call."""
        prompts_dir = prompt_loader.get_prompts_dir()
        temp_file_name = f"test_temporary_prompt_{int(time.time())}.md"
        temp_path = os.path.join(prompts_dir, temp_file_name)

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write("Initial prompt content version 1.0")

            loaded_v1 = prompt_loader.load_prompt(temp_file_name)
            self.assertEqual(loaded_v1, "Initial prompt content version 1.0")

            # Emulate an external edit by a user
            time.sleep(0.05)
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write("Updated prompt content version 2.0 with new directives")

            loaded_v2 = prompt_loader.load_prompt(temp_file_name)
            self.assertEqual(loaded_v2, "Updated prompt content version 2.0 with new directives")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
