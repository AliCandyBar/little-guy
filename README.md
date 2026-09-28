This is a custom bot for the official Guild.AI Discord Server.

## Voice music

Little Guy can join a member's voice channel with `/join` and play Spotify
tracks or YouTube videos and playlists with `/play`. `/queue`, `/stop`, `/previous`, `/restart`,
`/pause`, `/resume`, `/skip`, `/shuffle`, and `/leave` provide queue and
playback controls. The now-playing message includes artwork, a live progress
bar, the upcoming queue, and matching emoji buttons.

Spotify supplies metadata; playable audio is resolved from YouTube because
Spotify does not provide full audio streams to Discord bots. The host must have
`ffmpeg` installed. Discord's voice extras (including PyNaCl and `davey`) are
installed through `discord.py[voice]`. These environment variables must be configured:

```text
BOT_COMMANDS_CHANNEL_ID=123456789012345678
MUSIC_DEVELOPMENT_GUILD_ID=234567890123456789
SPOTIFY_CLIENT_ID=your_spotify_app_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_app_client_secret
SPOTIFY_REFRESH_TOKEN=authorized_spotify_user_refresh_token
MUSIC_VOLUME=0.5
MUSIC_MAX_PLAYLIST_TRACKS=100
```

`BOT_COMMANDS_CHANNEL_ID` restricts `/join` to that channel. Set
`MUSIC_DEVELOPMENT_GUILD_ID` to the Discord server ID for a development server;
inside that server only, `/join` may be used from any text channel. All other
music safety checks still apply. `MUSIC_VOLUME` is
optional and accepts values from 0.0 to 1.0. `MUSIC_MAX_PLAYLIST_TRACKS` is an
optional safety limit for each imported YouTube playlist and defaults to 100.
Public and unlisted YouTube playlists work without a YouTube API key; private
playlists are not supported. In the Discord developer portal,
the bot needs Connect and Speak permissions. It stays connected when the queue
ends, leaves after 15 idle minutes, or leaves after the voice channel has had no
human members for five minutes.

Spotify requires user OAuth for playlist contents. `SPOTIFY_REFRESH_TOKEN` must
be issued to the Spotify account that owns or collaborates on playlists the bot
will play, with `playlist-read-private` and `playlist-read-collaborative` scopes.
It is optional for individual track links, but required for playlist links.
Add `http://127.0.0.1:8888/callback` as a redirect URI in the Spotify developer
app, then run `python scripts/spotify_refresh_token.py` once to generate it.

## Guild Agent Architect

The `/agent-builder` command opens a private DM intake that helps a user design
a custom Guild agent. The architect acknowledges each added detail, rewrites the
request,
identifies material missing requirements, and produces a copy-ready agent name,
description, mode, system prompt, integration suggestions, and setup notes.

For each evolving request, Little Guy checks Guild's public Agent Hub for
published agents that may already solve the task. It shows up to three genuine
matches with their Agent Hub links and labels each as a complete or partial fit.
The public catalog lookup does not require or collect the user's Guild
credentials. If no listing fits, the architect continues designing the custom
agent normally.

Users can reply `use 1`, `use 2`, or `use 3` to select a recommended Hub agent
as their starting point. The architect then keeps that base agent in context,
asks what should change, and produces a custom specification the user can apply
after forking or installing the selected agent in Guild.

The completed DM uses normal Discord Markdown for explanations, headings, links,
and requirement summaries. Only terminal commands and the generated TypeScript
for `agent.ts` are placed in code blocks. Long prose and code are split into
separate messages without exceeding Discord's UTF-16 message limit.

The builder warns users not to provide secrets or private records and asks for
placeholders instead. Common API keys, access tokens, passwords, Discord bot
tokens, and private keys are rejected locally before the message is added to the
design transcript or sent to the Architect model. The in-memory transcript is
discarded when the conversation finishes, times out, or the bot restarts unless
the user explicitly creates an encrypted recovery record.

Clarification turns generate only the concise design review. The complete
TypeScript project is generated once, when the user finalizes the design.

Before code generation, the builder shows a final summary and requires the user
to type `confirm`. Typing `edit` returns to clarification. The architect
chooses and explains the appropriate Guild template (`LLM`,
`AUTO_MANAGED_STATE`, or `BLANK`) and generates three fictional test cases
that do not require real company or customer data.

The selected Agent Hub base is fetched again before confirmation. A listing that
is no longer public and published is removed instead of producing stale fork
instructions. At completion, Little Guy also attaches an in-memory ZIP containing
`agent.ts` and a setup README; the bundle is never written to the bot's disk.

## Optional encrypted recovery

During an active DM, `save progress` creates a one-time, account-bound recovery
code that expires after 24 hours. Resume by running `/agent-builder` and sending
`resume AB-...` in the new DM. Recovery records are encrypted on disk and
contain only credential-screened builder state. The builder never requires
confidential business data, but users should still describe workflows with
fictional examples and placeholders.

Configure a bot-owned Fernet key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `AGENT_BUILDER_RECOVERY_KEY` to that value. In container deployments, set
`AGENT_BUILDER_RECOVERY_DIR` to a mounted persistent directory so records
survive restarts. Neither setting comes from the Discord user or their Guild
account. Without the key, the builder works normally but `save progress`
reports that recovery is unavailable.

Little Guy does not request Guild credentials or create the agent. The finished
specification links the user to `https://app.guild.ai`, where they create and own
the agent in their chosen workspace.

The architect uses the same `OPENAI_API_KEY` configuration as the weekly poll
agents.

## Community chat agent

Little Guy welcomes new members, answers replies and mentions with up to 50
preceding channel messages as context, and posts one randomized daily discussion
prompt. Configure these Discord IDs:

For user messages containing `?`, Little Guy uses Discord's reply feature and
lets Discord notify the author without adding a manual mention. For statements
and question-like messages without `?`, it sends a normal channel message with
all generated mentions, role mentions, `@everyone`, and its own mention blocked.
After a member mentions Little Guy or replies directly to it, Little Guy keeps a
per-member conversation window open in that channel for up to five idle minutes
and twenty follow-up messages. It answers follow-ups related to its recent response
without requiring another mention, ignores unrelated conversation, and then
requires a new mention or direct reply. Requests to stop and direct hostile or
insulting remarks close the window immediately without a response.
Closing a window does not erase channel context. When a member later mentions
Little Guy or directly replies again, the new response receives the preceding
50 available channel messages, including messages sent while the window was
closed, so it can understand references to the intervening conversation.

```text
WELCOME_CHANNEL_ID=123456789012345678
DISCUSSION_CHANNEL_ID=123456789012345678
VERIFIED_ROLE_ID=123456789012345678
GREETER_BOT_ID=123456789012345678
```

In the welcome channel, Little Guy waits for the configured greeter bot to send
`Hey @user! We are so glad you joined **Guild.AI**!`. It then welcomes that
mentioned member and asks one varied question about their projects, agents,
Guild.AI assistance, programming, or agentic-AI usage. Each member is recorded
after the greeter trigger so duplicate greeter messages do not produce duplicate
Little Guy welcomes. `GREETER_BOT_ID` is optional but recommended; when set,
only that bot can trigger welcomes.

Daily prompts are scheduled at varying times from 4:00 AM through 10:59 PM in
`America/New_York`, ping only the configured Verified role, contain a community
question, and are limited to five sentences. The schedule survives restarts in
`data/community_chat.db`; set `COMMUNITY_CHAT_DB` to override that location.
Staff members or members with Manage Messages can use `/discussion-prompt` to
post that day's prompt immediately. Manual and scheduled sends share a durable
per-server, per-Eastern-date record, so only one prompt is posted each day.

The community agent uses the existing `OPENAI_API_KEY`; a separate API key is
not required. It has no CrewAI tools, delegation, or code-execution capability.
Requests to execute code or commands are also rejected locally before any model
call. It can still explain or review code without running it.

Chat answers can use OpenAI's hosted web search with the existing
`OPENAI_API_KEY`. Explicit requests to search, verify, find sources, or answer
current/recent questions require a live lookup; for other questions, the model
may search when specific or unfamiliar context would improve the answer. Search
answers are instructed to show clickable source links. Set
`COMMUNITY_WEB_SEARCH_MODEL` to override the default `gpt-4.1-mini` search model.
If web search is temporarily unavailable, Little Guy falls back to its existing
non-web chat agent rather than failing silently. Web search is its only enabled
hosted tool and does not grant code execution, shell, or computer access.
Before any lookup, a local topic gate rejects NSFW or sexually explicit
requests, politics and elections, partisan subjects, geopolitics and
international conflict, and broad state-of-the-world requests. These requests
never reach the web-search tool. The search agent repeats the same restriction
as a defense-in-depth safeguard.

When deployed with `compose.yaml`, the repository's `data` directory is mounted
at `/app/data`. This preserves welcome and daily-discussion records when the bot
container is rebuilt or restarted.

Little Guy uses a restrained, friendly knightly voice. It can explain its own
community role and regular-user commands, advise on Guild.AI and general agent
setup, and provide programming explanations, examples, and reviews.

Architected agents cannot read, monitor, post, moderate, trigger from, or perform
any other action inside the official Guild.AI Discord server. Discord integrations
for other, clearly identified servers are allowed. If the target server is not
specified, the architect requires clarification before finalizing. It may also
design content that a person manually copies into the Guild server.
