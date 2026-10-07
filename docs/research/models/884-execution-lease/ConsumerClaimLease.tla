----------------------------- MODULE ConsumerClaimLease -----------------------------
(***************************************************************************)
(* Consumer-claim execution spine (#884, RESEARCH M8-A4).                  *)
(*                                                                         *)
(* A faithful TLA+ rendering of the bounded protocol that                  *)
(* `scripts/model_check_consumer_claim.py` explores exhaustively: one Run,  *)
(* one node, competing consumers, a cancel authority, a recovery sweep and  *)
(* a bounded clock. The two named multi-await windows of the shipped spine  *)
(* are modeled as explicit steps:                                          *)
(*                                                                         *)
(*   - `_settle_provider_success` reads the Run, then writes the Attempt    *)
(*     (#1335): BeginCommit is the read, LandCommit the write.              *)
(*   - the `accept_outcome` projection (ADR-082426-e3ff): Accept carries    *)
(*     the live fencing token when FencedAcceptance is TRUE.                *)
(*                                                                         *)
(* Constants:                                                               *)
(*   Consumers          set of consumer identities, e.g. {"a", "b"}         *)
(*   TTL                lease length in ticks, e.g. 2                       *)
(*   Horizon            clock bound, e.g. 6                                 *)
(*   MaxAttempts        attempt ordinal bound, e.g. 2                       *)
(*   Once               TRUE = `once` replay semantics (ReplayRefused)      *)
(*   FencedAcceptance   TRUE = ADR-082426-e3ff fence on acceptance          *)
(*   TerminalRunRefusal TRUE = #1335 terminal-Run refusal on landing        *)
(*                                                                         *)
(* The guarded configuration is:                                            *)
(*   FencedAcceptance = TRUE /\ TerminalRunRefusal = TRUE                   *)
(*                                                                         *)
(* TLC:     java -cp tla2tools.jar tlc2.TLC ConsumerClaimLease.cfg          *)
(* Apalache: apalache-mc check --config ConsumerClaimLease.cfg              *)
(*                                                                         *)
(* S4 (no completion lands under a terminal Run) is a transition property;  *)
(* TLC checks state invariants, so the landing action records a "S4" flag   *)
(* into `violations` when it would land COMPLETED under a cancelled Run,    *)
(* and InvNoViolations refuses any flag. This mirrors the Python checker's  *)
(* edge checks exactly.                                                     *)
(*                                                                         *)
(* The executed, CI-reproducible equivalent lives in                       *)
(* scripts/model_check_consumer_claim.py; this module is the portable      *)
(* artifact of the same transition relation.                               *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
  Consumers,
  TTL,
  Horizon,
  MaxAttempts,
  Once,
  FencedAcceptance,
  TerminalRunRefusal

VARIABLES
  \* @type: Str;
  run,
  \* @type: Seq([ordinal: Int, status: Str, holder: Str, token: Int, expires: Int, cause: Str, dispatched: Bool]);
  attempts,
  \* @type: Set(Str);
  aliveSet,
  \* @type: Int;
  clock,
  \* @type: Int;
  fence,
  \* @type: Set(Int);
  dispatched,
  \* @type: [ordinal: Int, holder: Str, token: Int, observed: Str];
  pending,
  \* @type: Set(Str);
  violations

vars == <<run, attempts, aliveSet, clock, fence, dispatched, pending, violations>>

NoAttempt == [ordinal |-> 0, status |-> "none", holder |-> "none",
              token |-> 0, expires |-> 0, cause |-> "none", dispatched |-> FALSE]

Attempt(ordinal, holder, token, expires) ==
  [ordinal |-> ordinal, status |-> "running", holder |-> holder,
   token |-> token, expires |-> expires, cause |-> "none",
   dispatched |-> FALSE]

HasOpen == \E a \in Range(attempts) : a.status = "running"

OpenAttempt ==
  IF HasOpen
  THEN [a \in Range(attempts) |-> a][Len(attempts)]
  ELSE NoAttempt

Running(a) == a.status = "running"
LeaseExpired(a) == Running(a) /\ a.expires <= clock

ReplaceAttempt(updated) ==
  [i \in 1..Len(attempts) |->
     IF attempts[i].ordinal = updated.ordinal THEN updated ELSE attempts[i]]

CapExpiry == Min({clock + TTL, Horizon})

TerminalRun == run \in {"completed", "cancelled"}

Init ==
  /\ run = "queued"
  /\ attempts = <<>>
  /\ aliveSet = Consumers
  /\ clock = 0
  /\ fence = 0
  /\ dispatched = {}
  /\ pending = "none"
  /\ violations = {}

Claim(c) ==
  /\ run = "queued"
  /\ attempts = <<>>
  /\ run' = "running"
  /\ attempts' = <<Attempt(1, c, 1, CapExpiry)>>
  /\ fence' = 1
  /\ UNCHANGED <<aliveSet, clock, dispatched, pending, violations>>

Renew(c) ==
  /\ HasOpen
  /\ OpenAttempt.holder = c
  /\ OpenAttempt.expires > clock
  /\ attempts' = ReplaceAttempt([OpenAttempt EXCEPT !.expires = CapExpiry])
  /\ UNCHANGED <<run, aliveSet, clock, fence, dispatched, pending, violations>>

Tick ==
  /\ clock < Horizon
  /\ clock' = clock + 1
  /\ UNCHANGED <<run, attempts, aliveSet, fence, dispatched, pending, violations>>

Crash(c) ==
  /\ c \in aliveSet
  /\ aliveSet' = aliveSet \ {c}
  /\ UNCHANGED <<run, attempts, clock, fence, dispatched, pending, violations>>

Dispatch(c) ==
  /\ HasOpen
  /\ OpenAttempt.holder = c
  /\ OpenAttempt.token = fence
  /\ OpenAttempt.expires > clock
  /\ ~OpenAttempt.dispatched
  /\ (~Once \/ dispatched = {})
  /\ attempts' = ReplaceAttempt([OpenAttempt EXCEPT !.dispatched = TRUE])
  /\ dispatched' = dispatched \cup {OpenAttempt.ordinal}
  /\ UNCHANGED <<run, aliveSet, clock, fence, pending, violations>>

BeginCommit(c) ==
  /\ HasOpen
  /\ OpenAttempt.holder = c
  /\ OpenAttempt.dispatched
  /\ pending = "none"
  /\ pending' = [ordinal |-> OpenAttempt.ordinal, holder |-> c,
                 token |-> OpenAttempt.token, observed |-> run]
  /\ UNCHANGED <<run, attempts, aliveSet, clock, fence, dispatched, violations>>

LandCommit(c) ==
  /\ pending # "none"
  /\ pending.holder = c
  /\ \E a \in Range(attempts) :
       /\ a.ordinal = pending.ordinal
       /\ Running(a)
       /\ IF TerminalRunRefusal /\ run = "cancelled"
          THEN  \* #1335: the stale success converts, never lands COMPLETED.
                attempts' = ReplaceAttempt(
                  [a EXCEPT !.status = "cancelled", !.cause = "requested"])
                /\ violations' = violations
          ELSE  \* run not terminal, or the pre-#1335 landing:
                attempts' = ReplaceAttempt([a EXCEPT !.status = "completed"])
                /\ violations' = IF run = "cancelled"
                                 THEN violations \cup {"S4"}
                                 ELSE violations
  /\ run' = IF TerminalRun THEN run ELSE "running"
  /\ pending' = "none"
  /\ UNCHANGED <<aliveSet, clock, fence, dispatched>>

Accept(c) ==
  /\ ~TerminalRun
  /\ \E a \in Range(attempts) :
       /\ a.holder = c
       /\ a.status = "completed"
       /\ (~FencedAcceptance
           \/ (a.ordinal = attempts[Len(attempts)].ordinal /\ a.token = fence))
  /\ run' = "completed"
  /\ UNCHANGED <<attempts, aliveSet, clock, fence, dispatched, pending, violations>>

Cancel ==
  /\ run \in {"queued", "running"}
  /\ run' = "cancelled"
  /\ attempts' = [i \in 1..Len(attempts) |->
       IF Running(attempts[i])
          /\ (pending = "none" \/ pending.ordinal # attempts[i].ordinal)
       THEN [attempts[i] EXCEPT !.status = "cancelled", !.cause = "requested"]
       ELSE attempts[i]]
  /\ UNCHANGED <<aliveSet, clock, fence, dispatched, pending, violations>>

Recover ==
  /\ \E a \in Range(attempts) : LeaseExpired(a)
  /\ attempts' = [i \in 1..Len(attempts) |->
       IF LeaseExpired(attempts[i])
       THEN [attempts[i] EXCEPT !.status = "cancelled", !.cause = "recovered"]
       ELSE attempts[i]]
  /\ UNCHANGED <<run, aliveSet, clock, fence, dispatched, pending, violations>>

Retry(c) ==
  /\ run = "running"
  /\ attempts # <<>>
  /\ Len(attempts) < MaxAttempts
  /\ ~HasOpen
  /\ \/ attempts[Len(attempts)].cause = "recovered"
     \/ (attempts[Len(attempts)].status = "completed" /\ ~FencedAcceptance)
  /\ attempts' = Append(attempts,
       Attempt(Len(attempts) + 1, c, fence + 1, CapExpiry))
  /\ fence' = fence + 1
  /\ UNCHANGED <<run, aliveSet, clock, dispatched, pending, violations>>

Next ==
  \/ Tick
  \/ Cancel
  \/ Recover
  \/ \E c \in Consumers :
       \/ Claim(c)
       \/ Renew(c)
       \/ Crash(c)
       \/ Dispatch(c)
       \/ BeginCommit(c)
       \/ LandCommit(c)
       \/ Accept(c)
       \/ Retry(c)

-----------------------------------------------------------------------------
(***************************************************************************)
(* Safety invariants — the issue's candidate list, as state predicates.    *)
(***************************************************************************)

TypeOK ==
  /\ run \in {"queued", "running", "completed", "cancelled"}
  /\ clock \in 0..Horizon
  /\ fence \in 0..MaxAttempts
  /\ aliveSet \subseteq Consumers
  /\ pending = "none"
     \/ pending \in [ordinal: 1..MaxAttempts, holder: Consumers,
                     token: 1..MaxAttempts, observed: {"queued", "running"}]

InvSingleOwner ==
  Cardinality({a \in Range(attempts) : Running(a)}) <= 1

InvEffectOnce ==
  ~Once \/ Cardinality(dispatched) <= 1

InvAcceptanceIsCurrent ==
  run # "completed" \/ attempts[Len(attempts)].status = "completed"

InvNoViolations == violations = {}

=============================================================================
