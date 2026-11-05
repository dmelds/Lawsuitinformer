#!/usr/bin/env python3
"""Switch light and dark mode by time of day on every page.

Until 11/5/26 a visitor with no saved choice got whatever their device's
light/dark setting said (FOLLOW_OS in LI-DARK-INIT, and a prefers-color-scheme
listener in LI-DARK-JS). This sweep makes the site follow the visitor's own
clock instead: dark from 7 pm to 7 am, light the rest of the day.

  * LI-DARK-INIT picks the theme before first paint from the hour on the
    visitor's device. A saved toggle choice (localStorage li-theme) and the
    ?theme= handoff from lawsuit.center still win, exactly as before.
  * LI-DARK-JS replaces the OS listener with followClock(): it repaints at the
    next 7 pm or 7 am while the page is open and rechecks when the tab comes
    back into view. It does nothing once the visitor has clicked the toggle.

The hours live in DARK_FROM / DARK_UNTIL, written once in each block. Change
both pairs together.

Dry run by default; --apply writes. Idempotent: a page that already carries
followClock is left alone, so a rerun reports zero files patched. A page whose
dark block differs from the expected text is reported and makes the run exit 1.
The anchor add_cta_events.py relies on (the lone decorate() call in LI-DARK-JS)
is untouched.
"""
import argparse
import io
from pathlib import Path

GUARD = "function followClock()"
OLD_INIT_FALLBACK = """  if (t !== 'dark' && t !== 'light') {
    t = (FOLLOW_OS && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }"""
NEW_INIT_FALLBACK = """  if (t !== 'dark' && t !== 'light') {
    /* No saved choice: follow the visitor's own clock. Dark from DARK_FROM to
       DARK_UNTIL (24-hour, device local time). LI-DARK-JS keeps it in step. */
    var DARK_FROM = 19, DARK_UNTIL = 7, h = new Date().getHours();
    t = (h >= DARK_FROM || h < DARK_UNTIL) ? 'dark' : 'light';
  }"""
OLD_FLAG = "  var FOLLOW_OS = true; /* set false to default light unless visitor toggles */\n"
OLD_LISTEN = """  if (window.matchMedia) {
    var mq = matchMedia('(prefers-color-scheme: dark)');
    var onChange = function (e) {
      var stored = null;
      try { stored = localStorage.getItem('li-theme'); } catch (err) {}
      if (stored !== 'dark' && stored !== 'light') paint(e.matches ? 'dark' : 'light');
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }"""
NEW_LISTEN = """  /* Time-of-day theme: with no saved choice, switch at 7 pm and 7 am on the
     visitor's clock while the page is open, and recheck when the tab comes
     back. Keep DARK_FROM / DARK_UNTIL in step with LI-DARK-INIT. */
  var DARK_FROM = 19, DARK_UNTIL = 7, clockTimer = null;
  function saved() {
    var s = null;
    try { s = localStorage.getItem('li-theme'); } catch (err) {}
    return (s === 'dark' || s === 'light') ? s : null;
  }
  function byClock() {
    var h = new Date().getHours();
    return (h >= DARK_FROM || h < DARK_UNTIL) ? 'dark' : 'light';
  }
  function followClock() {
    clearTimeout(clockTimer);
    if (saved()) return;
    if (current() !== byClock()) paint(byClock());
    var now = new Date(), next = new Date(now);
    next.setHours(byClock() === 'dark' ? DARK_UNTIL : DARK_FROM, 0, 5, 0);
    if (next <= now) next.setDate(next.getDate() + 1);
    clockTimer = setTimeout(followClock, Math.min(next - now, 3600000));
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) followClock();
  });
  followClock();"""

PAIRS = ((OLD_FLAG, ""), (OLD_INIT_FALLBACK, NEW_INIT_FALLBACK), (OLD_LISTEN, NEW_LISTEN))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    patched, present, problems = [], [], []
    for path in sorted(Path(args.path).rglob("*.html")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        html = io.open(path, encoding="utf-8").read()
        if "LI-DARK-INIT:BEGIN" not in html:
            continue
        if GUARD in html:
            present.append(str(path))
            continue
        if any(html.count(old) != 1 for old, _ in PAIRS):
            problems.append(str(path))
            continue
        for old, new in PAIRS:
            html = html.replace(old, new, 1)
        patched.append(str(path))
        if args.apply:
            io.open(path, "w", encoding="utf-8").write(html)

    mode = "APPLIED" if args.apply else "DRY RUN (no files written)"
    print(f"time-of-day theme sweep - {mode}")
    print(f"  {len(patched)} files patched, {len(present)} already followed the clock")
    print(f"  {len(problems)} files could not be patched")
    for p in problems:
        print(f"    {p}  [SKIPPED - dark block differs from the expected text]")
    if not args.apply:
        for p in patched[:20]:
            print(f"    + {p}")
        if len(patched) > 20:
            print(f"    ... and {len(patched) - 20} more")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
