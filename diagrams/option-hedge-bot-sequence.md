# Option-Hedge Bot — Sequence Diagram

Flow for a bot that opens an MT5 market position on a signal from the frontend,
opens a YLG fixed-time option as a standing offer against it, streams live PnL
back to the frontend, and closes out on manual command, on a configured loss
limit, or on option expiry via an internally tracked stop loss.

The bot moves through two states:

- **EXPOSED** — only the MT5 position is live. The YLG option opened by
  `loadmp` is a reserved quote with a locked price and a running clock, not
  yet a matched trade, so there is no hedge — closing here only touches MT5.
- **HEDGED** — the YLG option has been *executed* (confirmed as an order at
  YLG), so both the MT5 position and the YLG option are live, offsetting
  positions. Closing here must close **both legs at the same time**, at the
  moment/price that **minimizes YLG's profit** on the option leg.

```mermaid
sequenceDiagram
    autonumber
    actor FE as Frontend
    participant Bot as Bot Engine
    participant YLG as YLG API
    participant MT5 as MT5 API

    FE->>Bot: POST /signal (buy | sell)
    activate Bot

    Bot->>YLG: loadmp(direction = opposite(signal), duration = X seconds)
    activate YLG
    YLG-->>Bot: price confirmed (option quote reserved, expiry = now + X s)
    deactivate YLG

    Bot->>MT5: send market order (signal direction)
    activate MT5
    MT5-->>Bot: position opened (entry price)
    deactivate MT5

    Note over Bot: State = EXPOSED — MT5 position live,<br/>YLG side is only a reserved quote

    loop every tick while EXPOSED
        Bot->>MT5: get current position price
        MT5-->>Bot: position price
        Bot->>Bot: compute price diff (position price vs. option price from loadmp)
        Bot->>FE: push tick (position price, option price, price diff)

        alt user closes position (still exposed)
            FE->>Bot: close position command
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>YLG: let quote lapse (never executed)
            Bot->>FE: closed (manual, exposure only)
        else user executes option (only before quote expiry)
            FE->>Bot: execute option command
            Bot->>YLG: confirm open order (execute option)
            YLG-->>Bot: option order confirmed (hedge live)
            Note over Bot: State -> HEDGED
        else MT5 price reaches loss limit (only before quote expiry)
            Bot->>Bot: detect loss limit breach (config threshold)
            Bot->>YLG: confirm open order (auto-execute option)
            YLG-->>Bot: option order confirmed (hedge live)
            Note over Bot: State -> HEDGED (auto, to cap further exposure)
        else quote expires (X seconds elapsed, never executed) — one-time
            Bot->>Bot: compute & store internal stop loss price
            Note right of Bot: stop loss is tracked internally only,<br/>not sent to MT5 as an order.<br/>Execute/loss-limit branches above no longer apply.
        else internal stop loss hit (only after quote expiry)
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>FE: close position command (stop loss hit, exposure only)
        end
    end

    opt state reached HEDGED
        loop every tick while HEDGED
            Bot->>MT5: get current position price
            MT5-->>Bot: position price
            Bot->>Bot: compute price diff (position price vs. option price)
            Bot->>FE: push tick (position price, option price, price diff)

            alt user closes position (hedged)
                FE->>Bot: close position command
                Bot->>Bot: pick close moment/price that minimizes YLG profit
                par close both legs together
                    Bot->>MT5: close position
                    MT5-->>Bot: position closed
                and
                    Bot->>YLG: close/settle option
                    YLG-->>Bot: option settled (payout)
                end
                Bot->>FE: closed (both legs, YLG profit minimized)
            end
        end
    end

    deactivate Bot
```

## Notes

- **loadmp** is called against the *opposite* direction of the incoming
  signal with a fixed duration (`X` seconds). A successful `loadmp` call
  opens the fixed-time option as a **reserved quote** — price locked, clock
  running — but that alone is not a matched trade against YLG, so it does
  not create a hedge by itself.
- **State = EXPOSED**: right after the MT5 order fills, only the MT5 side is
  a live risk position. The bot is naked until the option is executed.
- **State = HEDGED**: only reached once the option order is *confirmed* at
  YLG — via a manual "execute option" command, or automatically when the MT5
  loss limit is breached. From this point, MT5 position and YLG option are
  both live, offsetting legs.
- Every tick, the bot pushes three values to the frontend: position price,
  option price, and the diff between them. The option price is never
  re-fetched — it's held from the original `loadmp` response and stays fixed
  for the life of the option (including after expiry).
- **Expiry is a one-time transition within EXPOSED, not a new loop.** Once the
  quote lapses unused, the bot computes an internal stop loss and keeps
  ticking in the same tick loop — the execute/loss-limit branches stop
  applying, and an internal-stop-loss-hit branch becomes reachable instead.
- **Closing differs by state**:
  - While **EXPOSED**, closing (manual command, or the internal stop loss
    firing after the quote expires unused) only touches the MT5 leg — there
    is no YLG position to unwind.
  - While **HEDGED**, closing always unwinds **both legs simultaneously**
    (MT5 position + YLG option), timed at the price/moment that **minimizes
    YLG's profit** on the option leg, since the two legs are now offsetting
    positions and must be torn down together to lock in the hedge's result.
