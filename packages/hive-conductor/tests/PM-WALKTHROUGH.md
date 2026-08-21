# PM Walkthrough — Hive Conductor

> **Audience:** A project manager who has never touched this system.
> **Time:** 10 minutes from zero to running your first AI agent fleet.

---

## Step 0: Start the System

```bash
cd packages/hive-conductor
docker compose -f docker-compose.test.yml up --build -d
```

Wait ~30 seconds. Check it's alive:

```bash
curl http://localhost:8101/health
# Should return: {"status": "ok", ...}
```

Open your browser: **http://localhost:8101**

---

## Step 1: Setup Wizard (First Boot Only)

You'll see "Hive Conductor Setup — First boot detected."

1. **Name your hive** → type anything (e.g. "My PM Fleet")
2. Click **Next**
3. **Pick hardware** → click **Beast** (or whatever matches your machine)
4. Click **Next**
5. **Optional modules** → skip (just click Next)
6. Click **Launch the Hive**

The system creates two accounts:
- **admin** / password shown on screen
- **user** / password shown on screen

**Write these down.** You'll need the user account.

---

## Step 2: Login

1. You'll land on the Login page
2. Username: `user` (or whatever was shown)
3. Password: the one from setup
4. Click **Log In**

You're in. You'll see the Chat page with suggestion cards.

---

## Step 3: Look Around (Dashboard)

Click the **Dashboard** icon in the left sidebar (grid icon, usually first).

You'll see:
- Agent fleet status
- Recent DAG runs
- System health

This is your command center.

---

## Step 4: Create Your First DAG (Agent Workflow)

A "DAG" is a workflow — a chain of AI agents that do work for you.

1. Click **Fleet** in the sidebar
2. Click **+ New DAG** (or the create button)
3. Name it: `Daily Standup Summary`
4. Description: `Gather team updates and produce a summary email`
5. Click **Create**

You now have a DAG with two nodes:
- **Conductor** (the boss agent)
- **Worker** (does the actual work)

---

## Step 5: Activate & Run

1. On your new DAG, click **Activate** (changes status from draft → active)
2. Click **Run** (the play button)
3. Watch the execution — nodes light up as they process

The run completes in seconds (it's using stub data in dev mode).

---

## Step 6: Give Feedback

After a run completes:

1. Find the run in **Missions** (Activity) or the DAG detail page
2. Click the **👍** or **👎** button
3. Optionally add a comment: "Great summary!" or "Missed the blockers"

This feedback is **Signal #4** — it teaches the optimizer what you like.

---

## Step 7: Check the Optimizer

The optimizer reads your feedback + performance metrics and suggests improvements.

1. Click **Optimization Inbox** in the sidebar (or navigate to `/optimization`)
2. You'll see proposals like:
   - "Swap model from X to Y (faster, same quality)"
   - "Add a review node before output"
   - "Adjust prompt to include blockers"
3. Click **Accept** or **Reject** on each

Accepted proposals get applied to your DAG automatically.

---

## Step 8: View Audit Trail

Everything is logged. Click **Audit Log** in the sidebar:

- `dag_create` — you made the DAG
- `dag_activate` — you turned it on
- `dag_run` — it executed
- `dag_feedback` — you gave thumbs up/down
- `dag_edit` — any manual changes you made

This is your paper trail for compliance.

---

## Step 9: Topology Compare (A/B Testing)

After the optimizer makes changes, you can compare versions:

1. Go to **Topology** page
2. Select your DAG
3. See variant A (original) vs variant B (optimized)
4. Composite scores show which performs better

---

## Step 10: Rinse and Repeat

The system gets smarter every cycle:

```
You run a DAG
  → It produces output
  → You give feedback (👍/👎)
  → Optimizer proposes improvements
  → You accept/reject
  → Next run is better
  → Repeat
```

---

## Running the Automated Tests

To verify everything works without clicking around:

```bash
# API tests (no browser needed)
docker compose -f docker-compose.test.yml run --rm api-tests

# UI tests (headless browser)
docker compose -f docker-compose.test.yml run --rm e2e-tests

# AI Agent test — browser-use + Gemini 3.5 Flash
# (Requires GOOGLE_API_KEY env var)
make test-agent    # Runs the full PM workflow with an AI agent
make test-vision   # Pytest version with pass/fail assertions
```

The agent test is the ultimate "braindead PM" test — it gives an AI the same
instructions you'd give a new hire and lets it figure out the clicks. If the
AI can't complete the workflow, a real PM definitely can't.

---

## Shutting Down

```bash
docker compose -f docker-compose.test.yml down -v
```

---

## Quick Reference — Key Pages

| Page | What it does |
|------|-------------|
| **Chat** | Talk to your AI agents directly |
| **Dashboard** | Overview of fleet health + metrics |
| **Fleet** | Manage your DAGs (workflows) |
| **Missions** | See running/completed tasks |
| **Optimization Inbox** | Review AI-suggested improvements |
| **Audit Log** | Full history of everything |
| **Topology** | Compare DAG versions (A/B) |
| **Settings** | Configure models, presets, modules |
| **Credentials** | API keys for external services |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't connect to localhost:8101 | Run `docker compose -f docker-compose.test.yml ps` — is the container healthy? |
| Login fails | Did you complete setup first? Check the passwords from Step 1. |
| "Authentication required" on API calls | Your session expired. Login again. |
| Optimizer returns no proposals | You need at least one run + one feedback before it has data to work with. |
| DAG run shows "failed" | Normal in dev mode without a real LLM key. The workflow still exercises all the signals. |

---

## The Five Signals (What Makes It Learn)

| # | Signal | How you trigger it |
|---|--------|--------------------|
| 1 | Error codes | Automatic — system detects failures |
| 2 | Your edits | Edit a DAG manually → locks that field for 30 days |
| 3 | Eval judge | Automatic — internal LLM scores outputs |
| 4 | Your thumbs | Click 👍/👎 after a run |
| 5 | Performance | Automatic — latency, token count, cost |

All five feed into the optimizer. You only need to do #2 and #4 manually.
The rest happens automatically.

---

**That's it.** You're a PM running an AI agent fleet. 🐝
