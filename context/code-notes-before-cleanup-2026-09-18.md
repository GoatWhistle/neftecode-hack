# Свидетельства из кода перед удалением комментариев (A0b)

Дата: 2026-09-18. Собрано автоматически ПЕРЕД удалением всех комментариев
и докстрингов из `src/` и `tests/` (задача A0b в TODO.md).

Отбирались комментарии и докстринги, в которых мы сами называем дефекты,
упрощения и границы применимости решения — материал защиты перед жюри.
Ссылки вида `файл:строка` указывают на состояние ДО удаления (коммит 8b4e8e3 + рабочее дерево).

## `src/neftecode/application/agentic/contracts.py`

- **src/neftecode/application/agentic/contracts.py:1** (docstring `<module>`)
  > Structured contracts between language model agents and the deterministic core.
  > A model answer becomes a machine decision only through a parser here. Parsers are strict: unknown keys, wrong types, values out of range and silently "almost JSON" are rejected. What a model may propose is a closed vocabulary of constraints that can only narrow the set of plans the gate has already accepted.

- **src/neftecode/application/agentic/contracts.py:51** (docstring `ContractViolation`)
  > A model answer that does not satisfy the contract. Never interpreted further.

## `src/neftecode/application/agentic/decision.py`

- **src/neftecode/application/agentic/decision.py:1** (docstring `<module>`)
  > AgenticMakeDecision: language model agents on top of the deterministic decision, never around it.
  > Order of authority:
  > 1. The legacy `MakeDecision` runs first. Its result is the reference and the fallback. 2. Agents inspect gate-feasible candidates, consult each other, narrow the search and propose an action. 3. Code resolves the action: only gate-feasible, validator-passing plans that satisfy the accepted constraints and carry no veto are allowed; among them the declared `rank()` chooses. 4. The chosen plan goes through the same `release` as legacy (look-ahead, final re-check, robustness). 5. A guard re-evaluates the released plan with a fresh planner; if the gate fails, the answer is a refusal.
  > Any failure of the agent layer returns the legacy decision. The agent layer can make an answer more conservative (a refusal with evidence, a narrower choice), never less safe.

## `src/neftecode/application/agentic/loop.py`

- **src/neftecode/application/agentic/loop.py:1** (docstring `<module>`)
  > The bounded conversation between one agent and its tools.
  > The model chooses which allowlisted tool to call next; code executes it and returns compact results. The loop ends when the model submits a final answer that passes the strict contract, or when a bound is hit. It never loops past `max_calls`, never runs a tool outside the allowlist and never accepts a final answer the parser rejects.

## `src/neftecode/application/agentic/session.py`

- **src/neftecode/application/agentic/session.py:25** (docstring `SessionError`)
  > A tool request that cannot be answered (unknown candidate, exhausted limit, missing input).

## `src/neftecode/application/agentic/tools.py`

- **src/neftecode/application/agentic/tools.py:1** (docstring `<module>`)
  > Deterministic tools agents may call, their argument schemas and per-agent allowlists.
  > A tool reads the session; it never changes a limit, a gate verdict or a figure. Arguments are validated against the declared schema before the handler runs, and results are compact JSON with an evidence reference an agent must cite.

## `src/neftecode/application/ports/live.py`

- **src/neftecode/application/ports/live.py:8** (docstring `ForecastBindingError`)
  > A forecast cannot be safely bound to the production scenario.

## `src/neftecode/application/ports/response_effect.py`

- **src/neftecode/application/ports/response_effect.py:12** (docstring `effect`)
  > Return at least `available: bool` and `reason: str`; numbers only when available.

## `src/neftecode/application/services/explain.py`

- **src/neftecode/application/services/explain.py:1** (docstring `<module>`)
  > Turning a decision into something an operator can check, line by line.
  > Every statement here is built from a number the calculation actually produced, and carries the reference that number came from: an observation, a scenario parameter, a model version or a named gate check. A non-empty citation is not enough — the value in the statement and the value in the evidence are the same object, so a claim cannot drift away from the computation.
  > What is deliberately impossible to say:
  > * an unverified "process cause". Nothing here explains *why* the plant behaves as it does; it explains what was computed, from which inputs, and which limits were checked. * a refusal without a next step. Each refusal names its kind — bad data, an unusable model, or no feasible plan — and what would have to change, including how long that would take.

- **src/neftecode/application/services/explain.py:25** (comment)
  > Kinds of refusal. They are answered differently, so they are never merged.

- **src/neftecode/application/services/explain.py:165** (comment)
  > Report the tightest point of the plan, not the first: that is the one that could fail.

- **src/neftecode/application/services/explain.py:280** (docstring `explain_refusal`)
  > Build a refusal that says what is missing and what would change the answer.
  > The three kinds are answered differently: bad data needs a measurement, an inapplicable model needs a regime inside its declared region, and an infeasible plan needs a resource or a relaxed *scenario* condition — never a relaxed hard limit.

## `src/neftecode/application/services/trust.py`

- **src/neftecode/application/services/trust.py:1** (docstring `<module>`)
  > Whether the inputs deserve to carry a decision, and what to do when they do not.
  > Two positions are kept apart on purpose:
  > * a source is **usable** — fresh, self-consistent and not contradicted; * a source is **unusable** (or **missing**) — it cannot support a decision, and the reason says what is missing. Individual odd readings are flagged separately in `TrustReport.suspect_values`: they are shown to the operator without revoking the source.
  > A telemetry value of exactly 307 is a polling stub (experts, chat message 582) and is already replaced by a missing value when the sources are loaded; here it is still flagged if it reaches a state. A negative reading is not deleted automatically: for vacuum and zero offsets it can be physically real.

- **src/neftecode/application/services/trust.py:23** (comment)
  > Priority given by the brief, section 2. It does not change with predictive accuracy.

- **src/neftecode/application/services/trust.py:26** (comment)
  > Repeated exactly in 64 of 71 AVT tags and in 15 of 26 tags of 24-2000; a polling stub, confirmed by the experts as an outlier (chat message 582). See context/requirements-map.md, section 6.

- **src/neftecode/application/services/trust.py:71** (docstring `usable`)
  > A decision may proceed only when at least one quality source stands up.

- **src/neftecode/application/services/trust.py:184** (comment)
  > Priority is the brief's, not the forecaster's: LIMS outranks PAK even when PAK happens to predict better.

- **src/neftecode/application/services/trust.py:198** (comment)
  > Falling back means the analyzer cannot be relied on, so a model using its features must not be used either.

## `src/neftecode/application/use_cases/make_decision.py`

- **src/neftecode/application/use_cases/make_decision.py:1** (docstring `<module>`)
  > The agent loop: proposal, veto, a changed search, and a decision or a refusal.
  > The point of separating roles here is not decoration. Each agent answers a question the others are not allowed to answer:
  > * **data** — may this state carry a decision at all? * **quality** — do the three product properties hold at every point? * **reliability** — is the regime within what the scenario permits of the equipment? * **optimizer** — what can be proposed and how do the survivors compare? * **orchestrator** — who is asked, what a veto forbids next, and when to stop.
  > A veto is not a log line: it removes a region of the search, and the next round is demonstrably different. The loop is bounded, so a disagreement cannot spin forever. A failed or incomplete agent answer produces a refusal, never a decision that quietly skipped a check.

- **src/neftecode/application/use_cases/make_decision.py:49** (docstring `AgentError`)
  > Raised when an agent cannot answer; never swallowed into a successful decision.

- **src/neftecode/application/use_cases/make_decision.py:79** (docstring `QualityAgent`)
  > Reads the gate's quality verdicts. It does not compute economics and cannot waive a limit.

- **src/neftecode/application/use_cases/make_decision.py:138** (comment)
  > 1. Data first: a state that cannot carry a decision stops the loop before any model runs.

- **src/neftecode/application/use_cases/make_decision.py:258** (comment)
  > 2b. Look past the horizon: a plan that is fine for three hours may still run the stored product out of spec before anyone can react. This never waives a gate check.

- **src/neftecode/application/use_cases/make_decision.py:287** (comment)
  > 3b. Weak edge of the data-driven response: a plan that moves the reactor-inlet temperature must also pass the gate with the slope as weak as the study allows for the next half-year. A plan that fails there is vetoed, not merely called fragile; the remaining feasible plans are ranked again. Holds and plans without a temperature move are not affected.

- **src/neftecode/application/use_cases/make_decision.py:312** (comment)
  > 4. Robustness: a plan that only holds when every coefficient is exactly right is reported as fragile rather than released as reliable.

- **src/neftecode/application/use_cases/make_decision.py:355** (docstring `_weak_response_guard`)
  > Gate verdict for `plan` with the data-driven slope at its weak edge (`weak_strong[0]`).
  > The gate runs over the case horizon and, when the look-ahead is on, over the same extended horizon: a temperature move justified by pushing a violation past the reaction window must still do so at the weak edge. None when there is nothing to check: no raw scenario, no parser, or the slope is not from data.

- **src/neftecode/application/use_cases/make_decision.py:488** (docstring `_feedback_candidates`)
  > Create candidates that encode feedback; never present the same search as consensus.

- **src/neftecode/application/use_cases/make_decision.py:530** (docstring `_forbidden`)
  > Apply the accumulated restrictions to the candidate before it is evaluated.
  > The restriction is computed per tank, not against one global ceiling: a veto saying "the draw is too big" must remove exactly the candidates that draw too much, otherwise the next round would examine the same set and the loop would be theatre.

## `src/neftecode/application/use_cases/plan_operation.py`

- **src/neftecode/application/use_cases/plan_operation.py:1** (docstring `<module>`)
  > Short plans over the horizon: the transitional blend while the hydrotreater catches up.
  > The situation this exists for: crude worsens, a hydrotreating correction is the right answer, but it takes hours to act. Meanwhile the product still has to meet spec. So a plan holds a richer blend during the transition and steps back once the correction has taken effect.
  > What the planner is careful about:
  > * **A proposal is not an execution.** A plan's own steps are evaluated as *if* executed; what actually reached the plant comes in as confirmed `PendingAction`s from the caller. Running the advisor twice does not make the advice happen. * **No flip-flopping.** A change is only proposed if it clears the scenario's minimum useful benefit, and a plan is not allowed to undo a confirmed action that has not yet had time to show its effect. * **Stocks are real.** Every step draws from the tanks, so a transitional blend that would outlast the reserve is rejected where it fails.

- **src/neftecode/application/use_cases/plan_operation.py:121** (comment)
  > The chain does not model diesel density; the inflow keeps the component's declared density.

- **src/neftecode/application/use_cases/plan_operation.py:157** (comment)
  > Transitional plans: a correction now, a richer blend until it acts, then step back. Throughput is varied here too: a transitional plan pinned to one throughput would fail on an outflow limit and never be compared on its merits.

- **src/neftecode/application/use_cases/plan_operation.py:282** (docstring `evaluate`)
  > Run the plan through the chain, the blender, the tanks and the gate.
  > `confirmed` carries operator-confirmed actions as `(applied_at_hours, controls)`. The plan's own steps are treated as proposals: they shape the trajectory being evaluated, but they never enter `confirmed` on their own.

- **src/neftecode/application/use_cases/plan_operation.py:295** (comment)
  > A plan step carries its DELTA from the scenario baseline, not a full set of setpoints. Otherwise a plan that does not touch a control would silently revert a correction the operator has already confirmed.

- **src/neftecode/application/use_cases/plan_operation.py:418** (docstring `_main_sulfur`)
  > Current level of the main component's sulfur, or None when it cannot be known.
  > Either the chain produces it (so crude quality and the standing regime reach the decision), or the scenario declares it — for instance because a trained forecast was bound into it, which outranks the model.
  > When the scenario says the level comes from the chain and the chain cannot produce it, the answer is unknown. Falling back to the standing constant would substitute a placeholder the scenario itself calls a reference value, and the gate would see a number where it must see `unknown`.

## `src/neftecode/application/use_cases/replay_decisions.py`

- **src/neftecode/application/use_cases/replay_decisions.py:1** (docstring `<module>`)
  > Replaying decisions: the same core, on history and in the scenario environment.
  > Two modes, deliberately not mixed in the output:
  > * **historical** — the decision core runs at a past moment using only what was available then. The future laboratory value exists, but it goes to the evaluator *after* the decision and never into the state the agents see. * **simulated** — actions are applied through a separate execution state with its own material balance. This is where an alternative control can be studied at all, because history contains no observation of what an unexecuted action would have produced.
  > Because of that split, a historical replay must never be continued as though a recommendation had been carried out. The history is the history: it already contains whatever the operator actually did, and nothing else.

- **src/neftecode/application/use_cases/replay_decisions.py:42** (docstring `ExecutionState`)
  > What the simulated plant actually holds and what has actually been executed.
  > Kept apart from the advisor's state so that issuing advice cannot change the plant, and so that a pause and a resume lose neither inventory nor a pending action.

- **src/neftecode/application/use_cases/replay_decisions.py:174** (docstring `step`)
  > One decision. `future_truth` is returned for evaluation and never shown to the agents.

- **src/neftecode/application/use_cases/replay_decisions.py:191** (comment)
  > The evaluator gets the truth; the agents never saw it.

- **src/neftecode/application/use_cases/replay_decisions.py:224** (docstring `_apply`)
  > Apply only what the operator confirmed in this moment, never the advice itself.

## `src/neftecode/composition/demo.py`

- **src/neftecode/composition/demo.py:97** (comment)
  > Deliberate allowlist: future target and its actual value NEVER reach agents.

## `src/neftecode/composition/training.py`

- **src/neftecode/composition/training.py:46** (comment)
  > Risk thresholds belong to the measured property. In particular, an absent T95 product limit remains unknown; sulfur's 10 mg/kg limit must never be inherited by a temperature forecast.

## `src/neftecode/domain/advisory/entities.py`

- **src/neftecode/domain/advisory/entities.py:179** (docstring `CheckResult`)
  > One mandatory check at one time. Status `unknown` never counts as satisfied.

- **src/neftecode/domain/advisory/entities.py:211** (docstring `GateResult`)
  > Verdict over the whole trajectory. Feasibility is derived, never asserted by a caller.

## `src/neftecode/domain/advisory/gate.py`

- **src/neftecode/domain/advisory/gate.py:1** (docstring `<module>`)
  > The one place a plan is allowed to be declared acceptable.
  > Every mandatory condition — product qualities, control ranges, additive dose, tank stocks, outflow limits, model applicability — is checked at EVERY point of the trajectory and folded into a single `GateResult`. Feasibility is derived from the checks, never asserted by a caller.
  > Two properties this module exists to guarantee:
  > * a plan that is safe only at the end of the horizon does not pass, because the violation is recorded at the time it happens; * `unknown` blocks. A condition that could not be evaluated is not a condition that was met, no matter how attractive the plan's economics are.
  > Discretisation is explicit: the gate sees the points the trajectory was computed at. Between two checked points nothing is known, so `step_hours` is reported and a coarse grid is flagged rather than silently trusted.

- **src/neftecode/domain/advisory/gate.py:165** (docstring `applicability_check`)
  > A result produced outside the model's declared region cannot support a recommendation.

## `src/neftecode/domain/advisory/optimizer.py`

- **src/neftecode/domain/advisory/optimizer.py:1** (docstring `<module>`)
  > Generating candidate actions and choosing between the ones that survive the gate.
  > Design rules that keep the result honest:
  > * **Keeping the regime is always a candidate.** If the current mode is feasible and no change clears the minimum useful benefit, the answer is to leave it alone. * **The search is finite and enumerated in a fixed order**, so the result does not depend on dictionary iteration or on which candidate happened to be generated first. Ties are broken by a declared comparison key ending in the candidate id. * **Infeasible candidates are never ranked.** They are filtered by the gate before comparison, so no weighting can let a violation win. * **No global optimum is claimed.** The budget is reported, and when it is exhausted the result says the answer is the best of what was examined.

- **src/neftecode/domain/advisory/optimizer.py:81** (docstring `_throughputs`)
  > Current output and below, never above.
  > Raising output is a commercial decision the advisor is not making: its job is to keep quality, and lowering throughput is the lever the brief names for that (a smaller run instead of a load increase that is not available). Proposing more output would also manufacture a "gain" in every comparison and drown the hold candidate.

- **src/neftecode/domain/advisory/optimizer.py:122** (docstring `generate`)
  > Enumerate candidates in fixed layers until the budget is spent.
  > Layers rather than one nested product: truncating a nested loop would silently drop whole regions of the search (every high reserve fraction, say) and the result would look like a decision when it was an artefact of the iteration order. Each layer varies one aspect, so an exhausted budget costs the least important layer first.

- **src/neftecode/domain/advisory/optimizer.py:227** (docstring `key`)
  > Declared comparison order. Missing figures sort last, never first.

## `src/neftecode/domain/advisory/response_guard.py`

- **src/neftecode/domain/advisory/response_guard.py:1** (docstring `<module>`)
  > Does a plan lean on the hydrotreating response, and what does it look like at the weak edge?
  > The data-driven slope β on the reactor-inlet temperature carries a range for the next half-year (`weak_strong`). A plan that moves the temperature is only as safe as its weakest credible response: if the product limit holds at β but fails at the weak edge, the plan is not a guarantee but a bet. These helpers say (a) whether a plan moves the temperature or any hydrotreating setpoint at all — holds and blend-only plans do not, so perturbing the response says nothing about them — and (b) what the bound scenario looks like with the slope taken at the weak edge.

- **src/neftecode/domain/advisory/response_guard.py:45** (docstring `weak_response_factor`)
  > Multiplier turning the bound slope k = −β/S₀ into its weak-edge value, or None without data.

- **src/neftecode/domain/advisory/response_guard.py:57** (docstring `weak_response_raw`)
  > Copy of the bound scenario with the slope at the weak edge; None when no data-driven slope is bound.

## `src/neftecode/domain/monitoring/entities.py`

- **src/neftecode/domain/monitoring/entities.py:43** (docstring `visible_at`)
  > A late sample appears only after available_at, never retroactively.

## `src/neftecode/domain/production/blending.py`

- **src/neftecode/domain/production/blending.py:1** (docstring `<module>`)
  > Blending four qualities, and what the cetane additive may and may not be credited with.
  > Density is blended by volume additivity (total mass over total volume), a declared ideal-mixing assumption; the product carries a two-sided density limit.
  > Sulfur is a mass balance: no reaction happens in a tank, so the blend carries the mass-weighted sulfur of its components. That is the only one of the three with a defensible exact rule here.
  > T95 and cetane number are NOT mass-additive in reality. Distillation points and cetane number blend non-linearly, and the package supplies no blending indices. So each is computed by a declared scenario rule with its own applicability, and the result says which rule produced it. Applying the sulfur formula to them silently would be the easy, wrong answer.
  > Anything unknown stays unknown. A component with no cetane number makes the blend's cetane number unknown — not "fine", not "the average of the others".

- **src/neftecode/domain/production/blending.py:29** (comment)
  > Properties the cetane additive is allowed to touch. Sulfur is deliberately absent: a cetane improver does not remove sulfur, and the scenario loader refuses to claim it does.

- **src/neftecode/domain/production/blending.py:153** (comment)
  > T95 and cetane number: declared scenario rules, not the sulfur formula.

- **src/neftecode/domain/production/blending.py:206** (docstring `meets_spec`)
  > Compare each quality with its limit. Unknown is reported as unknown, never as a pass.

## `src/neftecode/domain/production/economics.py`

- **src/neftecode/domain/production/economics.py:1** (docstring `<module>`)
  > Cost, production and how hard the hydrotreater is being pushed.
  > Three separate things, deliberately not fused into one score:
  > * **production** — tonnes of blended product over the plan; * **cost** — components, the additive and the energy of treating, each from a declared price. Treating energy grows with the square of how far below the reference sulfur level the stream is pushed (organisers' written answer of 18.09.2026: "растут квадратично от запаса" below 8 ppm); the scale of that square is a scenario constant; * **severity** — how far the hydrotreater is driven from its reference regime.
  > Severity is a described index, not a residual life and not a failure probability. The package contains no catalyst change dates, no run-length and no failure labels, so any claim about remaining life would be invented. The index only says "this regime is harder than that one", by rules written down here and weighted by the scenario.
  > Costs are counted once. Per-tonne prices and totals over the horizon are reported separately, so a reader cannot accidentally add the same expense twice.

## `src/neftecode/domain/production/inventory.py`

- **src/neftecode/domain/production/inventory.py:1** (docstring `<module>`)
  > Tank inventories over the plan: what is actually available, step by step.
  > A recipe that is fine right now can be impossible an hour later. This module carries the mass balance forward through the plan so that a blend which would empty a tank mid-horizon is caught where it fails, not averaged away.
  > Two rules that are easy to get wrong and are enforced here:
  > * **Mass is conserved.** Every tonne drawn leaves the tank; replaying the same step twice does not spend the stock twice, because each step returns a new state instead of mutating one. * **The end of the horizon is not the end of the plant.** A plan that survives only by draining the reserve to zero at the last point is not feasible: the terminal rule demands a declared minimum remaining supply.

- **src/neftecode/domain/production/inventory.py:62** (docstring `draw_step`)
  > Draw one step. Returns a NEW state; the input is never mutated.
  > Infeasibility is reported, not raised: the optimiser needs to see why a candidate failed so it can propose a different one.

## `src/neftecode/domain/production/offspec.py`

- **src/neftecode/domain/production/offspec.py:1** (docstring `<module>`)
  > Price of getting it wrong, in the same units as the plan's own cost.
  > The organisers' written answer of 18.09.2026 fixes one number: re-blending off-spec product costs an extra 5 % of its cost, applied to the volume already in the tank (`economics.offspec_rework_cost_share`). Two figures follow from it, and they answer different questions:
  > * **rework_cost** — what a wrong regime would cost once the tank has to be re-blended: the share times the main component's price times its stock. It does not depend on the plan; it is the size of the mistake the plan is avoiding. * **plan_extra_cost** — what the chosen plan costs above keeping the regime, over the mass it actually makes.
  > Both are reported, never enforced. Admissibility is decided by the gate on the product limits alone: money orders variants that are already allowed and may not make a forbidden one allowed nor a permitted one forbidden.

## `src/neftecode/domain/production/process.py`

- **src/neftecode/domain/production/process.py:1** (docstring `<module>`)
  > Effect of an action on the chain: AVT, then hydrotreating.
  > This is deliberately NOT the forecast. The forecast answers "what is coming given the history"; this module answers "what would come out if this setpoint were moved". A CatBoost model with one input swapped does not answer the second question, so it is not used here.
  > The relations below are scenario models with declared units, coefficients and an applicability range. They are honest about being ours: the expert allowed the team to build its own justified model, including a simple linear one (message 518). None of it is a measured plant response.
  > Everything works in the named physical variables of the process schemes (`crude_feed_rate_tph`, `ht_reactor_inlet_temp_c`, …), never in the raw CSV tags, because the magnitudes of the 24-2000 tags contradict their descriptions — see context/requirements-map.md.

- **src/neftecode/domain/production/process.py:25** (docstring `ProcessError`)
  > Raised when a model is asked for something it does not claim to describe.

- **src/neftecode/domain/production/process.py:166** (docstring `HydrotreatingModel`)
  > Sulfur leaving the hydrotreater, and how long a setpoint change takes to show up.
  > Structure, coefficients declared in the scenario:
  > conversion = 1 - (1 - conversion_at_reference) * exp(-dk_dT * (T_inlet - T_reference)) * (space_velocity / reference_space_velocity) ** severity_exponent outlet_sulfur = inlet_sulfur * (1 - conversion)
  > Higher inlet temperature removes more sulfur; higher throughput leaves less residence time and removes less. Both directions are ordinary hydrotreating behaviour; the magnitudes are ours and carry no measured backing.
  > **Delay is part of the model, not decoration.** `apply_at` returns the setpoint actually acting at a given time, so a change made now cannot improve the product now. Two successive changes are handled by taking the most recent one already in effect: adding their separate effects would count the same move twice.

- **src/neftecode/domain/production/process.py:227** (docstring `effective_controls`)
  > Which setpoints are actually acting at `time_hours` after the decision.
  > `pending` holds `(applied_at_hours, controls)` for confirmed moves. Only the latest move whose lag has elapsed is in effect: successive changes supersede each other rather than accumulating.

## `src/neftecode/domain/production/scenario.py`

- **src/neftecode/domain/production/scenario.py:1** (docstring `<module>`)
  > Executable chain scenario: what is measured, what is assumed and what stays unknown.
  > Every physical number carries a unit and a provenance, so a scenario constant can never be read back as if it were a plant measurement. Loading validates structure, units and ranges; a missing optional quality is preserved as unknown instead of silently becoming a pass.

- **src/neftecode/domain/production/scenario.py:16** (comment)
  > Units accepted for each named quantity. A scenario declaring another unit is rejected rather than converted by guesswork.

- **src/neftecode/domain/production/scenario.py:63** (docstring `measured`)
  > True only for values traceable to the issued data, never for our own assumptions.

- **src/neftecode/domain/production/scenario.py:125** (comment)
  > True when this component leaves the modelled chain, so its sulfur is whatever the chain produces at the current regime rather than a standing scenario constant. A real forecast bound into the scenario overrides it: a measurement outranks a model.

- **src/neftecode/domain/production/scenario.py:156** (docstring `ProductSpec`)
  > Declared product limits. A None limit is unknown, which is not the same as no limit.

- **src/neftecode/domain/production/scenario.py:173** (docstring `Additive`)
  > Cetane additive. Its dose response is our assumption, not a supplied curve.

- **src/neftecode/domain/production/scenario.py:283** (docstring `unknown_properties`)
  > Qualities a tank does not declare. These make the blend result unknown, not compliant.

## `src/neftecode/domain/production/state.py`

- **src/neftecode/domain/production/state.py:49** (docstring `draw`)
  > Withdrawal that would go negative is an error, not a silent clamp to zero.

## `src/neftecode/domain/shared/actions.py`

- **src/neftecode/domain/shared/actions.py:37** (docstring `effect_expected_at`)
  > Unconfirmed advice has no expected effect time: it was never executed.

## `src/neftecode/evaluation/benchmark.py`

- **src/neftecode/evaluation/benchmark.py:1** (docstring `<module>`)
  > Is the advisor worth more than a simple rule? Measured on identical conditions.
  > Three strategies are run on exactly the same scenarios, with the same limits, the same tanks and the same models:
  > * **hold** — keep the current regime whatever happens; * **threshold** — a single rule: if the predicted sulfur is above the limit, raise the reserve fraction one notch at a time until it fits. It gets the same hard checks as everyone else, because building a deliberately crippled opponent would prove nothing; * **advisor** — the full agent loop.
  > Two ablations answer "what are the extra parts for": the advisor without transitional planning (single-step plans only) and the advisor without the terminal stock rule.
  > What the result is NOT: measured savings at a refinery. Every number here comes from our own scenario models, and the advisor is compared inside the same model it optimises against. That limitation is reported with the numbers, not left to the reader.

- **src/neftecode/evaluation/benchmark.py:41** (docstring `_outcome`)
  > Figures for one strategy, including the ones the advisor does NOT optimise.
  > Masses are integrated over the horizon: each step is held until the next one, and the last until the horizon ends. Summing per-step rates without their durations would make a two-phase plan look twice as wasteful as a constant one.

- **src/neftecode/evaluation/benchmark.py:265** (docstring `_wins_and_losses`)
  > Where the advisor beats the simple strategies, and where it does not.
  > Comparison runs over several dimensions on purpose. Production alone is the dimension the advisor ranks by while searching a superset of the simple rules' options, so it wins there almost by construction; a report showing only that would be a rigged scoreboard.

## `src/neftecode/evaluation/episodes.py`

- **src/neftecode/evaluation/episodes.py:1** (docstring `<module>`)
  > Evaluate analyzer excursions, batch proxies, margins and alarm lead time.
  > An instantaneous excursion of the online analyzer is evidence, not a violation. This module separates short flickers from sustained excursions and reports both, so an alarm rule is never tuned against a target it invented. The same duration convention is used by every calculation in this module.

- **src/neftecode/evaluation/episodes.py:70** (docstring `batch_average`)
  > Trailing batch proxy. Windows with thin coverage return NaN rather than a guess.

- **src/neftecode/evaluation/episodes.py:113** (docstring `sustained_labels`)
  > Label a decision time as risky when it falls inside a sustained excursion.
  > Used only for reporting alongside the instantaneous label, never as a silent replacement of the laboratory target.

- **src/neftecode/evaluation/episodes.py:152** (comment)
  > Scatter around the fit is carried into the estimate rather than hidden.

- **src/neftecode/evaluation/episodes.py:196** (docstring `margin_series`)
  > Vectorised margin over the whole record, for measuring warning lead time.
  > The slope is a finite difference of the batch proxy rather than a refitted regression: coarser than `trend_margin`, but computed identically at every point.

- **src/neftecode/evaluation/episodes.py:249** (comment)
  > The period the detector actually ran over. Absence of an alarm outside it is absence of knowledge, not absence of risk, so those episodes become `unknown` rather than `missed`.

## `src/neftecode/evaluation/expert_grid.py`

- **src/neftecode/evaluation/expert_grid.py:1** (docstring `<module>`)
  > What happens when an expert turns the knobs, recorded rather than promised.
  > The organisers described the defence plainly (Q&A 15.09): the team brings a scenario and the experts change it to see how the solution reacts. This module runs that grid ahead of time through the very call the panel makes (`Demo.run`, injected by the composition root, so this layer does not reach up into presentation), and every row is produced by the real loader and the real core, not by a rehearsal.
  > Three things are being looked for, and all three are reported:
  > * a traceback instead of an honest refusal — any row whose `error` is set is a defect, because an expert at the keyboard must never see a stack trace; * an absurd number — the grid records cost per tonne and the severity index so a value that jumps by orders of magnitude is visible rather than discovered live; * recomputation time — an expert will not wait a minute, so the worst case is measured.
  > A rejected change is a correct outcome, not a failure: the scenario loader refuses an inadmissible condition with its own message, and the row records that message.

- **src/neftecode/evaluation/expert_grid.py:38** (comment)
  > Data faults, run on the unchanged scenario: they test the refusal path, not the arithmetic.

- **src/neftecode/evaluation/expert_grid.py:53** (docstring `GridError`)
  > Raised when the grid cannot be built from the scenario it was given.

- **src/neftecode/evaluation/expert_grid.py:87** (docstring `_row`)
  > One grid point. A crash is caught and recorded as a defect, never re-raised.

- **src/neftecode/evaluation/expert_grid.py:124** (docstring `ExpertGrid`)
  > Runs the grid and reports defects separately from ordinary outcomes.

- **src/neftecode/evaluation/expert_grid.py:142** (docstring `summarise`)
  > Aggregate one scenario's rows, keeping the defects in plain sight.

## `src/neftecode/evaluation/robustness.py`

- **src/neftecode/evaluation/robustness.py:1** (docstring `<module>`)
  > Would the chosen plan still hold if the models are a little wrong?
  > The models here are ours: scenario coefficients, a declared response lag, component properties taken from the scenario rather than measured. A plan that only works when all of that is exactly right is not a plan, it is a coincidence. So the selected plan is re-evaluated under a declared set of perturbations and the result says plainly how many of them it survives.
  > Deliberate limits of this check:
  > * the perturbations are OURS. Surviving them is not a probability of success and not a confidence interval; it is "this plan held under these listed deviations". * the same response model is perturbed, so this does not test a structurally different plant. That limitation is reported with the result rather than left for the reader to notice. * a long excursion in the history is not evidence of a new regime. Applicability is decided by the model's declared region, not by how unusual a period looked.

- **src/neftecode/evaluation/robustness.py:38** (comment)
  > A plan surviving fewer than this share of the perturbations is called fragile.

- **src/neftecode/evaluation/robustness.py:43** (docstring `response_perturbations`)
  > Возмущения k по границам отклика из данных, когда модель ГО связана с C2.
  > Границы — `weak_strong` (диапазон следующего полугодия по исследованию), при их отсутствии — `beta_ci`. k = −β/S₀, поэтому множитель к текущему k равен bound/β; знаки должны совпадать с β.

- **src/neftecode/evaluation/robustness.py:64** (docstring `inapplicable_reason`)
  > Why a response or lag perturbation cannot act on this plan, or None when it can.
  > A perturbed slope only matters to a plan that moves the reactor-inlet temperature; a perturbed lag only to a plan that moves a hydrotreating setpoint. For a hold or a blend-only plan such a perturbation changes nothing, and counting it as "held" would dress the plan up as robust against a deviation it never met.

- **src/neftecode/evaluation/robustness.py:79** (docstring `RobustnessError`)
  > Raised when a perturbation cannot be applied to the scenario as declared.

- **src/neftecode/evaluation/robustness.py:226** (docstring `choose_robust`)
  > Prefer a plan that survives the perturbations over a nominally better fragile one.

## `src/neftecode/evaluation/vak.py`

- **src/neftecode/evaluation/vak.py:1** (docstring `<module>`)
  > Virtual analysers: parse the 17 published formulas, apply the expert's corrections, check them.
  > The sheet mixes decimal commas with points and uses `x` where `*` is meant, so the text is normalised before parsing. Parsing goes through Python's own expression grammar restricted to arithmetic over named tags: no attribute access, no calls, no names outside the tag map.
  > What a formula is and is not:
  > * it is a published dependency, usable as a calculated feature and as a fallback estimate; * it is **not** evidence of causality. The sign of a coefficient does not authorise moving that tag. See context/idea-review.md, section 2.
  > A formula whose inputs cannot be bound — the two `LIMS:24-2000.Pipeline...` references have no declared laboratory point — reports explicit unavailability instead of a number.

- **src/neftecode/evaluation/vak.py:48** (comment)
  > Laboratory inputs with no declared sampling point. Formulas needing them cannot be computed. Identifiers deliberately carry no digits next to underscores: the punctuation normalisation below rewrites `<digit>_<digit>` back into a decimal point.

- **src/neftecode/evaluation/vak.py:72** (comment)
  > AVT formula groups bound to laboratory points by process position, fixed BEFORE any comparison. The expert said (Q&A 11.09) that AVT point numbers mean position in the process: point 1 is inside the unit, point 3 is the final exit. The `240-350` group is the diesel cut leaving the unit and point 3 carries its D15, T50, end point and filterability limit. The `350` group needs I350, which only point 1 measures, and the ЛА sheet labels point 1 properties «до 350». This is a declared hypothesis, not a confirmed binding, and a poor result does not move a formula elsewhere.

- **src/neftecode/evaluation/vak.py:98** (docstring `VakError`)
  > Raised when a formula cannot be parsed or bound, with the offending text.

- **src/neftecode/evaluation/vak.py:110** (comment)
  > Decimal comma only between digits; a comma elsewhere would be a separator we must not eat.

- **src/neftecode/evaluation/vak.py:119** (docstring `_balance`)
  > Drop the single unmatched closing bracket rather than guessing a new grouping.

- **src/neftecode/evaluation/vak.py:148** (docstring `computable`)
  > A formula needing an unbound laboratory point yields unavailability, not a number.

- **src/neftecode/evaluation/vak.py:229** (comment)
  > A denominator near zero produces unknown, never a huge number that looks like a reading.

- **src/neftecode/evaluation/vak.py:340** (docstring `input_locations`)
  > Where the AVT inputs of a formula sit on the schemes: column, stream, legend mark.
  > The location explains which part of the unit a formula describes. It does not turn a coefficient into a permission to move that tag.

## `src/neftecode/infrastructure/agentic/factory.py`

- **src/neftecode/infrastructure/agentic/factory.py:78** (docstring `default_decision_factory`)
  > Factory from the process environment and `<root>/.env`, built once per root.
  > `root` is the project root the command was given (`--root`); the working directory is only the fallback, so a run from another folder does not silently lose the key and fall back.

## `src/neftecode/infrastructure/data/data.py`

- **src/neftecode/infrastructure/data/data.py:23** (comment)
  > Exactly this value is a polling stub, not a measurement. The experts confirmed it (chat, message 582, 2026-09-16: "307 — это выброс"); in the data it appears simultaneously in dozens of tags, including ones whose physical range excludes it (a sulfur analyser around 8 ppm, a separator at 35 °C).

- **src/neftecode/infrastructure/data/data.py:27** (comment)
  > A telemetry column that is a stub more often than this is not measured at all and is dropped.

- **src/neftecode/infrastructure/data/data.py:32** (docstring `mask_stubs`)
  > Replace polling stubs by missing values and drop columns that never carry a measurement.
  > With `until` the stub share is measured on the rows before it only (the training period), so the choice of columns does not look at later data. Without it the whole frame is used (synthetic tests).

- **src/neftecode/infrastructure/data/data.py:55** (docstring `load_sources`)
  > Read the four sources. `dead_until` — end of the training period (cfg["train_end"]) for `mask_stubs`.

- **src/neftecode/infrastructure/data/data.py:115** (docstring `backward_readings`)
  > Join by availability, retaining sample time. Never backfill from the future.

- **src/neftecode/infrastructure/data/data.py:126** (comment)
  > Frozen by T108 from the pre-2026 rolling protocol. Runtime configuration may repeat this record for provenance, but may not silently retune it.

- **src/neftecode/infrastructure/data/data.py:156** (docstring `causal_pak_lab_bias`)
  > Median LIMS-minus-PAK correction known at each decision time.
  > A laboratory sample is paired with the last PAK value no more than 30 minutes before its sampling time. The pair enters the rolling history only at ``sample_time + delay_hours``; consequently later laboratory results cannot rewrite an earlier forecast. Until ``min_pairs`` finite pairs are known the conservative correction is zero.

- **src/neftecode/infrastructure/data/data.py:209** (comment)
  > Time-based trailing windows, right closed. No centered windows/interpolation. This window looks BACKWARD over available history; it is not the forecast horizon.

- **src/neftecode/infrastructure/data/data.py:271** (docstring `make_dataset`)
  > One real laboratory analysis produces exactly one evaluation row.
  > Rare analyses are never resampled onto the 10-minute telemetry grid: that would turn 1 458 measurements into tens of thousands of dependent rows and inflate every metric.
  > `target_lab` lets another laboratory series be the target while the features keep coming from the sulfur sources. The leak guard below then compares the right pair of times.

- **src/neftecode/infrastructure/data/data.py:291** (comment)
  > Persistence of the SAME property. Comparing a T95 model against the last sulfur reading would be a straw man, not a baseline.

- **src/neftecode/infrastructure/data/data.py:322** (comment)
  > Legacy rules, used only when a configuration carries no rules derived from the data (old model bundles and synthetic tests): 6 identical readings, conflict above max(3; 0.5·LIMS).

## `src/neftecode/infrastructure/data/quality.py`

- **src/neftecode/infrastructure/data/quality.py:1** (docstring `<module>`)
  > Where the estimate of each product quality actually comes from, and where it does not.
  > The brief requires sulfur, and the experts added T95 and cetane number. These three are not in the same position, and pretending otherwise would be the easiest way to produce a confident number with nothing behind it:
  > * **sulfur** — 1 462 laboratory analyses. A forecast is trained and verified chronologically. * **T95** — 1 291 analyses at the same sampling point. A forecast can be trained the same way; the published virtual analyser cannot be used (T07: its input has no declared lab point). * **cetane number** — 42 analyses in the whole package. No model is claimed. The value comes from the scenario or stays unknown.
  > `unknown` is a real answer here. A quality with no estimate blocks the plan through the gate; it never becomes a pass.

- **src/neftecode/infrastructure/data/quality.py:112** (docstring `report`)
  > Machine-readable statement of what the system can and cannot estimate.

## `src/neftecode/infrastructure/live/advisor.py`

- **src/neftecode/infrastructure/live/advisor.py:40** (docstring `LiveError`)
  > Raised when the real measurements cannot be joined to a scenario.

- **src/neftecode/infrastructure/live/advisor.py:471** (docstring `estimate_tank_sulfur`)
  > Sulfur of what is already stored in the main tank, from what flowed in before the decision.
  > The tank is treated as well mixed over its refresh window (inventory over inflow): the mean of trusted analyser readings in that window. Readings inside a flat run of at least `pak_frozen_readings` identical values are not trusted. With too few trusted readings the laboratory mean in the window is used (at least two results); otherwise the level is unknown and no advice may be produced.

- **src/neftecode/infrastructure/live/advisor.py:527** (docstring `bind_forecast`)
  > Bind a hydrotreated-sulfur forecast to the main tank, on a copy.
  > The forecast describes the stream leaving hydrotreating, not the stored product, so its UPPER bound becomes the sulfur of the tank's inflow: the blend is judged against what the incoming stream could be, and the stored mass dilutes it as it does in the plant. With a measurement state the stored sulfur is estimated from history; without one (synthetic scenes) the scenario's declared stored sulfur is kept.

## `src/neftecode/infrastructure/live/origin.py`

- **src/neftecode/infrastructure/live/origin.py:7** (docstring `validate_origin`)
  > Return a local timestamp only when the trained model already existed.

## `src/neftecode/infrastructure/llm/config.py`

- **src/neftecode/infrastructure/llm/config.py:1** (docstring `<module>`)
  > Environment configuration for language model adapters and agent budgets.
  > Values come from the process environment, optionally overlaid on a `.env` file. Keys are wrapped in `Secret` and never appear in reprs, descriptions or error messages.

- **src/neftecode/infrastructure/llm/config.py:48** (docstring `Secret`)
  > A credential that refuses to print itself.
  > Deliberately not a dataclass: `dataclasses.asdict` on settings must not unwrap the value.

## `src/neftecode/infrastructure/llm/demo_policy.py`

- **src/neftecode/infrastructure/llm/demo_policy.py:1** (docstring `<module>`)
  > A deterministic policy that drives the agent layer without a language model.
  > It exists for tests and for the offline demonstration trace. Every branch reads what the deterministic tools returned, so different situations produce different tool sequences. It is NOT a language model and its trace must be labelled as a scripted policy wherever it is shown.

## `src/neftecode/infrastructure/llm/openai_compatible.py`

- **src/neftecode/infrastructure/llm/openai_compatible.py:1** (docstring `<module>`)
  > OpenAI-compatible chat completions adapter (Z.AI Coding Plan, OpenAI, local endpoints).
  > HTTP goes through `urllib.request.urlopen`, looked up at call time so tests can replace it. Provider reasoning (`reasoning_content`) is discarded and never reaches `LLMResponse`.

- **src/neftecode/infrastructure/llm/openai_compatible.py:57** (docstring `call_with_retries`)
  > Retry only retryable errors, at most `max_retries` extra times, with 1s, 2s, ... backoff.
  > `budget_s` bounds all attempts together, not each one: a retry gets what is left after the failed attempt and the pause, and is not made at all when less than a second remains. So one model call never exceeds the deadline the agent budget handed down (`AgentBudget.remaining_seconds`).

## `src/neftecode/infrastructure/llm/scripted.py`

- **src/neftecode/infrastructure/llm/scripted.py:1** (docstring `<module>`)
  > Deterministic stand-ins for a language model: no network, no randomness.
  > `ScriptedLLM` replays a fixed queue of answers. `PolicyLLM` calls a policy function that reads the conversation (including tool results) and decides the next step, so a scripted path can still depend on what the deterministic tools returned. Both report provider "scripted": they are not language models and their traces must never be presented as model reasoning.

## `src/neftecode/infrastructure/ml/forecast.py`

- **src/neftecode/infrastructure/ml/forecast.py:1** (docstring `<module>`)
  > Frozen chronological experiment. Final test never selects or calibrates models.

- **src/neftecode/infrastructure/ml/forecast.py:176** (comment)
  > The rolling bias is a separately pre-registered point method. Do not silently give this new feature to the legacy fitted candidates.

- **src/neftecode/infrastructure/ml/forecast.py:181** (comment)
  > The online analyser measures sulfur only: it is not a baseline for any other property.

- **src/neftecode/infrastructure/ml/forecast.py:223** (comment)
  > Fallback is evaluated separately; never claim it retains the main model's accuracy.

## `src/neftecode/infrastructure/ml/risk.py`

- **src/neftecode/infrastructure/ml/risk.py:14** (docstring `select_threshold`)
  > Lowest threshold satisfying empirical FPR budget. Ties are never split.

- **src/neftecode/infrastructure/ml/risk.py:23** (comment)
  > Strictly above this negative score: tie groups cannot breach the budget.

- **src/neftecode/infrastructure/ml/risk.py:100** (comment)
  > New threshold uses calibration-period negatives; the test cannot move it.

## `src/neftecode/infrastructure/response/estimate.py`

- **src/neftecode/infrastructure/response/estimate.py:1** (docstring `<module>`)
  > β — отклик серы после гидроочистки на температуру входа реактора, оценённый при обучении.
  > Перенос без изменения метода из `context/response-research/t6/response_model.py` (`RESPONSE_MODEL_T6.md`):
  > * 10-минутный кадр `prepare`: установка в работе (T6, T5 > 320 °C, P13 > 3 МПа, F2 > 30000, F9 > q01 F9 на «горячих» строках, без NaN в опорных тегах), `stable_label` = работа ≥ 12 ч до и 6 ч после строки, ПАК на сетке 10 мин (среднее, правая метка), зависание — плато ≥ 1 ч по прошлому, ПАК валиден в 0.05–50 мг/кг; F2 по справочнику — расход газа на линии от ЦК-201; здесь это только эмпирический фильтр режима, не управляющая уставка и не утверждение, что весь поток проходит через Р-202; * ARX на 10-минутных приращениях (24 лага T6, F9, ПАК-30 мин) по строкам `stable_label`; β — среднее накопленного отклика через 3–8 ч на устойчивый шаг +1 °C по T6; окно (τ − 12 мес., τ − 6 ч]; ДИ90 — бутстреп по месяцам, 40 повторов; * weak = 0.5·β; strong = β × max прошлых отношений realized/estimate по полугодиям (cap −1.0 мг/кг/°C); * область: q01–q99 T6 и F9 по пригодным 30-минутным строкам до τ; дрейф — тот же ARX по полугодиям (realized).
  > Оценка делается на сетке τ (1 января / 1 июля, начиная с первого τ, у которого есть 12 месяцев истории, плюс `train_end` и конец данных); живое решение берёт последнюю оценку с τ не позже момента решения (`response_at`), все её окна заканчиваются в τ − 6 ч — строго до момента.

## `src/neftecode/infrastructure/response/unavailable.py`

- **src/neftecode/infrastructure/response/unavailable.py:11** (docstring `UnavailableResponseEffect`)
  > Always answers that the data-derived effect is unavailable; never invents a number.

## `src/neftecode/presentation/cli.py`

- **src/neftecode/presentation/cli.py:1** (docstring `<module>`)
  > Command-line presentation boundary.
  > The parser owns the stable command contract. Runtime wiring is supplied by the top-level composition root so this layer does not depend on infrastructure or evaluation modules.

## `src/neftecode/presentation/demo.py`

- **src/neftecode/presentation/demo.py:1** (docstring `<module>`)
  > Changeable demonstration: the jury edits the conditions, the core recomputes.
  > The requirement this satisfies is narrow and strict: an arbitrary admissible change must reach the calculation, not switch between prepared answers. So a change here is an edit of the scenario document, which is then parsed by the same loader with the same validation, and run through the same orchestrator. There is no branch in this module that returns a stored text.
  > Consequences kept on purpose:
  > * an inadmissible change is rejected by the scenario loader with its own message — the demo does not silently repair it; * an injected failure (a frozen analyser, an unavailable tank) is labelled as an injection, so nobody mistakes it for something observed in the data; * the original scenario is always recoverable, because every change is applied to a fresh copy.

- **src/neftecode/presentation/demo.py:40** (comment)
  > Data faults the jury can inject. They are model injections, never observations.

- **src/neftecode/presentation/demo.py:63** (docstring `apply_change`)
  > Apply one change to a COPY of the scenario. The original is never touched.

- **src/neftecode/presentation/demo.py:197** (docstring `scenes`)
  > The demonstration scenes, expressed as changes rather than as canned answers.
  > Со срезами сцены отказов идут на реальных моментах (`snapshot` — подпись среза из config/snapshot_moments.json), а инъекция не нужна. «Ухудшение сырья» остаётся синтетической: в живом пути сера сырья сокращается в отношении откликов, сцена имеет смысл только с абсолютной моделью цепочки. Сцена риска по качеству существует только на реальном срезе: инъекции риска качества здесь нет и быть не должно, поэтому без среза она не показывается.

## `tests/agentic/conftest.py`

- **tests/agentic/conftest.py:1** (docstring `<module>`)
  > Agent tests never reach the network. Provider tests install their own mock on top of this guard.

## `tests/agentic/test_legacy_baseline.py`

- **tests/agentic/test_legacy_baseline.py:1** (docstring `<module>`)
  > Regression net for the deterministic decision loop before the agent layer is added.
  > Every case the agent layer must never make less safe is pinned here: hold, recommendation, refusal on data (both paths), refusal with no feasible plan, a failed final re-check, an unknown limit and a fragile plan. The frozen hashes live in tests/test_architecture_baseline.py; this file pins the meaning behind them so a change is explained, not only detected.

- **tests/agentic/test_legacy_baseline.py:24** (comment)
  > scenario -> (status, plan id, refusal kind, production, fragile, rounds, evaluated, trace agents, decision id)

## `tests/agentic/test_old_vs_new.py`

- **tests/agentic/test_old_vs_new.py:1** (docstring `<module>`)
  > Old vs new on every shipped scenario: the agent layer may narrow or refuse, never release an unchecked plan.

## `tests/agentic/test_ports.py`

- **tests/agentic/test_ports.py:1** (docstring `<module>`)
  > The language model port validates its messages; the response effect boundary never invents numbers.

## `tests/agentic/test_safety.py`

- **tests/agentic/test_safety.py:1** (docstring `<module>`)
  > Adversarial model behaviour never produces a plan the gate did not accept, and failures fall back.

## `tests/test_agents.py`

- **tests/test_agents.py:51** (comment)
  > Stored 10.7 mg/kg: the point inflow 9 keeps the blend in spec, the upper bound 14 does not.

## `tests/test_benchmark.py`

- **tests/test_benchmark.py:1** (docstring `<module>`)
  > Comparison with simple rules: identical conditions, no weak opponent, no dropped cases.

- **tests/test_benchmark.py:128** (docstring `test_switching_off_the_terminal_rule_looks_better_and_that_is_stated`)
  > Removing the terminal rule never lowers the apparent number, and the report says why.

- **tests/test_benchmark.py:213** (docstring `test_real_losses_are_found_and_reported`)
  > A scoreboard with no losses at all would be a rigged one.

- **tests/test_benchmark.py:257** (comment)
  > Производимый по необходимости компонент ограничен подачей, а не запасом.

## `tests/test_blending.py`

- **tests/test_blending.py:96** (comment)
  > --- T95 and cetane are not silently treated as sulfur ---

## `tests/test_contracts.py`

- **tests/test_contracts.py:138** (comment)
  > --- TankState: inventory cannot be spent twice ---

## `tests/test_demo.py`

- **tests/test_demo.py:27** (comment)
  > --- A change reaches the calculation, it does not switch a canned answer ---

## `tests/test_economics.py`

- **tests/test_economics.py:1** (docstring `<module>`)
  > Costs counted once, and a severity index that never becomes a claim about equipment life.

## `tests/test_expert_grid.py`

- **tests/test_expert_grid.py:1** (docstring `<module>`)
  > The grid an expert turns: a refusal is an answer, a traceback is a defect.

## `tests/test_explain.py`

- **tests/test_explain.py:30** (comment)
  > --- A statement cannot drift from the number it talks about ---

## `tests/test_gate.py`

- **tests/test_gate.py:1** (docstring `<module>`)
  > The gate: every point checked, unknown blocks, and profit never buys a pass.

- **tests/test_gate.py:55** (comment)
  > --- A plan safe only at the end does not pass ---

- **tests/test_gate.py:120** (comment)
  > --- Hard limits cannot be bought ---

- **tests/test_gate.py:123** (docstring `test_a_profitable_plan_breaking_the_sulfur_limit_still_fails`)
  > Economics are not an input here at all: the gate cannot be argued with.

## `tests/test_integration.py`

- **tests/test_integration.py:1** (docstring `<module>`)
  > End-to-end checks: the requirements of T02 and the error chains that must not be bypassable.
  > Each test here goes through the real components rather than a stub, because the defects worth catching are the ones that appear only when the parts are wired together.

## `tests/test_inventory.py`

- **tests/test_inventory.py:45** (comment)
  > --- Mass is conserved and never spent twice ---

- **tests/test_inventory.py:234** (comment)
  > --- The end of the horizon is not the end of the plant ---

- **tests/test_inventory.py:291** (comment)
  > --- An on-demand component cannot be consumed before it can be produced (A3) ---

## `tests/test_live.py`

- **tests/test_live.py:152** (comment)
  > Only 285 t of inflow enter a 4000 t stock over three hours: the change must reach the blend, but cannot instantly replace its initial quality.

- **tests/test_live.py:363** (comment)
  > --- A frozen analyser does not lower the risk (T52) ---

## `tests/test_offspec.py`

- **tests/test_offspec.py:1** (docstring `<module>`)
  > Cost of off-spec (organisers, 18.09): reported in the decision, never deciding admissibility.

## `tests/test_optimizer.py`

- **tests/test_optimizer.py:1** (docstring `<module>`)
  > Candidate search and ranking: reproducible, gate-first, and never disturbing a good regime.

- **tests/test_optimizer.py:73** (comment)
  > --- Infeasible candidates can never win ---

- **tests/test_optimizer.py:159** (docstring `test_the_whole_recipe_range_is_covered_not_only_its_start`)
  > A truncated nested loop would silently drop every high reserve fraction.

## `tests/test_planner.py`

- **tests/test_planner.py:108** (docstring `test_a_confirmed_correction_changes_what_the_planner_still_needs_to_do`)
  > After a correction is confirmed, the advisor must account for it rather than repeat it.

- **tests/test_planner.py:257** (docstring `test_a_preparation_time_past_the_horizon_drops_the_component_where_a_blend_remains`)
  > A component that cannot exist within the horizon is removed, never merely scheduled late.
  > A recipe made of nothing but that component has no remainder to scale up, so it is left as it stands and rejected by the gate rather than rewritten into a different blend.

## `tests/test_process_avt.py`

- **tests/test_process_avt.py:1** (docstring `<module>`)
  > The AVT stage: a declared scenario response, never presented as measured plant behaviour.

- **tests/test_process_avt.py:173** (comment)
  > --- The action model is not the forecast ---

## `tests/test_process_ht.py`

- **tests/test_process_ht.py:1** (docstring `<module>`)
  > Hydrotreating response: delayed, non-retroactive, and never double counted.

- **tests/test_process_ht.py:86** (comment)
  > --- Delay: an action cannot act before its lag has elapsed ---

## `tests/test_response_guard.py`

- **tests/test_response_guard.py:1** (docstring `<module>`)
  > Ход температуры ГО допускается только если проходит Gate и при слабом крае β (weak_strong[0]).

## `tests/test_risk.py`

- **tests/test_risk.py:27** (comment)
  > One false alarm is allowed mathematically, but the tied 0.9 group cannot be split, so both tied negatives must stay below threshold.

## `tests/test_selection.py`

- **tests/test_selection.py:46** (docstring `test_large_but_noisy_gain_still_keeps_the_baseline`)
  > A gain that a paired bootstrap cannot separate from zero is not a gain.

## `tests/test_source_rules.py`

- **tests/test_source_rules.py:1** (docstring `<module>`)
  > Stub values and source-trust thresholds: removed and derived from history, not hand-set.

## `tests/test_time_alignment.py`

- **tests/test_time_alignment.py:49** (docstring `test_history_window_is_a_separate_quantity_from_the_horizon`)
  > The 6-hour feature window is backward-looking history, not a 6-hour forecast.

- **tests/test_time_alignment.py:121** (docstring `test_pak_and_lab_keep_independent_time_axes`)
  > The two sources are joined by time, never by row number.

## `tests/test_trust.py`

- **tests/test_trust.py:112** (comment)
  > --- A source never passes silently ---

- **tests/test_trust.py:126** (comment)
  > --- 307 is a confirmed polling stub; negatives are suspected, not deleted ---

---

Всего сохранено фрагментов: 187 в 75 файлах.

## Отдельно: два фрагмента, на которые прямо ссылается TODO.md (A0b, A2b-2, A2b-5)

Это главный материал защиты: дефекты, которые мы нашли и назвали сами, до жюри.

- **`src/neftecode/application/use_cases/make_decision.py:573`** (комментарий, коммит `8b4e8e3`)
  > A projection that stopped because a stock ran out does not prove the plan holds.

  Контекст на `8b4e8e3` — выбор запасного плана в `_look_ahead`: проекция бралась как
  первое не-`None` из `hours_to_violation` / `stock_ends_at_hours`, то есть исчерпание
  запаса компонента засчитывалось наравне с отсутствием нарушения качества.
  В рабочем дереве на 18.09 этот участок уже переписан: `stock_ends_at_hours`
  даёт `reach = 0.0`, то есть план с кончившимся запасом больше не выигрывает
  упреждение. Комментарий исчез вместе с дефектом, но сам факт «нашли и исправили»
  сохраняем здесь.

- **`src/neftecode/application/use_cases/make_decision.py:530-533`** (докстринг `_forbidden`)
  > Apply the accumulated restrictions to the candidate before it is evaluated.
  > The restriction is computed per tank, not against one global ceiling: a veto saying
  > "the draw is too big" must remove exactly the candidates that draw too much, otherwise
  > the next round would examine the same set and the loop would be theatre.

  Признание, что цикл «предложение — вето» без корректного сужения поиска был бы
  имитацией работы: вето обязано менять следующий перебор, а не просто попадать в трассу.
