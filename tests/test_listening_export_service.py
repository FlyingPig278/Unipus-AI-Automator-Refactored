import unittest


class ListeningExportServiceTests(unittest.TestCase):
    def test_answer_mapping_uses_one_answer_per_single_choice_question(self):
        from src.services.listening_export_service import ListeningExportService

        mapped = ListeningExportService.map_answers_to_questions(
            "single_choice",
            ["A", "D"],
            question_count=2,
        )

        self.assertEqual(mapped, ["A", "D"])

    def test_answer_mapping_keeps_multiple_choice_answers_together_for_one_question(self):
        from src.services.listening_export_service import ListeningExportService

        mapped = ListeningExportService.map_answers_to_questions(
            "multiple_choice",
            ["A", "C", "D"],
            question_count=1,
        )

        self.assertEqual(mapped, ["A, C, D"])

    def test_render_markdown_contains_transcript_options_and_cached_answer(self):
        from src.services.listening_export_service import ListeningExportEntry
        from src.services.listening_export_service import ListeningExportService

        entry = ListeningExportEntry(
            breadcrumb=["Course", "Unit 1", "News report"],
            question_index=1,
            media_url="https://example.test/audio.mp3",
            transcript="The library closes at six.",
            question="When does the library close?",
            options=["A. At five.", "B. At six.", "C. At seven.", "D. At eight."],
            answer="B",
        )

        markdown = ListeningExportService.render_markdown([entry], generated_at="2026-06-17 20:00")

        self.assertIn("# U校园听力题导出", markdown)
        self.assertIn("Course > Unit 1 > News report", markdown)
        self.assertIn("The library closes at six.", markdown)
        self.assertIn("A. At five.", markdown)
        self.assertIn("答案：B", markdown)


if __name__ == "__main__":
    unittest.main()
