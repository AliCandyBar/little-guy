from crewai import Agent, Task


discussion_agent = Agent(
    role="Community Discussion Writer",

    goal=(
        "Turn a verified technology news story into a concise, "
        "professional discussion post for the Guild.AI Discord community."
    ),

    backstory=(
        "You are responsible for creating discussion content for "
        "Guild.AI's weekly technology polls.\n\n"

        "You receive a news story that has already been researched "
        "and selected by the Technology News Researcher.\n\n"

        "Your job is to explain the story clearly and encourage "
        "members to discuss it without exaggerating, editorializing, "
        "or adding unsupported information.\n\n"

        "The audience includes developers, students, AI enthusiasts, "
        "Linux users, and other technology-focused community members.\n\n"

        "Do NOT:\n"
        "- Research additional news stories.\n"
        "- Change the article being discussed.\n"
        "- Invent facts not included in the research.\n"
        "- Create sensational or inflammatory discussion prompts.\n"
        "- Add a visible 'Why It Matters' section.\n"
        "- Write an unnecessarily long summary.\n"
        "- Present opinions as facts."
    ),

    allow_delegation=False,

    verbose=True
)


def create_discussion_task(
    article_title: str,
    article_url: str,
    source_name: str,
    publication_date: str,
    article_summary: str,
    relevance_to_guild: str
) -> Task:
    """
    Creates the discussion content that will later be
    posted inside the thread attached to the Discord poll.

    relevance_to_guild is backend context only and should
    NOT appear as a separate section in the final post.
    """

    return Task(
        description=(
            "Create the opening discussion post for Guild.AI's "
            "weekly technology poll.\n\n"

            f"Article Title:\n{article_title}\n\n"

            f"Source:\n{source_name}\n\n"

            f"Article URL:\n{article_url}\n\n"

            f"Publication Date:\n{publication_date}\n\n"

            f"Research Summary:\n{article_summary}\n\n"

            f"Internal Relevance Context:\n"
            f"{relevance_to_guild}\n\n"

            "Use the relevance context only to better understand "
            "why this story is appropriate for the community. "
            "Do not include a visible 'Why It Matters' section.\n\n"

            "Create:\n"
            "1. A concise factual summary of the article, ideally "
            "around 50 to 100 words, keeping it succinct and to the point.\n"
            "2. A short discussion prompt that encourages members "
            "to explain their opinions and poll choices.\n\n"

            "Keep the language professional, approachable, and neutral."
        ),

        expected_output=(
            "Return the discussion content with exactly these parts:\n\n"

            "Summary:\n"
            "[Concise factual article summary]\n\n"

            "Discussion Prompt:\n"
            "[Short, open-ended discussion prompt]"
        ),

        agent=discussion_agent
    )