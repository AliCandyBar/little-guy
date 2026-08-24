from crewai import Agent, Task
from crewai_tools import (
    BraveSearchTool,
    ScrapeWebsiteTool
)
from pydantic import BaseModel


brave_search = BraveSearchTool()

website_scraper = ScrapeWebsiteTool()

class SelectedArticle(BaseModel):
    headline: str
    source: str
    url: str
    publication_date: str
    summary: str
    relevance_to_guild: str

research_agent = Agent(
    role="Technology News Researcher",

    goal=(
        "Research recent, factual, discussion-worthy news relating "
        "to artificial intelligence, programming, Linux, "
        "open-source software, technology, and developer tools."
    ),

    backstory=(
        "You are Guild.AI's technology news researcher.\n\n"

        "Your responsibility is to find recent technology news "
        "that will encourage meaningful discussion within the "
        "Guild.AI community.\n\n"

        "Always read the source article before making a recommendation.\n\n"

        "Prioritize:\n"
        "- Official announcements\n"
        "- Release notes\n"
        "- Research papers\n"
        "- Project blogs\n"
        "- GitHub releases\n"
        "- Reputable technology journalism\n\n"

        "Do NOT:\n"
        "- Use clickbait articles.\n"
        "- Use controversial articles that are likely to cause arguments or flame wars.\n"
        "- Use rumors or speculation.\n"
        "- Use sponsored content presented as news.\n"
        "- Use politics unrelated to technology.\n"
        "- Use duplicate or substantially similar stories.\n"
        "- Invent facts not supported by the source article."
    ),

    tools=[
        brave_search,
        website_scraper
    ],

    allow_delegation=False,

    verbose=True
)


def create_research_task(
    recent_history: list[dict]
) -> Task:

    if recent_history:
        history_text = "\n".join(
            (
                f"- {item['article_title']} "
                f"({item['article_url']})"
            )
            for item in recent_history
        )
    else:
        history_text = "No previous polls have been posted yet."

    return Task(
        description=(
            "Research recent technology news from approximately "
            "the last 7 to 14 days.\n\n"

            "Focus on:\n"
            "- Artificial Intelligence\n"
            "- Programming Languages\n"
            "- Software Development\n"
            "- Developer Tools\n"
            "- Linux\n"
            "- Hardware and Technology\n"
            "- Open Source\n\n"

            "Internally research and compare 5 strong candidate "
            "stories using Brave Search and the website scraper.\n\n"

            "Read promising source articles in depth before selecting one.\n\n"

            "Choose exactly ONE final story for the Guild.AI weekly poll.\n\n"

            "IMPORTANT:\n"
            "- Every returned field must refer to the SAME article.\n"
            "- The headline, source, URL, publication date, and summary "
            "must all come from the selected article.\n"
            "- Do not combine information from different candidate stories.\n"
            "- The URL must be the exact URL for the article summarized.\n\n"

            "Do not select the same article, news event, or substantially "
            "similar story that has already been used.\n\n"

            "Previously used stories:\n"
            f"{history_text}"
        ),

        expected_output=(
            "One selected article with its headline, source, URL, "
            "publication date, factual summary, and Guild.AI relevance."
        ),

        output_pydantic=SelectedArticle,

        agent=research_agent
    )