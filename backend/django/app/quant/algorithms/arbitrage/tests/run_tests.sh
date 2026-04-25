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
  python -m pytest $BASE/test_grid_bot.py -v -s

# # Run a single test class
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_grid_bot.py::TestProcessTick -v

# # Run a single test case
# docker exec -w $WORKDIR $CONTAINER \
#   python -m pytest $BASE/test_grid_bot.py::TestProcessTick::test_sell_zone_places_new_order -v

# ---------------------------------------------------------------------------
# Simulation — named scenarios (isolated sim: channels, safe with live bot)
# ---------------------------------------------------------------------------

# # Sell zone: upper_diff breaches limit → expects new SELL order
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --scenario sell_zone --interval 0.8

# # Buy zone: lower_diff breaches limit → expects new BUY order
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --scenario buy_zone --interval 0.8

# Complete: no-fill chase → partial fill → full fill → SELL/BUY zone with hedges
docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
  python $BASE/simulate_bot.py --scenario complete --interval 0.8

# # Capacity exceeded: position at max → expects cancel instead of new order
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --scenario capacity_exceeded --position 5.0 --max-pos 5.0 --interval 0.8

# # ---------------------------------------------------------------------------
# # Simulation — manual tick injection
# # ---------------------------------------------------------------------------

# # Inject 5 sell-zone ticks, 1s apart
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --upper-diff 6.0 --lower-diff -2.0 --count 5 --interval 1.0

# # Inject buy-zone ticks with custom market price
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --upper-diff 2.0 --lower-diff -6.0 --bid 3300.0 --ask 3301.0 --count 3

# # Fractional position scenario
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --upper-diff 2.0 --lower-diff 0.0 --position 0.5 --count 3

# # Repeat a scenario multiple times
# docker exec -w $WORKDIR $SIM_ENV $CONTAINER \
#   python $BASE/simulate_bot.py --scenario sweep --repeat 3 --interval 0.5

# ---------------------------------------------------------------------------
# Simulation — live channels  ⚠️  only when live bot is stopped
# ---------------------------------------------------------------------------

# docker exec -w $WORKDIR -e PAIR_INDEX=1 $CONTAINER \
#   python $BASE/simulate_bot.py --live-channels --scenario sell_zone --interval 1.0
