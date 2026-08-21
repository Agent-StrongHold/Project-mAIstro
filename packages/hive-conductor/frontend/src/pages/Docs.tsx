import { useState } from "react";

const SECTIONS = [
  {
    id: "welcome",
    title: "What is Hive Conductor?",
    content: `Hive Conductor is your personal AI assistant platform. It connects AI "agents" to your smart home, web browser, and other services so you can control everything through natural language chat.

Think of it as a team of AI assistants (like a hive of bees) that work together. You talk to the Queen Bee (the Conductor), and she delegates tasks to specialized worker bees — one handles your smart home, another browses the web, another manages your schedule.

You don't need to know any of this to use it. Just open Chat and type what you want in plain English.`,
  },
  {
    id: "dashboard",
    title: "Dashboard",
    content: `The Dashboard is your home base. It shows you:

- **Agent status**: Which AI agents are active and ready to help
- **Active Missions**: Tasks currently being worked on
- **Approvals**: If an agent wants to do something sensitive (like unlock a door), it will show up here for you to approve or deny
- **System Health**: Whether everything is connected and running
- **Provider Quotas**: How much of each AI service you've used this month

The hexagonal grid shows all your agents as a honeycomb — each hex is one agent. Click one to see details.`,
  },
  {
    id: "chat",
    title: "Chat",
    content: `Chat is how you talk to the AI. Just type what you want in plain English:

- "Turn off the living room lights"
- "Browse amazon.com and find the cheapest USB-C cable"
- "What's the weather going to be like tomorrow?"
- "Create a new mission to monitor the crypto market"

The AI understands context — it remembers your conversation and can use tools to actually do things, not just talk. When it uses a tool (like controlling a light), you'll see a "tool call" card showing what it did.

**Sessions**: Each conversation is saved as a session. You can switch between sessions or start a new one.

**Model selector**: By default, the AI picks the best model for your request. If you want to use a specific AI model, click "Advanced" to choose one.`,
  },
  {
    id: "agents",
    title: "Agents (The Hive)",
    content: `Agents are the AI workers in your hive. Each agent has a specific role:

- **Queen** (Conductor): The boss. Routes your requests to the right worker.
- **Worker**: General-purpose agents that handle tasks like research, coding, or home automation.
- **Scout**: Research agents that find information.
- **Drone**: Monitoring agents that watch things and report back.
- **Guard**: Security agents that scan for threats and enforce safety rules.

Each agent has:
- A **model** — which AI brain it uses (GPT-4, Claude, Gemini, etc.)
- A **strategy** — how it approaches problems (see Strategies below)
- **Capabilities** — what kinds of tasks it can handle

You can create new agents, edit their behavior, or forge them using the step-by-step Builder.

**Intent Map**: Shows which agent handles which type of request. For example, "research" requests go to the Researcher agent.`,
  },
  {
    id: "missions",
    title: "Missions",
    content: `A Mission is a multi-step task that you assign to one or more agents. Unlike a simple chat request, a mission can run for minutes or hours.

For example:
- "Monitor the crypto market and alert me if Bitcoin drops below $40k"
- "Research competitors and create a summary report"
- "Audit all smart home devices for security issues"

Missions have statuses: Pending → Running → Completed (or Failed). You can pause, resume, and track progress with a progress bar.

Create a mission from the Missions page or by asking in Chat.`,
  },
  {
    id: "dags",
    title: "DAGs (Workflows)",
    content: `A DAG (Directed Acyclic Graph) is a workflow — a chain of steps that run in order. Think of it as a recipe:

1. Step A runs first (e.g., "Fetch weather data")
2. Step B runs next (e.g., "Analyze the data")
3. Step C runs last (e.g., "Send me a summary")

Each step is handled by a specific agent. DAGs are useful for automating repetitive multi-step tasks.

The DAG Builder lets you visually create these workflows by connecting nodes (steps) together with arrows.

**When to use DAGs vs Missions**: Use a Mission for a single goal. Use a DAG when you need a specific sequence of steps executed in order.`,
  },
  {
    id: "skills",
    title: "Skills",
    content: `Skills are reusable capabilities that agents can use. Think of them as plugins or tools:

- A "Home Automation" skill lets agents control your smart home
- A "Web Browser" skill lets agents browse websites
- A "Calculator" skill lets agents do math

Skills can be enabled or disabled. Disabled skills won't be used by any agent. Each skill shows its success rate, average response time, and how many times it's been used.

You generally don't need to manage skills manually — they come pre-configured. But if something isn't working, check here to make sure the relevant skill is enabled.`,
  },
  {
    id: "mcp",
    title: "MCP (Tool Connections)",
    content: `MCP (Model Context Protocol) is how Hive Conductor connects to external tools and services. Each MCP server provides a set of tools that agents can use.

For example:
- A "Home Assistant" MCP server provides tools like "turn on light" and "set thermostat"
- A "Browser" MCP server provides tools like "visit webpage" and "click button"
- A "Calendar" MCP server might provide tools like "create event"

Each server shows its connection status, the tools it provides, and when it was last checked. If a server shows "disconnected," its tools won't be available until the connection is restored.

You can add new MCP servers by providing their URL. This is how you extend what the AI can do.`,
  },
  {
    id: "schedules",
    title: "Schedules",
    content: `Schedules let you run tasks automatically on a timer. Think of them as alarms for your AI.

For example:
- "Every day at midnight" — run a security audit
- "Every hour" — check for new emails
- "Every Sunday" — generate a weekly summary report

Schedules use cron expressions (like \`0 * * * *\` for "every hour"), but you can use the preset buttons for common patterns.

Each schedule can be enabled or disabled independently. You can also trigger a schedule manually with "Run Now."`,
  },
  {
    id: "topology",
    title: "Topology",
    content: `The Topology page shows a visual map of how everything in your system is connected — agents, skills, MCP servers, and missions. It's like a network diagram.

This is mostly for understanding the big picture. If something isn't working, the topology can help you see if the right connections exist between agents and their tools.`,
  },
  {
    id: "messages",
    title: "Messages",
    content: `The Message Board is where agents post updates and alerts. Think of it as an inbox for your AI hive:

- **Security alerts**: When the guard agent detects something suspicious
- **Mission updates**: When a mission completes or fails
- **System notices**: When a service goes down or a quota is running low

Messages have priority levels (info, warning, critical). Critical messages are highlighted in red. You can filter by category or mark messages as read.`,
  },
  {
    id: "quotas",
    title: "Quotas",
    content: `Quotas show how much you're using each AI provider (OpenAI, Google, Mistral, etc.) this billing cycle.

Each provider has:
- **Used**: How many tokens (words) you've used
- **Remaining**: How many are left
- **Usage %**: How close you are to your limit

If a provider runs out, the system automatically falls back to another provider. The "Models" tab shows usage per model, and the "Billing" tab shows cost estimates.

You generally don't need to worry about this — the system manages it automatically. But if you're curious about costs or want to optimize, check here.`,
  },
  {
    id: "audit",
    title: "Audit Log",
    content: `The Audit Log records every important action taken in the system:

- Login attempts (successful and failed)
- Agent actions (tool calls, mission starts)
- Configuration changes
- Security events (threat scans, gate blocks)

This is primarily for security and debugging. If something unexpected happened, the audit log will tell you what, when, and who did it.

You can filter by action type, severity, and date range.`,
  },
  {
    id: "memory",
    title: "Memory",
    content: `Memory is how the AI remembers things across conversations. Without memory, every chat starts from scratch.

The memory store contains:
- **Learnings**: Things the AI has figured out over time (like "Blake prefers short answers")
- **Episodes**: Records of past interactions
- **Knowledge**: Facts you've told the AI to remember

Each memory entry has a namespace (category), tags, and optional TTL (time-to-live). Memories that aren't accessed eventually fade away, just like human memory.

You can manually add, edit, or delete memory entries. But usually the AI manages this automatically.`,
  },
  {
    id: "containers",
    title: "Containers",
    content: `Containers are the Docker services running your system. This page shows the technical infrastructure:

- **Running containers**: Services that are currently active
- **Stopped containers**: Services that are turned off
- **Resource usage**: CPU, memory, and network I/O for each container

You can start, stop, restart, and view logs for each container from here.

**Note**: This is a technical page. You generally don't need to interact with containers unless something is broken or you're debugging an issue.`,
  },
  {
    id: "evolution",
    title: "Evolution",
    content: `Evolution is an advanced feature that automatically improves your agents over time using genetic algorithms.

It works like biological evolution:
1. Create a "population" of agent configurations
2. Test them against benchmarks (fitness evaluation)
3. The best-performing ones "reproduce" to create new configurations
4. Repeat over many generations

Over time, the agents get better at their jobs without manual tuning.

**This is experimental.** You don't need to use it for the platform to work. It's for power users who want to optimize agent performance.`,
  },
  {
    id: "browser-tool",
    title: "Browser Tool",
    content: `The Browser Tool lets the AI actually browse websites — not just search, but navigate, click, read, and interact with web pages like a human would.

Use cases:
- "Go to amazon.com and find the cheapest USB-C cable"
- "Check my bank balance on chase.com"
- "Research this topic across multiple websites"

The browser uses a vision AI to "see" web pages, so it can handle sites that require visual interaction. It runs in a sandboxed container for security.

When the AI uses the browser, you'll see a \`browser_task\` tool call in the chat showing what it's doing.`,
  },
  {
    id: "home-automation",
    title: "Home Automation",
    content: `Hive Conductor connects to Home Assistant, which controls your smart home devices. You can control devices through Chat:

- "Turn off the living room lights"
- "Set the thermostat to 72 degrees"
- "Lock the front door"

**Approvals**: For sensitive actions (like unlocking doors or disarming security), the AI will ask for your approval before proceeding. You'll see an "Approval Required" banner on the Dashboard where you can approve or deny.

**Announcements**: The AI can make announcements through your home speakers.

**Supported devices**: Any device connected to Home Assistant — lights, thermostats, locks, fans, sensors, cameras, etc.`,
  },
  {
    id: "strategies",
    title: "Agent Strategies",
    content: `Each agent uses a strategy — a way of approaching problems:

- **ReAct** (Reason-Act-Observe): The agent thinks, takes an action, observes the result, then thinks again. Best for complex problems that need step-by-step reasoning.

- **Plan & Execute**: The agent creates a full plan first, then executes each step in order. Best for multi-step tasks where the order matters.

- **Direct**: Single-shot — the agent responds immediately without planning. Fastest option, best for simple questions.

- **Delegate**: The agent doesn't do the work itself — it routes the request to a more specialized agent. Best for the Conductor/Queen agent.

Most users don't need to worry about this. The system picks the right strategy automatically. But if you're creating a custom agent, you can choose which strategy it uses.`,
  },
];

export default function Docs() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["welcome"]));

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", paddingBottom: 60 }}>
      <div className="page-header">
        <div>
          <h1 style={{ fontFamily: "var(--hand)", fontSize: 28, fontWeight: 700 }}>Documentation</h1>
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--pencil)", marginTop: 4 }}>
            Everything you need to know about Hive Conductor
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {SECTIONS.map((s) => {
          const isOpen = expanded.has(s.id);
          return (
            <div key={s.id} id={s.id} style={{ borderBottom: "1px solid var(--rule)" }}>
              <button
                onClick={() => toggle(s.id)}
                style={{
                  width: "100%", background: "none", border: "none",
                  padding: "12px 4px", cursor: "pointer", textAlign: "left",
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                }}
              >
                <span style={{ fontFamily: "var(--hand)", fontSize: 18, fontWeight: 600, color: "var(--ink)" }}>
                  {s.title}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--pencil)" }}>
                  {isOpen ? "\u25BE" : "\u25B8"}
                </span>
              </button>
              {isOpen && (
                <div style={{
                  padding: "0 4px 14px",
                  fontFamily: "var(--mono)", fontSize: 11,
                  lineHeight: 1.7, color: "var(--ink)",
                  whiteSpace: "pre-wrap",
                }}>
                  {s.content}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
