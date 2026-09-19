# Option-Hedge Bot — Sequence Diagram

Flow for a bot that opens an MT5 market position on an incoming signal, hedges it
with a YLG fixed-time option, streams live PnL to the frontend, and closes out
either on manual command, on a configured loss limit, or on option expiry via an
internally tracked stop loss.

```mermaid
sequenceDiagram
    autonumber
    actor Signal as Signal Source
    participant Bot as Bot Engine
    participant YLG as YLG API
    participant MT5 as MT5 API
    participant FE as Frontend

    Signal->>Bot: POST /signal (buy | sell)
    activate Bot

    Bot->>YLG: loadmp(direction = opposite(signal), duration = X seconds)
    activate YLG
    YLG-->>Bot: price confirmed & option opened (option price, expiry = now + X s)
    deactivate YLG

    Bot->>MT5: send market order (signal direction)
    activate MT5
    MT5-->>Bot: position opened (entry price)
    deactivate MT5

    Bot->>Bot: start tick loop (position price, option price, price diff)

    loop every tick until closed/expired
        Bot->>MT5: get current position price
        MT5-->>Bot: position price
        Bot->>Bot: compute price diff (position price vs. option price from loadmp)
        Bot->>FE: push tick (position price, option price, price diff)

        alt user closes position
            FE->>Bot: close position command
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>YLG: cancel/leave option (per policy)
            Bot->>FE: closed (manual)
        else user executes option
            FE->>Bot: execute option command
            Bot->>YLG: confirm open order (execute option)
            YLG-->>Bot: option executed (payout)
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>FE: closed (option executed)
        else MT5 price reaches loss limit
            Bot->>Bot: detect loss limit breach (config threshold)
            Bot->>YLG: confirm open order (auto-execute option)
            YLG-->>Bot: option executed (payout)
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>FE: closed (auto: loss limit)
        else option expires (X seconds elapsed, no action taken)
            Bot->>Bot: option expired
            Bot->>Bot: compute & store internal stop loss price
            Note right of Bot: stop loss is tracked internally only,<br/>not sent to MT5 as an order
            loop until stop loss hit
                Bot->>MT5: get current position price
                MT5-->>Bot: position price
                Bot->>FE: push tick (position price, option price from loadmp, price diff)
            end
            Bot->>Bot: position price reaches internal stop loss
            Bot->>MT5: close position
            MT5-->>Bot: position closed
            Bot->>FE: close position command (stop loss hit)
        end
    end

    deactivate Bot
```

## Notes

- **loadmp** is called against the *opposite* direction of the incoming signal
  with a fixed duration (`X` seconds). A successful `loadmp` call *is* the
  fixed-time option being opened — there is no separate "open option" step;
  price confirmation and the hedge going live happen in the same call, and
  must complete before the bot fires the MT5 market order.
- The YLG option runs for that fixed duration (`X` seconds) in the opposite
  direction of the MT5 position, acting as a hedge.
- Every tick, the bot pushes three values to the frontend: position price,
  option price, and the diff between them. The option price is never
  re-fetched — it's held from the original `loadmp` response and stays fixed
  for the life of the option (including after expiry).
- Three ways out of a live position/option pair:
  1. **Manual close** — user sends a close position command.
  2. **Manual/auto option execution** — user confirms opening the order at
     YLG (execute option), or the bot does this automatically when the MT5
     price breaches the configured loss limit.
  3. **Option expiry** — if the option expires untouched, the bot computes an
     internal-only stop loss price (never submitted to MT5) and keeps
     streaming ticks until price reaches it, at which point it sends the
     close position command itself.
