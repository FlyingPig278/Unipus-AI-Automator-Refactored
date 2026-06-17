SHORT_ANSWER_STRATEGY_CLASS_NAMES = {
    "ShortAnswerStrategy",
    "QAVoiceStrategy",
}


def filter_available_strategies(strategies: list[type], skip_short_answer: bool) -> list[type]:
    """Return strategies enabled by runtime configuration."""
    if not skip_short_answer:
        return list(strategies)

    return [
        strategy
        for strategy in strategies
        if strategy.__name__ not in SHORT_ANSWER_STRATEGY_CLASS_NAMES
    ]
