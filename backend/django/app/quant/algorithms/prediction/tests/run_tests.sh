#!/usr/bin/env bash
# Run from repo root. All commands execute inside the django container.

CONTAINER="django"
WORKDIR="/app"
BASE="app/quant/algorithms/prediction/tests"
SIM_ENV="-e PAIR_INDEX=1"

# ---------------------------------------------------------------------------
# Unit / automated tests
# ---------------------------------------------------------------------------

# # Run all prediction bot tests
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_prediction_bot.py -v

# Run with log output visible
docker exec -w $WORKDIR $CONTAINER \
  python -m pytest $BASE/test_prediction_bot.py -v -s --log-cli-level=INFO

# # Run a single test class
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_prediction_bot.py::TestProcessTick -v

# # Run a single test case
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_prediction_bot.py::TestProcessTick::test_passive_close_on_target_met -v

# ---------------------------------------------------------------------------
# Simulation — named scenarios (isolated sim: settings channel, safe with live bot)
# ---------------------------------------------------------------------------

# neutral_hold: profit below target → bot does nothing
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario neutral_hold --profit-target 10 --interval 2.5

# passive_close: profit target met → passive best-ask SELL, fills next tick
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario passive_close --profit-target 10 --aggressiveness passive --interval 2.5

# aggressive_close_slippage_capped: thin book → close clipped across ticks by max_slippage_usd
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario aggressive_close_slippage_capped \
    --profit-target 5 --max-slippage 3 --aggressiveness aggressive --position 5 --interval 2.5

# reentry_after_close: price gives back the run-up to within reentry_tolerance_usd → bot buys back
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario reentry_after_close \
    --profit-target 10 --reentry-tolerance 3 --interval 2.5

# cancel_on_target_lost: resting close order cancelled when price drops back below target
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario cancel_on_target_lost --profit-target 10 --interval 2.5

# ---------------------------------------------------------------------------
# Simulation — manual tick injection
# ---------------------------------------------------------------------------

# # Inject 5 ticks stepping bid/ask up by 1.0 each, starting from an open long
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --position 2 --entry-price 1000 --bid 1000 --ask 1001 \
#     --bid-step 1.0 --ask-step 1.0 --count 5 --interval 2.5

# # Inject ticks stepping price down, to test reentry behavior manually
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --position 0 --entry-price 1000 --bid 1012 --ask 1013 \
#     --bid-step -1.0 --ask-step -1.0 --count 8 --interval 2.5 --reentry-tolerance 3

# ---------------------------------------------------------------------------
# Simulation — live settings channel  ⚠️  writes the real prediction settings key
# ---------------------------------------------------------------------------

# docker exec -w $WORKDIR -e PAIR_INDEX=1 $CONTAINER \
#   python $BASE/simulate_bot.py --live-channels --scenario passive_close --profit-target 10 --interval 2.5
