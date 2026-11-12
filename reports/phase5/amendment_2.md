# Amendment 2: Parts C–E, before execution

User-authorized 2026-11-12. Frozen Phase 4 decision code remains unchanged.

L3 ingestion uses recorded DEV spans from the first 20 manifest occurrences as
synthetic traffic with fresh trace/span IDs. The existing collector, Kafka,
assembler and classifier containers are measured, with classification results
consumed by a measurement-only Postgres sink. Existing classifier rule/learned
detectors are used as deployed; these are distinct from the Phase 4 offline
detector pipeline used in heal decisions. Neither is modified. Critic/healer
consumers stay stopped to prevent API spend/notifications and synthetic alerts
from initiating repairs. Their alert offsets will be advanced past this test's
synthetic traffic before restoration, with the exact offset change recorded.
Post-test deviation: automatic approval review rejected that offset mutation
because it could skip alerts for a future consumer. No offsets were changed;
critic/healer remain stopped instead. The requested measurements continue with
all paid requests confined to their capped experiment controllers.

Hold offered rates 1, 5, 20, 80, 320, 1280 events/s for at least 180 seconds
each, stopping after the first saturated step. Warm up with one full 20-trace
pass and drain before measurement. Preserve full traces and their terminal
signals; batch requests may cause within-trace bursts. Events/s means spans/s;
report traces/s separately. Poll Kafka committed consumer lag every 10 seconds.
Evaluate lag growth using the final 120 seconds (to exclude initial transients):
OLS slope > max(0.1 events/s, 1% offered rate) or end lag exceeding start lag by
max(10 events, 2% of offered events) is growing. Also require accepted >=98% of
offered target, no HTTP/sink errors, and completion without missing traces.
The maximum sustained rate is the highest tested step satisfying those checks,
not an interpolated capacity. End-to-end detection latency is measured from
first HTTP submission for each trace until classification is committed to
Postgres, including queueing, assembly, detection and sink. Record missing or
late detections and drain after each step; do not omit censored traces.

The existing classifier publishes classifications to Kafka but does not write
them to Postgres. The added sink is explicit measurement plumbing, not a claim
that a native production classification-to-Postgres writer already exists.
Report host/Docker specs, resource samples and both assembler/classifier lag.

L3 heal concurrency changes the original 20-occurrence, levels 1/2/4/8 plan:
draw 10 distinct manifest occurrence IDs without replacement using Python
random.Random(2026111203), preserve draw order, execute concurrency 1 then 4.
Keep identical selected tasks, frozen pipeline/model/temperature, fresh local
caches per heal, existing no-patch reference reuse. Every actual HTTP attempt
reserves against a shared $1.50 DeepSeek usage-priced provider cap, including
in-flight and unknown attempts. No replacement for failures/cap stops. Report
all/full-gate denominators and wall-clock throughput, with order/cache/provider
drift confounds. No warm-up paid heals. Raw data stays ignored.

Gemini is a separate 20-occurrence side row, manifest order, at concurrency 2
matching last night's baseline. Prefer the preregistered gemini-3.5-flash-lite
if models.list confirms availability. Use exact frozen prompts, system text,
temperature 0.2 and 800 maximum output tokens. Adapt only provider transport:
DeepSeek forced strict function call becomes Gemini application/json with the
same JSON schema in responseJsonSchema; return JSON text to unchanged local
validation. Disable thinking with thinkingLevel=minimal (as supported for
Flash-Lite) to match the non-thinking baseline; document the wire config.
Minimal thinking is the nearest supported setting, not a guarantee of zero
thinking tokens; count any reported thinking toward the cap. No extra repair
prompts/format retries outside frozen validation. Gates remain
DeepSeek, with a separate shared $0.75 usage-priced provider cap. Gemini uses a
separate $2.00 cap including thinking/output and unknown reservations. A full
cap stop may leave the requested side row incomplete: report all 20 slots,
never extrapolate. API usage-priced costs are not invoice reconciliation.

Part E collects the entire test suite with -p no:deepeval. Existing explicit
sealed-TEST guards apply; report any TEST-dependent skips transparently rather
than reading sealed artifacts. No directory/test subset selection is allowed.
Write aggregate results, regenerate RESULTS.md, secret-scan explicit staging,
push normally and open (do not merge) a phase-5-perf -> main PR.

## User-requested L3 add-on (no API spend)

Run all offered-rate steps 30, 40 and 60 events/s, in that order, for at least
180 seconds each. Keep the original warm-up, final-120-second consumer-lag
thresholds, acceptance/error and complete-persistence criteria unchanged.
Drain between steps; continue through all three even if one saturates. Keep
paid critic/healer consumers stopped, with no Kafka offset changes. Retain the
initial and add-on experiments as separate JSON sources; their combined summary
reports the highest passing measured rate without interpolation. Check frozen
logic before/after and compare durable API-ledger fingerprints to verify zero
new provider attempts/spend. Inspect only source code to confirm Phase 4 used
the offline detectors; never reload sealed data for this confirmation.
