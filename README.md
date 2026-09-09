This is a custom bot for the official Guild.AI Discord Server.

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

Architected agents cannot read, monitor, post, moderate, trigger from, or perform
any other action inside the official Guild.AI Discord server. Discord integrations
for other, clearly identified servers are allowed. If the target server is not
specified, the architect requires clarification before finalizing. It may also
design content that a person manually copies into the Guild server.
