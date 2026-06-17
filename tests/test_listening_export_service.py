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

    def test_render_markdown_groups_questions_by_audio_page(self):
        from src.services.listening_export_service import ListeningExportEntry
        from src.services.listening_export_service import ListeningExportService

        entries = [
            ListeningExportEntry(
                breadcrumb=["Course", "Unit 1", "News report"],
                question_index=1,
                media_url="https://example.test/news.mp3",
                transcript="The library closes at six.",
                question="When does the library close?",
                options=["A. At five.", "B. At six.", "C. At seven.", "D. At eight."],
                answer="B",
            ),
            ListeningExportEntry(
                breadcrumb=["Course", "Unit 1", "News report"],
                question_index=2,
                media_url="https://example.test/news.mp3",
                transcript="The library closes at six.",
                question="Where is the speaker?",
                options=["A. In a shop.", "B. In a library.", "C. In a bank.", "D. In a station."],
                answer="A",
            ),
            ListeningExportEntry(
                breadcrumb=["Course", "Unit 1", "Conversation"],
                question_index=1,
                media_url="",
                transcript="The T-shirt is fifteen dollars.",
                question="How much is the T-shirt?",
                options=["A. $5.", "B. $10.", "C. $15.", "D. $20."],
                answer="C",
            ),
        ]

        markdown = ListeningExportService.render_markdown(entries, generated_at="2026-06-17 20:00")

        self.assertIn("# U校园听力题导出", markdown)
        self.assertEqual(markdown.count("## Course > Unit 1 > News report"), 1)
        self.assertEqual(markdown.count("---"), 1)
        self.assertIn("音频：[打开音频](https://example.test/news.mp3)", markdown)
        self.assertIn("The library closes at six.", markdown)
        self.assertIn("1. ( B ) When does the library close?", markdown)
        self.assertIn("   A. At five.", markdown)
        self.assertIn("2. ( A ) Where is the speaker?", markdown)
        self.assertIn("## Course > Unit 1 > Conversation", markdown)
        self.assertIn("1. ( C ) How much is the T-shirt?", markdown)


if __name__ == "__main__":
    unittest.main()
