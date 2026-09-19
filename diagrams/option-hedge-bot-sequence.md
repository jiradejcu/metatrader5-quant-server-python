# Option-Hedge Bot — Sequence Diagram

Flow for a bot that opens an MT5 market position on a signal from the frontend
— but only once the current MT5 price is confirmed favorable against the YLG
option price — opens a YLG fixed-time option as a standing offer against it,
and streams live PnL back to the frontend while **EXPOSED** (only the MT5 leg
live, the YLG option still just a reserved quote from `loadmp`).

Getting hedged isn't a state the bot sits in — it's a restart trigger. The
moment the option order is *confirmed* at YLG (manual execute, an auto
loss-limit breach, or an auto near-expiry-while-losing save), the bot treats
that as done and immediately restarts the whole sequence with the
**opposite** direction as the new signal. The only real exits are while
**EXPOSED**: a manual close, or the internal stop loss firing after a quote
expires unused.

```mermaid
sequenceDiagram
    autonumber
    actor FE as Frontend
    participant Bot as Bot Engine
    participant YLG as YLG API
    participant MT5 as MT5 API

    FE->>Bot: POST /signal (buy | sell)
    activate Bot

    loop each direction cycle
        Bot->>YLG: loadmp(direction = opposite(direction), duration = X seconds)
        activate YLG
        YLG-->>Bot: price confirmed (option quote reserved, expiry = now + X s)
        deactivate YLG

        Bot->>MT5: get current price (direction)
        activate MT5
        MT5-->>Bot: current price
        deactivate MT5

        alt price is on our side (buy: MT5 price cheaper than option;<br/>sell: MT5 price higher than option)
            Bot->>MT5: send market order (direction)
            activate MT5
            MT5-->>Bot: position opened (entry price)
            deactivate MT5

            Note over Bot: State = EXPOSED — MT5 position live,<br/>YLG side is only a reserved quote

            loop every tick while EXPOSED
                Bot->>MT5: get current position price
                MT5-->>Bot: position price
                Bot->>Bot: compute price diff (position price vs. option price from loadmp)
                Bot->>FE: push tick (position price, option price, price diff)

                alt user closes position
                    FE->>Bot: close position command
                    Bot->>MT5: close position
                    MT5-->>Bot: position closed
                    Bot->>YLG: let quote lapse (never executed)
                    Bot->>FE: closed (manual, exposure only)
                    Note over Bot: done — no restart
                else user executes option (only before quote expiry)
                    FE->>Bot: execute option command
                    Bot->>YLG: confirm open order (execute option)
                    YLG-->>Bot: option order confirmed
                    Note over Bot: hedged -> restart with opposite direction
                else MT5 price reaches loss limit (only before quote expiry)
                    Bot->>Bot: detect loss limit breach (config threshold)
                    Bot->>YLG: confirm open order (auto-execute option)
                    YLG-->>Bot: option order confirmed
                    Note over Bot: hedged -> restart with opposite direction
                else quote nearing expiry AND MT5 position is at a loss
                    Bot->>Bot: detect near-expiry window + unrealized loss
                    Bot->>YLG: confirm open order (auto-execute option)
                    YLG-->>Bot: option order confirmed
                    Note over Bot: hedged -> restart with opposite direction
                else quote expires (X seconds elapsed, never executed) — one-time
                    Bot->>Bot: compute & store internal stop loss price
                    Note right of Bot: only reached if position was flat/in profit<br/>at expiry. Stop loss is tracked internally only,<br/>not sent to MT5 as an order. Execute/loss-limit<br/>branches above no longer apply.
                else internal stop loss hit (only after quote expiry)
                    Bot->>MT5: close position
                    MT5-->>Bot: position closed
                    Bot->>FE: close position command (stop loss hit, exposure only)
                    Note over Bot: done — no restart
                end
            end
        else price not on our side
            Bot->>YLG: let quote lapse (never executed)
            Bot->>FE: error (MT5 price not favorable vs. option price)
            Note over Bot: done — no restart, no order sent
        end

        Bot->>Bot: direction = opposite(direction)
    end

    deactivate Bot
```

## Notes

- **loadmp** is called against the *opposite* direction of the current
  signal with a fixed duration (`X` seconds). A successful `loadmp` call
  opens the fixed-time option as a **reserved quote** — price locked, clock
  running — but that alone is not a matched trade against YLG, so it does
  not create a hedge by itself.
- **Pre-trade price check**: before sending the MT5 market order, the bot
  fetches the current MT5 price and compares it to the YLG option price. The
  order only goes out if price is on our side — for a **buy**, MT5 price
  must be *cheaper* than the option price; for a **sell**, MT5 price must be
  *higher* than the option price (mirror condition). If it isn't, the bot
  never sends the order — it just returns an error and lets the quote lapse.
- **State = EXPOSED**: right after the MT5 order fills, only the MT5 side is
  a live risk position. Every tick, the bot pushes three values to the
  frontend: position price, option price, and the diff between them. The
  option price is never re-fetched — it's held from the original `loadmp`
  response for the life of the option.
- **Getting hedged is a restart trigger, not a managed state.** The moment
  the option order is confirmed at YLG — manual execute, auto on loss-limit
  breach, or auto on near-expiry-while-losing — the bot doesn't track or
  unwind a hedged position at all. It flips the direction and immediately
  starts the whole sequence over: a fresh `loadmp`, a fresh MT5 market
  order, a fresh EXPOSED tick loop.
- **Expiry is a one-time transition within the EXPOSED loop.** If the
  position is still flat or in profit as the quote nears expiry, it's
  allowed to lapse unused; the bot computes an internal stop loss and stays
  in the same loop — the execute/loss-limit branches stop applying, and an
  internal-stop-loss-hit branch becomes reachable instead. If instead the
  position is at a loss as the quote nears expiry, the bot auto-executes the
  option before it can lapse, which triggers the same restart.
- **Only two real exits, both from EXPOSED**: a manual close command, or the
  internal stop loss firing after a quote expires unused. Either way, only
  the MT5 leg ever needed closing — there's no YLG position to unwind.
