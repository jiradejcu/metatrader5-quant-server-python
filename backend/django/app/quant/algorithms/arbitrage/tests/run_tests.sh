#!/usr/bin/env bash
# Run from repo root. All commands execute inside the django container.

CONTAINER="django"
WORKDIR="/app"
BASE="app/quant/algorithms/arbitrage/tests"
SIM_ENV="-e PAIR_INDEX=1"

# ---------------------------------------------------------------------------
# Unit / automated tests
# ---------------------------------------------------------------------------

# # Run all grid bot tests
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_grid_bot.py -v

# Run with log output visible
docker exec -w $WORKDIR $CONTAINER \
  python -m pytest $BASE/test_grid_bot.py -v -s --log-cli-level=INFO

# # Run a single test class
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_grid_bot.py::TestProcessTick -v

# # Run a single test case
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_grid_bot.py::TestProcessTick::test_sell_zone_places_new_order -v

# ---------------------------------------------------------------------------
# Simulation — named scenarios (isolated sim: channels, safe with live bot)
# ---------------------------------------------------------------------------

# sell_accumulate: SELL zone fills one order at a time until max_position_size
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario sell_accumulate --max-pos 3 --interval 0.8

# complete: no-fill chase → partial fill → full fill → SELL/BUY zones
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario complete --interval 0.8

# neutral_cancel: open order cancelled immediately when zone returns to NEUTRAL
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario neutral_cancel --interval 0.8

# delayed_price_diff: stale ticks (slow Binance API) are dropped; fresh ticks pass through
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario delayed_price_diff --interval 1.5

# ---------------------------------------------------------------------------
# Simulation — manual tick injection
# ---------------------------------------------------------------------------

# # Inject 5 sell-zone ticks, 1s apart
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --upper-diff 6.0 --lower-diff -2.0 --count 5 --interval 1.0

# # Inject buy-zone ticks with custom market price
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --upper-diff 2.0 --lower-diff -6.0 --bid 3300.0 --ask 3301.0 --count 3

# ---------------------------------------------------------------------------
# Replay — drive the REAL grid bot with recorded ticks from a log, then diff
# the result against the original run with plots.py. PAIR_INDEX auto-detected.
# Fully offline (in-process pub/sub, mocked fills) — safe with the live bot.
# ---------------------------------------------------------------------------

# Baseline: replay a recorded log. The default output name embeds the input
# log's name + ATR params, e.g.
#   replay_quant.log.2026-07-01.123000_to_124500_atrP2-D7-t0.3.log
LOG=/app/logs/quant.log.2026-07-01.123000_to_124500.log
docker exec -w $WORKDIR $CONTAINER \
  python $BASE/replay_bot.py $LOG --quiet

# Change a param (env for ATR_*, or edit grid_bot.py logic) and replay again —
# the ATR tag in the auto-name keeps this variant in its own file (…_t0.4.log)
docker exec -w $WORKDIR -e ATR_HIGH_THRESHOLD=0.4 $CONTAINER \
  python $BASE/replay_bot.py $LOG --quiet

# Chart both and compare (same X-axis / timeline → overlay 1:1). Each replay log
# yields atr_<its-name>.png, so the source log + params are visible in the PNG.
STEM=quant.log.2026-07-01.123000_to_124500
docker exec -w $WORKDIR $CONTAINER bash -c "cd app/utils \
    && python plots.py --atr /app/logs/replay_${STEM}_atrP2-D7-t0.3.log \
    && python plots.py --atr /app/logs/replay_${STEM}_atrP2-D7-t0.4.log"

# ---------------------------------------------------------------------------
# Simulation — live channels  ⚠️  only when live bot is stopped
# ---------------------------------------------------------------------------

# docker exec -w $WORKDIR -e PAIR_INDEX=1 $CONTAINER \
#   python $BASE/simulate_bot.py --live-channels --scenario sell_accumulate --max-pos 3 --interval 1.0
