# log-color.awk — colorize structured Python log lines from docker compose
# Usage: docker compose logs -f | gawk -f log-color.awk
#
# Handles two log formats automatically:
#   docker compose:  service  | LEVEL DATE TIME module:func:lineno message...
#   log file:        LEVEL DATE TIME module:func:lineno PID:x THREADID message...
#
# Colors applied:
#   service name     → magenta
#   level (DEBUG…)   → per-level color
#   date             → cyan
#   time             → bright cyan
#   module path      → blue
#   function name    → bright blue
#   line number      → yellow
#   PID + thread     → dark gray (log file only)
#   [tag] in msg     → bold bright yellow
#   label=number     → white label, bright yellow number
#   label=WORD       → white label, bright cyan word
#   'dict_key':      → cyan
#   : number         → bright yellow

BEGIN {
    RST = "\033[0m"

    # level colors
    LC["DEBUG"]    = "\033[37m"     # white/light gray
    LC["INFO"]     = "\033[32m"     # green
    LC["WARNING"]  = "\033[33m"     # yellow
    LC["WARN"]     = "\033[33m"     # yellow
    LC["ERROR"]    = "\033[1;31m"   # bold red
    LC["CRITICAL"] = "\033[1;41m"   # red background

    # structural part colors
    C_SVC  = "\033[35m"    # magenta      — docker service name
    C_DATE = "\033[36m"    # cyan         — date
    C_TIME = "\033[96m"    # bright cyan  — time
    C_MOD  = "\033[34m"    # blue         — module path
    C_FUNC = "\033[94m"    # bright blue  — function name
    C_LINE = "\033[33m"    # yellow       — line number
    C_PID  = "\033[90m"    # dark gray    — PID + thread id
}

{
    # strip docker compose service prefix "service  | "
    prefix = ""
    rest   = $0
    pipe   = index($0, " | ")
    if (pipe > 0) {
        svc    = substr($0, 1, pipe - 1)
        rest   = substr($0, pipe + 3)
        prefix = C_SVC svc RST " | "
    }

    # parse fields: LEVEL DATE TIME module:func:line [PID:x THREADID] message...
    n = split(rest, p, " ")
    if (n < 4 || !(p[1] in LC)) { print prefix rest; next }

    lc = LC[p[1]]

    # split module:func:lineno on ":"
    nmod = split(p[4], mfl, ":")
    if (nmod == 3)
        loc = C_MOD mfl[1] RST ":" C_FUNC mfl[2] RST ":" C_LINE mfl[3] RST
    else
        loc = C_MOD p[4] RST

    # detect format: log file has "PID:xx" as field 5, docker compose goes straight to message
    pid_str = ""
    msg_start = 5
    if (p[5] ~ /^PID:/) {
        pid_str = C_PID p[5] " " p[6] RST "  "
        msg_start = 7
    }

    # rebuild message (avoid msg(...) function-call parse bug by using sep variable)
    msg = ""; sep = ""
    for (i = msg_start; i <= n; i++) { msg = msg sep p[i]; sep = " " }

    # colorize message parts (order matters — later passes won't re-match colored spans)
    # 1. [tags] in square brackets → bold bright yellow
    msg = gensub(/\[([^\]]+)\]/, "\033[1;93m[\\1]\033[0m", "g", msg)
    # 2. label=number → white label, bright yellow number
    msg = gensub(/([a-zA-Z_][a-zA-Z0-9_]*)=(-?[0-9][0-9.]*)/, "\033[37m\\1\033[0m=\033[93m\\2\033[0m", "g", msg)
    # 3. label=WORD → white label, bright cyan value (ALLCAPS, or Python True/False/None)
    msg = gensub(/([a-zA-Z_][a-zA-Z0-9_]*)=(True|False|None|[A-Z][A-Z0-9_]*)/, "\033[37m\\1\033[0m=\033[96m\\2\033[0m", "g", msg)
    # 4. 'dict_key': → cyan key
    msg = gensub(/'([^']+)':/, "\033[36m'\\1'\033[0m:", "g", msg)
    # 5. ": number" → bright yellow number (catches "Volume: 0", "Amount: -4.00")
    msg = gensub(/(:\s*)(-?[0-9]+\.?[0-9]*)/, "\\1\033[93m\\2\033[0m", "g", msg)

    printf "%s%s%-8s%s  %s%s%s %s%s%s  %s  %s%s\n",
        prefix,
        lc, p[1], RST,
        C_DATE, p[2], RST,
        C_TIME, p[3], RST,
        loc,
        pid_str,
        msg
}
