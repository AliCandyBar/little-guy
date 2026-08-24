from datetime import timedelta

import discord


async def post_weekly_poll(
    poll_channel: discord.TextChannel,
    poll_number: int,
    poll_question: str,
    answers: list[str],
    article_url: str,
    discussion_summary: str,
    discussion_prompt: str
) -> tuple[discord.Message, discord.Thread]:
    """
    Posts a native Discord poll, creates its discussion thread,
    posts the opening discussion message, and pins it.

    Returns:
        poll_message
        discussion_thread
    """

    # ---------------------------------------------------------
    # Validate poll answers
    # ---------------------------------------------------------

    if len(answers) != 4:
        raise ValueError(
            "Weekly polls must contain exactly 4 answers."
        )
    for answer in answers:
        if len(answer) > 55:
            raise ValueError(
                f"Poll answer exceeds Discord's 55-character limit: "
                f"{answer!r}"
            )

    # ---------------------------------------------------------
    # Create native Discord poll
    # ---------------------------------------------------------

    poll = discord.Poll(
        question=poll_question,
        duration=timedelta(days=7),
        multiple=False
    )

    for answer in answers:
        poll.add_answer(
            text=answer
        )

    # ---------------------------------------------------------
    # Post poll
    # ---------------------------------------------------------

    poll_message = await poll_channel.send(
        poll=poll
    )

    print(
        f"WEEKLY POLL: Poll #{poll_number} posted "
        f"with message ID {poll_message.id}",
        flush=True
    )

    # ---------------------------------------------------------
    # Create attached discussion thread
    # ---------------------------------------------------------

    thread = await poll_message.create_thread(
        name=(
            f"💬 Join the Discussion - #{poll_number}"
        )
    )

    print(
        f"WEEKLY POLL: Discussion thread created "
        f"with ID {thread.id}",
        flush=True
    )

    # ---------------------------------------------------------
    # Create opening discussion message
    # ---------------------------------------------------------

    discussion_text = (
        f"## 💬 Guild.AI Weekly Discussion #{poll_number}\n\n"

        f"### 📰 Source\n"
        f"{article_url}\n\n"

        f"### Summary\n"
        f"{discussion_summary}\n\n"

        f"### Discussion\n"
        f"{discussion_prompt}"
    )

    opening_message = await thread.send(
        discussion_text
    )

    print(
        "WEEKLY POLL: Opening discussion message posted.",
        flush=True
    )

    # ---------------------------------------------------------
    # Pin opening message
    # ---------------------------------------------------------

    try:
        await opening_message.pin(
            reason=(
                f"Opening message for weekly poll "
                f"#{poll_number}"
            )
        )

        print(
            "WEEKLY POLL: Opening discussion message pinned.",
            flush=True
        )

    except discord.Forbidden:
        print(
            "WEEKLY POLL: Missing permission to pin the opening message.",
            flush=True
        )
        raise

    except discord.HTTPException as error:
        print(
            f"WEEKLY POLL: Failed to pin opening message: {error}",
            flush=True
        )
        raise

    return poll_message, thread