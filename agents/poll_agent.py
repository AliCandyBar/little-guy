from crewai import Agent, Task


poll_agent = Agent(
    role="Community Poll Writer",

    goal=(
        "Turn a verified technology news story into one concise, "
        "engaging Discord poll for the Guild.AI community."
    ),

    backstory=(
        "You create Guild.AI's weekly community polls based on "
        "recent technology news that has already been researched "
        "and selected.\n\n"

        "Your job is to create a professional, neutral poll that "
        "encourages opinion and discussion rather than testing "
        "members on factual knowledge.\n\n"

        "The poll will use Discord's native poll feature, which "
        "provides only one question field and a list of answers.\n\n"

        "The poll question must therefore combine the article "
        "headline and the discussion question on the same line.\n\n"

        "Do NOT:\n"
        "- Research additional stories.\n"
        "- Change the selected article.\n"
        "- Create trivia or quiz questions.\n"
        "- Create fewer or more than four answers.\n"
        "- Use 'Other' as an answer.\n"
        "- Use joke or meme answers.\n"
        "- Create overlapping or nearly identical answers.\n"
        "- Use biased or leading wording.\n"
        "- Invent facts not supported by the research."
    ),

    allow_delegation=False,

    verbose=True
)


def create_poll_task(
    article_title: str,
    article_summary: str,
    relevance_to_guild: str,
    discussion_prompt: str
) -> Task:
    """
    Creates the poll question and exactly four answers.

    relevance_to_guild is internal context only.
    """

    return Task(
        description=(
            "Create one Discord poll based on the selected "
            "technology news story.\n\n"

            f"Article Headline:\n{article_title}\n\n"

            f"Article Summary:\n{article_summary}\n\n"

            f"Internal Relevance Context:\n"
            f"{relevance_to_guild}\n\n"

            f"Discussion Context:\n"
            f"{discussion_prompt}\n\n"

            "Poll requirements:\n"
            "- Create exactly ONE poll.\n"
            "- Create exactly FOUR answer choices.\n"
            "- Each answer must be 40 characters or fewer whenever possible.\n"
            "- Never exceed Discord's 55-character answer limit.\n"
            "- Begin the poll question with one relevant emoji.\n"
            "- Put the article headline and the discussion question "
            "on the same line.\n"
            "- Use this structure:\n"
            "  [emoji] [headline] — [discussion question]\n"
            "- Preserve the original headline when practical.\n"
            "- If the headline is too long, shorten it without "
            "changing its factual meaning.\n"
            "- Make the question opinion-based rather than factual.\n"
            "- Keep all four answers concise and distinct.\n"
            "- Make the answers directly relevant to the story.\n"
            "- Represent different reasonable viewpoints or priorities.\n\n"

            "Emoji guidance:\n"
            "- AI / Machine Learning: 🤖\n"
            "- Programming: 💻\n"
            "- Linux: 🐧\n"
            "- Open Source: 🌐\n"
            "- Cybersecurity: 🔒\n"
            "- Developer Tools: 🛠️\n"
            "- Research: 🔬\n"
            "- Cloud / Infrastructure: ☁️\n"
            "- Hardware: 🖥️\n"
            "- Guild.AI: 💬\n\n"

            "Do not add explanations, article links, summaries, "
            "or discussion text to the poll itself."
        ),

        expected_output=(
            "Return exactly:\n\n"

            "Question:\n"
            "[One poll question using emoji + headline + discussion question]\n\n"

            "Answers:\n"
            "1. [Answer]\n"
            "2. [Answer]\n"
            "3. [Answer]\n"
            "4. [Answer]"
        ),

        agent=poll_agent
    )