import unittest


class StrategyRegistryTests(unittest.TestCase):
    def test_filter_available_strategies_removes_text_and_voice_short_answer(self):
        from src.strategy_registry import filter_available_strategies

        ShortAnswerStrategy = type("ShortAnswerStrategy", (), {})
        QAVoiceStrategy = type("QAVoiceStrategy", (), {})
        SingleChoiceStrategy = type("SingleChoiceStrategy", (), {})

        filtered = filter_available_strategies(
            [ShortAnswerStrategy, QAVoiceStrategy, SingleChoiceStrategy],
            skip_short_answer=True,
        )

        self.assertEqual(filtered, [SingleChoiceStrategy])

    def test_filter_available_strategies_keeps_everything_when_disabled(self):
        from src.strategy_registry import filter_available_strategies

        ShortAnswerStrategy = type("ShortAnswerStrategy", (), {})
        SingleChoiceStrategy = type("SingleChoiceStrategy", (), {})
        strategies = [ShortAnswerStrategy, SingleChoiceStrategy]

        self.assertEqual(
            filter_available_strategies(strategies, skip_short_answer=False),
            strategies,
        )


if __name__ == "__main__":
    unittest.main()
