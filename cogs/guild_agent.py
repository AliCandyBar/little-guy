import asyncio
import io
import re
import zipfile

import aiohttp
import discord
from crewai import Crew, Process
from discord import app_commands
from discord.ext import commands

from agents.architect_agent import (
    AgentArchitectureReview,
    HubAgentRecommendation,
    architect_agent,
    create_architecture_task,
)
from agents.guild_hub import GuildAgentHub
from cogs.agent_builder_utils import (
    contains_sensitive_data,
    normalize_agent_ts,
    sanitize_project_name,
    take_discord_chunk,
)
from cogs.agent_builder_recovery import (
    AgentBuilderRecovery,
    RecoveryUnavailable,
)


class GuildAgentArchitect(commands.Cog):
    INTAKE_TIMEOUT = 600
    MAX_MESSAGES = 12
    MAX_ACTIVE_USERS = 3
    GUILD_URL = "https://app.guild.ai"
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_users: set[int] = set()
        self.background_tasks: set[asyncio.Task] = set()
        self.architect_lock = asyncio.Lock()
        self.agent_hub = GuildAgentHub()
        self.recovery = AgentBuilderRecovery()

    @staticmethod
    def run_architect(
        transcript: list[str],
        newest_message: str,
        hub_candidates: list[dict[str, str]],
        hub_lookup_available: bool,
        selected_hub_agent: HubAgentRecommendation | None,
        generate_artifacts: bool = False,
        force_finalize: bool = False,
    ) -> AgentArchitectureReview:
        task = create_architecture_task(
            transcript=transcript,
            newest_message=newest_message,
            hub_candidates=hub_candidates,
            hub_lookup_available=hub_lookup_available,
            selected_hub_agent=selected_hub_agent,
            generate_artifacts=generate_artifacts,
            force_finalize=force_finalize,
        )
        result = Crew(
            agents=[architect_agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        ).kickoff()

        if result.pydantic is None:
            raise RuntimeError(
                "The Agent Architect returned an invalid response."
            )

        review = AgentArchitectureReview.model_validate(result.pydantic)
        allowed_matches = {
            (candidate["name"], candidate["url"]): candidate["description"]
            for candidate in hub_candidates
            if candidate["url"]
        }
        review.recommended_hub_agents = [
            match
            for match in review.recommended_hub_agents
            if (match.name, match.url) in allowed_matches
        ]
        for match in review.recommended_hub_agents:
            match.source_description = allowed_matches[(match.name, match.url)]
        review.project_name = sanitize_project_name(review.project_name)
        return review

    async def review_request(
        self,
        transcript: list[str],
        newest_message: str,
        selected_hub_agent: HubAgentRecommendation | None = None,
        generate_artifacts: bool = False,
        force_finalize: bool = False,
    ) -> AgentArchitectureReview:
        try:
            hub_candidates = await self.agent_hub.find_candidates(
                "\n".join(transcript)
            )
            hub_lookup_available = True
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            print(
                "AGENT HUB LOOKUP ERROR:",
                type(error).__name__,
                repr(error),
                flush=True,
            )
            hub_candidates = []
            hub_lookup_available = False

        async with self.architect_lock:
            return await asyncio.to_thread(
                self.run_architect,
                transcript,
                newest_message,
                hub_candidates,
                hub_lookup_available,
                selected_hub_agent,
                generate_artifacts,
                force_finalize,
            )

    @classmethod
    async def reject_sensitive_message(
        cls,
        user: discord.abc.Messageable,
    ):
        await cls.send_long_dm(
            user,
            "## Please remove confidential information\n\n"
            "I didn’t add that message to the design or send it to the "
            "Architect model because it appears to contain a password, token, "
            "API key, or private key.\n\n"
            "Describe what the credential is used for with a placeholder "
            "such as **YOUR_API_KEY**. You can connect the real credential "
            "privately inside Guild after building the agent.",
        )

    async def get_initial_request(
        self,
        user: discord.User | discord.Member,
    ) -> str | None:
        while True:
            message = await self.wait_for_dm(user.id)
            content = message.content.strip()

            if content.lower() == "cancel":
                await user.send("Agent design cancelled.")
                return None
            if not content:
                await user.send(
                    "Please describe the agent in text, or type **cancel**."
                )
                continue
            if contains_sensitive_data(content):
                await self.reject_sensitive_message(user)
                continue

            return content[:4000]

    async def wait_for_dm(self, user_id: int) -> discord.Message:
        def check(message: discord.Message) -> bool:
            return (
                message.author.id == user_id
                and isinstance(message.channel, discord.DMChannel)
                and not message.author.bot
            )

        return await self.bot.wait_for(
            "message",
            check=check,
            timeout=self.INTAKE_TIMEOUT,
        )

    @classmethod
    async def send_long_dm(
        cls,
        user: discord.abc.Messageable,
        text: str,
    ):
        remaining = text.strip() or "No content was generated."

        while remaining:
            chunk, remaining = take_discord_chunk(remaining, 1900)

            await user.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @classmethod
    async def send_code_dm(
        cls,
        user: discord.abc.Messageable,
        text: str,
        language: str = "text",
    ):
        # Keep every Discord message inside a complete code fence. Replace
        # nested fences so generated content cannot close one early.
        remaining = text.strip().replace("```", "'''")
        safe_language = re.sub(r"[^a-zA-Z0-9_-]", "", language) or "text"
        fence_overhead = len(safe_language) + 8

        while remaining:
            chunk, remaining = take_discord_chunk(
                remaining,
                2000 - fence_overhead,
            )

            await user.send(
                f"```{safe_language}\n{chunk}\n```",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @staticmethod
    def format_review(
        review: AgentArchitectureReview,
        step: int,
        selected_hub_agent: HubAgentRecommendation | None = None,
    ) -> str:
        missing = (
            "\n".join(f"- {item}" for item in review.missing_requirements)
            if review.missing_requirements
            else "None identified."
        )
        sections = [
            f"## Step {step} complete",
            "",
            f"**Updated:** {review.acknowledgement.strip()}",
            "",
            "### Current draft",
            review.revised_request.strip(),
            "",
            "### Agent Hub check",
            review.hub_assessment.strip(),
        ]

        if selected_hub_agent:
            sections.extend(
                [
                    "",
                    "**Selected base agent:** "
                    f"{selected_hub_agent.name}",
                    selected_hub_agent.url,
                ]
            )

        for index, match in enumerate(review.recommended_hub_agents, start=1):
            fit = (
                "Complete match"
                if match.fit == "complete"
                else "Partial match"
            )
            sections.extend(
                [
                    "",
                    f"**{index}. {match.name}** — {fit}",
                    match.reason.strip(),
                    match.url,
                ]
            )

        if review.recommended_hub_agents and not selected_hub_agent:
            sections.extend(
                [
                    "",
                    "To customize one of these, reply **use 1**, **use 2**, "
                    "or **use 3**.",
                ]
            )

        sections.extend(
            [
                "",
                "### Still needed",
                missing,
            ]
        )

        if review.next_question.strip():
            sections.extend(
                [
                    "",
                    "### Next question",
                    review.next_question.strip(),
                ]
            )

        sections.extend(
            [
                "",
                "Reply with another detail, type **done**, **save progress**, "
                "or **cancel**.",
            ]
        )
        return "\n".join(sections)

    @classmethod
    async def send_final_specification(
        cls,
        user: discord.abc.Messageable,
        review: AgentArchitectureReview,
        selected_hub_agent: HubAgentRecommendation | None = None,
    ):
        integrations = (
            "\n".join(
                f"- {item}" for item in review.suggested_integrations
            )
            if review.suggested_integrations
            else "- None required"
        )
        notes = (
            "\n".join(f"- {item}" for item in review.setup_notes)
            if review.setup_notes
            else "- No additional setup notes"
        )
        hub_matches = (
            "\n".join(
                f"- {match.name} ({match.fit} match): {match.reason}\n"
                f"  {match.url}"
                for match in review.recommended_hub_agents
            )
            if review.recommended_hub_agents
            else f"- {review.hub_assessment.strip()}"
        )
        selected_base = "No pre-made base agent selected."
        if selected_hub_agent:
            selected_base = (
                f"**{selected_hub_agent.name}**\n"
                f"{selected_hub_agent.url}\n"
                "The custom project below builds on this Agent Hub listing."
            )

        await cls.send_long_dm(
            user,
            "# Your custom Guild agent is ready\n\n"
            "## User specifications\n\n"
            f"**Agent name:** {review.agent_name.strip()}\n\n"
            f"**Description:** {review.description.strip()}\n\n"
            f"**Mode:** {review.mode}\n\n"
            f"**Architecture:** {review.architecture}\n"
            f"{review.architecture_reason.strip()}\n\n"
            f"### Suggested integrations\n{integrations}\n\n"
            f"### Setup notes\n{notes}\n\n"
            f"### Agent Hub check\n{hub_matches}\n\n"
            f"### Selected base agent\n{selected_base}",
        )

        if selected_hub_agent:
            hub_identifier = selected_hub_agent.url.rstrip("/").rsplit(
                "/", 1
            )[-1].replace("~", "/")
            initialization = (
                f"mkdir {review.project_name}\n"
                f"cd {review.project_name}\n"
                f"guild agent init --fork {hub_identifier}"
            )
        else:
            initialization = (
                f"mkdir {review.project_name}\n"
                f"cd {review.project_name}\n"
                "guild agent init "
                f"--name {review.project_name} "
                f"--template {review.architecture}"
            )

        await cls.send_long_dm(
            user,
            "## Set up the project\n\n"
            "Install the Guild CLI, authenticate in your own browser, and "
            "select the workspace where you want to develop the agent:",
        )
        await cls.send_code_dm(
            user,
            "npm install -g @guildai/cli\n"
            "guild auth login\n"
            "guild auth status\n"
            "guild workspace select",
            language="bash",
        )
        await cls.send_long_dm(
            user,
            "Create the project with these commands:",
        )
        await cls.send_code_dm(user, initialization, language="bash")
        await cls.send_long_dm(
            user,
            "## Replace **agent.ts**\n\n"
            "Open the generated **agent.ts** file and replace its contents "
            "with the following TypeScript:",
        )
        await cls.send_code_dm(user, review.agent_ts, language="typescript")
        await cls.send_long_dm(
            user,
            "## Test, validate, and publish\n\n"
            "Use these fictional cases so no private records are needed:\n\n"
            + "\n\n".join(
                f"**Test {index}:** {test_case}"
                for index, test_case in enumerate(
                    review.fictional_test_cases,
                    start=1,
                )
            )
            + "\n\nRun an ephemeral test first. When the behavior is "
            "correct, save, validate, and publish the agent:",
        )
        await cls.send_code_dm(
            user,
            'guild agent test --ephemeral\n'
            'guild agent save --message "Ready to publish" --wait\n'
            "guild agent publish",
            language="bash",
        )
        await cls.send_long_dm(
            user,
            "## Add it to your workspace\n\n"
            f"Open {cls.GUILD_URL}, choose the intended workspace, go to "
            "**Agents → Add agent**, and install the validated version.\n\n"
            "Little Guy has not authenticated with Guild, accessed your "
            "workspace, created the project, or received any credentials.",
        )
        await cls.send_project_bundle(user, review, initialization)

    @classmethod
    async def send_project_bundle(
        cls,
        user: discord.abc.Messageable,
        review: AgentArchitectureReview,
        initialization: str,
    ):
        tests = "\n\n".join(
            f"{index}. {test_case}"
            for index, test_case in enumerate(
                review.fictional_test_cases,
                start=1,
            )
        )
        guide = (
            f"# {review.agent_name}\n\n"
            f"{review.description}\n\n"
            "## Initialize\n\n"
            f"```bash\n{initialization}\n```\n\n"
            "## Test\n\n"
            f"{tests}\n\n"
            "```bash\n"
            "guild agent test --ephemeral\n"
            'guild agent save --message "Ready to publish" --wait\n'
            "guild agent publish\n"
            "```\n\n"
            "Connect real credentials only inside Guild. Never place them in "
            "agent.ts or this project bundle.\n"
        )
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("agent.ts", review.agent_ts)
            archive.writestr("README.md", guide)
        bundle.seek(0)

        await cls.send_long_dm(
            user,
            "## Download the project\n\n"
            "The same privacy-safe starter files are attached as a ZIP:",
        )
        await user.send(
            file=discord.File(
                bundle,
                filename=f"{review.project_name}.zip",
            )
        )

    @staticmethod
    def selected_hub_match(
        content: str,
        review: AgentArchitectureReview,
    ) -> HubAgentRecommendation | None:
        match = re.fullmatch(
            r"(?:use|select)\s+(\d+)",
            content.strip().lower(),
        )
        if not match:
            return None

        index = int(match.group(1)) - 1
        if index < 0 or index >= len(review.recommended_hub_agents):
            return None

        recommendation = review.recommended_hub_agents[index]
        return recommendation

    @staticmethod
    def violates_discord_policy(
        review: AgentArchitectureReview,
    ) -> bool:
        return review.restricted_guild_discord_capability

    @staticmethod
    def format_policy_rejection(
        review: AgentArchitectureReview,
    ) -> str:
        explanation = review.policy_message.strip() or (
            "The requested design could operate inside the Guild.AI Discord "
            "server."
        )
        return (
            "## Guild Discord restriction\n\n"
            f"**Not allowed:** {explanation}\n\n"
            "Agents cannot operate inside the official Guild.AI Discord "
            "server. Discord automation for a clearly identified different "
            "server is allowed. Content may also be prepared for a person to "
            "copy manually into the Guild server.\n\n"
            "Please clarify the target server or describe a workflow outside "
            "the Guild server."
        )

    async def review_and_reply(
        self,
        user: discord.abc.Messageable,
        transcript: list[str],
        newest_message: str,
        step: int,
        selected_hub_agent: HubAgentRecommendation | None,
    ) -> AgentArchitectureReview:
        review = await self.review_request(
            transcript,
            newest_message,
            selected_hub_agent=selected_hub_agent,
        )
        if self.violates_discord_policy(review):
            await self.send_long_dm(
                user,
                self.format_policy_rejection(review),
            )
        await self.send_long_dm(
            user,
            self.format_review(review, step, selected_hub_agent),
        )
        return review

    async def finalize_design(
        self,
        user: discord.abc.Messageable,
        transcript: list[str],
        current_review: AgentArchitectureReview,
        selected_hub_agent: HubAgentRecommendation | None,
        force: bool = False,
    ) -> bool:
        if self.violates_discord_policy(current_review):
            await self.send_long_dm(
                user,
                self.format_policy_rejection(current_review),
            )
            return False

        if not current_review.ready_to_finalize and not force:
            missing = "\n".join(
                f"- {item}" for item in current_review.missing_requirements
            )
            await self.send_long_dm(
                user,
                "## Almost ready\n\n"
                f"### Still needed\n{missing}\n\n"
                "Add those details, or type **finalize anyway** and I’ll use "
                "clearly stated assumptions.",
            )
            return False

        await user.send(
            "**Finalizing.** I’m generating the TypeScript and setup steps…"
        )
        final_review = None
        for attempt in range(2):
            final_review = await self.review_request(
                transcript,
                (
                    "Generate the confirmed final custom agent project using "
                    f"name '{current_review.agent_name}', architecture "
                    f"{current_review.architecture}, and mode "
                    f"{current_review.mode}."
                    if attempt == 0
                    else "Regenerate valid, credential-free final artifacts "
                    f"using architecture {current_review.architecture} and "
                    f"mode {current_review.mode}."
                ),
                selected_hub_agent=selected_hub_agent,
                generate_artifacts=True,
                force_finalize=force,
            )
            try:
                self.validate_final_artifacts(final_review)
                if (
                    final_review.architecture != current_review.architecture
                    or final_review.mode != current_review.mode
                ):
                    raise RuntimeError(
                        "Generated artifacts changed the confirmed design."
                    )
                break
            except (RuntimeError, ValueError):
                if attempt == 1:
                    raise

        assert final_review is not None
        if self.violates_discord_policy(final_review):
            await self.send_long_dm(
                user,
                self.format_policy_rejection(final_review),
            )
            return False
        await self.send_final_specification(
            user,
            final_review,
            selected_hub_agent,
        )
        return True

    @staticmethod
    def validate_final_artifacts(review: AgentArchitectureReview):
        if not review.agent_ts.strip():
            raise RuntimeError("The Architect did not generate agent.ts.")
        if len(review.fictional_test_cases) != 3:
            raise RuntimeError("The Architect did not generate three tests.")

        review.agent_ts = normalize_agent_ts(review.agent_ts)
        generated = "\n".join(
            [review.agent_ts, *review.fictional_test_cases]
        )
        if contains_sensitive_data(generated):
            raise RuntimeError("Generated output contains a possible secret.")

    async def request_confirmation(
        self,
        user: discord.abc.Messageable,
        review: AgentArchitectureReview,
        selected_hub_agent: HubAgentRecommendation | None,
    ) -> tuple[HubAgentRecommendation | None, bool]:
        if self.violates_discord_policy(review):
            await self.send_long_dm(
                user,
                self.format_policy_rejection(review),
            )
            return selected_hub_agent, False

        if selected_hub_agent:
            try:
                still_available = await self.agent_hub.verify_listing(
                    selected_hub_agent.name,
                    selected_hub_agent.url,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                await user.send(
                    "I couldn’t recheck the selected Hub agent right now. "
                    "Please type **done** to try again."
                )
                return selected_hub_agent, False
            if not still_available:
                await user.send(
                    "The selected Hub agent is no longer public and published. "
                    "I removed it as the base; review or update your design "
                    "before continuing."
                )
                return None, False

        base = (
            f"**Base agent:** {selected_hub_agent.name}\n"
            if selected_hub_agent
            else "**Base agent:** New custom agent\n"
        )
        await self.send_long_dm(
            user,
            "## Confirm your design\n\n"
            f"**Name:** {review.agent_name}\n"
            f"**Description:** {review.description}\n"
            f"**Architecture:** {review.architecture}\n"
            f"**Mode:** {review.mode}\n"
            f"{base}\n"
            "Type **confirm** to generate the project, **edit** to make "
            "changes, **save progress** for a recovery code, or **cancel**.",
        )
        return selected_hub_agent, True

    async def save_recovery(
        self,
        user: discord.User | discord.Member,
        transcript: list[str],
        review: AgentArchitectureReview,
        selected_hub_agent: HubAgentRecommendation | None,
        step: int,
        awaiting_confirmation: bool,
        force_finalize: bool,
    ):
        state = {
            "transcript": transcript,
            "review": review.model_dump(mode="json"),
            "selected_hub_agent": (
                selected_hub_agent.model_dump(mode="json")
                if selected_hub_agent
                else None
            ),
            "step": step,
            "awaiting_confirmation": awaiting_confirmation,
            "force_finalize": force_finalize,
        }
        try:
            code = await asyncio.to_thread(
                self.recovery.save,
                user.id,
                state,
            )
        except RecoveryUnavailable:
            await user.send(
                "Encrypted recovery is not configured on this deployment. "
                "An administrator must set **AGENT_BUILDER_RECOVERY_KEY**."
            )
            return

        await user.send(
            "## Progress saved\n\n"
            f"Your one-time recovery code is **{code}**. It expires in 24 "
            "hours and only works with your Discord account.\n\n"
            "To resume, run **/agent-builder** and DM me "
            f"**resume {code}**. Keep the code private."
        )

    async def run_intake(
        self,
        user: discord.User | discord.Member,
    ):
        try:
            initial_request = await self.get_initial_request(user)
            if initial_request is None:
                return

            resume_match = re.fullmatch(
                r"resume\s+(AB-[A-F0-9]{12})",
                initial_request,
                re.IGNORECASE,
            )
            if resume_match:
                try:
                    state = await asyncio.to_thread(
                        self.recovery.load,
                        user.id,
                        resume_match.group(1),
                    )
                except RecoveryUnavailable:
                    await user.send(
                        "Encrypted recovery is not configured on this "
                        "deployment."
                    )
                    return
                if not state:
                    await user.send(
                        "That recovery code is invalid, expired, already used, "
                        "or belongs to another Discord account."
                    )
                    return
                transcript = list(state["transcript"])
                review = AgentArchitectureReview.model_validate(state["review"])
                selected_data = state.get("selected_hub_agent")
                selected_hub_agent = (
                    HubAgentRecommendation.model_validate(selected_data)
                    if selected_data
                    else None
                )
                step = max(2, int(state.get("step", 2)))
                awaiting_confirmation = bool(
                    state.get("awaiting_confirmation", False)
                )
                force_after_confirmation = bool(
                    state.get("force_finalize", False)
                )
                await self.send_long_dm(
                    user,
                    "## Design restored\n\n"
                    + self.format_review(
                        review,
                        step=max(1, step - 1),
                        selected_hub_agent=selected_hub_agent,
                    ),
                )
                if awaiting_confirmation:
                    selected_hub_agent, awaiting_confirmation = (
                        await self.request_confirmation(
                            user,
                            review,
                            selected_hub_agent,
                        )
                    )
            else:
                transcript = [initial_request]
                selected_hub_agent = None
                step = 2
                awaiting_confirmation = False
                force_after_confirmation = False
                await user.send(
                    "**Got it.** Reviewing your initial request…"
                )
                review = await self.review_and_reply(
                    user,
                    transcript,
                    initial_request,
                    step=1,
                    selected_hub_agent=selected_hub_agent,
                )

            while True:
                if step > self.MAX_MESSAGES and not awaiting_confirmation:
                    await user.send(
                        "You’ve reached the 12-message design limit. I’ll use "
                        "clearly stated assumptions for anything still missing."
                    )
                    review = await self.review_request(
                        transcript,
                        "Prepare confirmation with reasonable assumptions.",
                        selected_hub_agent=selected_hub_agent,
                        force_finalize=True,
                    )
                    selected_hub_agent, awaiting_confirmation = (
                        await self.request_confirmation(
                            user,
                            review,
                            selected_hub_agent,
                        )
                    )
                    force_after_confirmation = True

                message = await self.wait_for_dm(user.id)
                content = message.content.strip()
                command = content.lower()

                if command == "cancel":
                    await user.send("Agent design cancelled.")
                    return

                if command == "save progress":
                    await self.save_recovery(
                        user,
                        transcript,
                        review,
                        selected_hub_agent,
                        step,
                        awaiting_confirmation,
                        force_after_confirmation,
                    )
                    continue

                if awaiting_confirmation:
                    if command == "confirm":
                        if await self.finalize_design(
                            user,
                            transcript,
                            review,
                            selected_hub_agent,
                            force=force_after_confirmation,
                        ):
                            return
                        awaiting_confirmation = False
                        continue
                    if command == "edit":
                        awaiting_confirmation = False
                        force_after_confirmation = False
                        if step > self.MAX_MESSAGES:
                            step = self.MAX_MESSAGES
                        await user.send(
                            "**Editing resumed.** Send the detail you want to "
                            "add or change."
                        )
                        continue
                    await user.send(
                        "Please type **confirm**, **edit**, **save progress**, "
                        "or **cancel**."
                    )
                    continue

                if command in {"done", "finalize"}:
                    if not review.ready_to_finalize:
                        await self.finalize_design(
                            user,
                            transcript,
                            review,
                            selected_hub_agent,
                        )
                        continue
                    selected_hub_agent, awaiting_confirmation = (
                        await self.request_confirmation(
                            user,
                            review,
                            selected_hub_agent,
                        )
                    )
                    force_after_confirmation = False
                    continue

                if command == "finalize anyway":
                    assumed_review = await self.review_request(
                        transcript,
                        "Finalize the design with clearly stated assumptions.",
                        selected_hub_agent=selected_hub_agent,
                        force_finalize=True,
                    )
                    selected_hub_agent, awaiting_confirmation = (
                        await self.request_confirmation(
                            user,
                            assumed_review,
                            selected_hub_agent,
                        )
                    )
                    if awaiting_confirmation:
                        review = assumed_review
                        force_after_confirmation = True
                    continue

                selected_match = self.selected_hub_match(content, review)
                if selected_match:
                    selected_hub_agent = selected_match
                    content = (
                        "Use the Agent Hub listing "
                        f"'{selected_match.name}' as the base for my "
                        "custom agent. Help me decide what to change or add."
                    )
                    await user.send(
                        f"**Selected:** {selected_match.name}\n\n"
                        "I’ll use it as the starting point and help you build "
                        "a custom version."
                    )
                elif re.fullmatch(
                    r"(?:use|select)\s+\d+",
                    command,
                ):
                    await user.send(
                        "That Agent Hub option isn’t available. Choose one "
                        "of the numbered matches shown above."
                    )
                    continue

                if not content:
                    await user.send(
                        "I received an empty message, so the description has "
                        "not changed. Please send a detail or answer the "
                        "current question."
                    )
                    continue
                if contains_sensitive_data(content):
                    await self.reject_sensitive_message(user)
                    continue

                content = content[:4000]
                transcript.append(content)
                await user.send(
                    f"**Got it.** Updating the agent draft with message "
                    f"{step}…"
                )
                review = await self.review_and_reply(
                    user,
                    transcript,
                    content,
                    step=step,
                    selected_hub_agent=selected_hub_agent,
                )
                step += 1

        except asyncio.TimeoutError:
            await user.send(
                "The Agent Architect closed after 10 minutes of inactivity. "
                "Run /agent-builder again whenever you’re ready to continue."
            )
        except discord.Forbidden:
            pass
        except Exception:
            print(
                "AGENT ARCHITECT ERROR:",
                type(error).__name__,
                flush=True,
            )
            try:
                await user.send(
                    "The Agent Architect encountered an error. Please ask a "
                    "staff member to check Little Guy’s logs."
                )
            except discord.HTTPException:
                pass
        finally:
            self.active_users.discard(user.id)

    @app_commands.command(
        name="agent-builder",
        description="Design a custom Guild agent in a private DM."
    )
    @app_commands.guild_only()
    async def agent_builder(
        self,
        interaction: discord.Interaction,
    ):
        if interaction.user.id in self.active_users:
            await interaction.response.send_message(
                "You already have an Agent Architect conversation in DMs.",
                ephemeral=True,
            )
            return

        if len(self.active_users) >= self.MAX_ACTIVE_USERS:
            await interaction.response.send_message(
                "The Agent Architect is currently at capacity. Please try "
                "again shortly.",
                ephemeral=True,
            )
            return

        try:
            await interaction.user.send(
                "# Agent Architect\n\n"
                "I’ll refine your idea, identify missing requirements, and "
                "prepare a copy-ready Guild agent specification.\n\n"
                "**First, describe the agent you want to create.**\n\n"
                "Use placeholders instead of passwords, API keys, tokens, "
                "private records, or other confidential information. You’ll "
                "connect real credentials privately inside Guild later. Your "
                "DM description is sent to the Architect AI only to create "
                "this design and is kept by Little Guy only for this active "
                "conversation unless you explicitly choose **save progress**."
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can’t initialize the Agent Builder because I can’t send "
                "you a DM. Enable direct messages from members of this "
                "server, then run `/agent-builder` again.",
                ephemeral=True,
            )
            return

        self.active_users.add(interaction.user.id)
        await interaction.response.send_message(
            "I sent you a DM to begin designing your Guild agent.",
            ephemeral=True,
        )

        background_task = asyncio.create_task(
            self.run_intake(interaction.user)
        )
        self.background_tasks.add(background_task)
        background_task.add_done_callback(self.background_tasks.discard)

    async def cog_unload(self):
        for task in self.background_tasks:
            task.cancel()


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildAgentArchitect(bot))
