#!/usr/bin/env python3
"""asciineditor - An editor for asciicast v2 (.cast) files.

Provides split, join, cut, and speed operations on asciicast recordings.
Markers in .cast files (event type "m") can be used to define start/end points.
"""

import argparse
import json
import os
import sys


def read_cast(path):
    """Read an asciicast v2 file. Returns (header_dict, list_of_events)."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        print(f"Error: '{path}' is empty.", file=sys.stderr)
        sys.exit(1)
    header = json.loads(lines[0])
    if header.get("version") != 2:
        print(f"Error: '{path}' is not asciicast v2.", file=sys.stderr)
        sys.exit(1)
    events = []
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        events.append(json.loads(line))
    return header, events


def write_cast(path, header, events):
    """Write an asciicast v2 file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def resolve_position(events, spec):
    """Resolve a position specifier to a timestamp.

    spec can be:
      - A float/int literal interpreted as seconds (e.g. "5.0")
      - "marker:<label>" to find the first marker with that label
      - "marker:" or "marker" to find the first marker with any/empty label

    Returns the timestamp (float).
    """
    if spec.startswith("marker:"):
        label = spec[len("marker:"):]
        for ev in events:
            if ev[1] == "m" and ev[2] == label:
                return ev[0]
        print(f"Error: marker with label '{label}' not found.", file=sys.stderr)
        sys.exit(1)
    elif spec == "marker":
        for ev in events:
            if ev[1] == "m":
                return ev[0]
        print("Error: no marker found.", file=sys.stderr)
        sys.exit(1)
    else:
        try:
            return float(spec)
        except ValueError:
            print(f"Error: invalid position '{spec}'. Use a number (seconds) or 'marker:<label>'.",
                  file=sys.stderr)
            sys.exit(1)


def resolve_marker_pair(events, start_spec, end_spec):
    """Resolve start and end specifiers to timestamps.

    Each spec can be a timestamp or marker reference.
    Additionally, if start_spec or end_spec is just a bare marker label
    without the 'marker:' prefix, we try numeric first, then marker lookup.
    """
    start_ts = resolve_position(events, start_spec)
    end_ts = resolve_position(events, end_spec)
    if end_ts < start_ts:
        print(f"Error: end ({end_ts}s) is before start ({start_ts}s).", file=sys.stderr)
        sys.exit(1)
    return start_ts, end_ts


def update_duration(header, events):
    """Update the duration field in the header based on events."""
    if events:
        header["duration"] = events[-1][0]
    else:
        header["duration"] = 0.0
    return header


# ── SPLIT ────────────────────────────────────────────────────────────────────

def cmd_split(args):
    """Split a cast file at a given position into two files."""
    header, events = read_cast(args.file)
    split_ts = resolve_position(events, args.at)

    before = [ev for ev in events if ev[0] <= split_ts]
    after = [ev for ev in events if ev[0] > split_ts]

    # Rebase timestamps for the second part so it starts at 0
    if after:
        offset = after[0][0]
        after = [[ev[0] - offset, ev[1], ev[2]] for ev in after]

    base, ext = os.path.splitext(args.file)
    out1 = args.output1 or f"{base}_part1{ext}"
    out2 = args.output2 or f"{base}_part2{ext}"

    h1 = dict(header)
    h2 = dict(header)
    update_duration(h1, before)
    update_duration(h2, after)

    write_cast(out1, h1, before)
    write_cast(out2, h2, after)
    print(f"Split at {split_ts}s:")
    print(f"  Part 1: {out1} ({len(before)} events)")
    print(f"  Part 2: {out2} ({len(after)} events)")


# ── JOIN ─────────────────────────────────────────────────────────────────────

def cmd_join(args):
    """Join multiple cast files into one."""
    if len(args.files) < 2:
        print("Error: need at least 2 files to join.", file=sys.stderr)
        sys.exit(1)

    header, all_events = read_cast(args.files[0])
    gap = args.gap

    for path in args.files[1:]:
        h, events = read_cast(path)
        # Use the max terminal dimensions
        header["width"] = max(header.get("width", 0), h.get("width", 0))
        header["height"] = max(header.get("height", 0), h.get("height", 0))

        # Offset = end of previous + gap
        offset = (all_events[-1][0] if all_events else 0.0) + gap
        for ev in events:
            all_events.append([ev[0] + offset, ev[1], ev[2]])

    update_duration(header, all_events)
    out = args.output or "joined.cast"
    write_cast(out, header, all_events)
    print(f"Joined {len(args.files)} files into {out} ({len(all_events)} events)")


# ── CUT ──────────────────────────────────────────────────────────────────────

def cmd_cut(args):
    """Cut (remove) a section between start and end from a cast file."""
    header, events = read_cast(args.file)
    start_ts, end_ts = resolve_marker_pair(events, args.start, args.end)
    cut_duration = end_ts - start_ts

    result = []
    for ev in events:
        if start_ts <= ev[0] <= end_ts:
            # Skip events in the cut region (optionally keep markers)
            continue
        elif ev[0] > end_ts:
            # Shift subsequent events back by the cut duration
            result.append([ev[0] - cut_duration, ev[1], ev[2]])
        else:
            result.append(ev)

    update_duration(header, result)
    out = args.output or args.file
    write_cast(out, header, result)
    removed = len(events) - len(result)
    print(f"Cut {start_ts}s-{end_ts}s ({cut_duration:.3f}s removed, {removed} events dropped)")
    print(f"  Output: {out} ({len(result)} events)")


# ── SPEED ────────────────────────────────────────────────────────────────────

def cmd_speed(args):
    """Change playback speed of a section between start and end markers."""
    header, events = read_cast(args.file)
    start_ts, end_ts = resolve_marker_pair(events, args.start, args.end)
    factor = args.factor

    if factor <= 0:
        print("Error: speed factor must be positive.", file=sys.stderr)
        sys.exit(1)

    # The section [start_ts, end_ts] has original duration D.
    # After speed change, it becomes D / factor.
    # Events after the section shift by D - D/factor = D * (1 - 1/factor).
    section_duration = end_ts - start_ts
    new_section_duration = section_duration / factor
    time_shift = section_duration - new_section_duration  # positive if speeding up

    result = []
    for ev in events:
        if ev[0] < start_ts:
            result.append(ev)
        elif ev[0] <= end_ts:
            # Scale the position within the section
            pos_in_section = ev[0] - start_ts
            new_pos = pos_in_section / factor
            result.append([start_ts + new_pos, ev[1], ev[2]])
        else:
            # After section: shift by the time difference
            result.append([ev[0] - time_shift, ev[1], ev[2]])

    update_duration(header, result)
    out = args.output or args.file
    write_cast(out, header, result)
    print(f"Speed {factor}x applied to {start_ts}s-{end_ts}s")
    print(f"  Section: {section_duration:.3f}s -> {new_section_duration:.3f}s")
    print(f"  Output: {out} ({len(result)} events)")


# ── REMOVE MARKER ────────────────────────────────────────────────────────────

def cmd_remove_marker(args):
    """Remove marker events from a cast file."""
    header, events = read_cast(args.file)

    if args.label is not None:
        result = [ev for ev in events if not (ev[1] == "m" and ev[2] == args.label)]
    elif args.at is not None:
        ts = float(args.at)
        result = [ev for ev in events if not (ev[1] == "m" and abs(ev[0] - ts) < 0.001)]
    elif args.all:
        result = [ev for ev in events if ev[1] != "m"]
    else:
        print("Error: specify --label, --at, or --all.", file=sys.stderr)
        sys.exit(1)

    removed = len(events) - len(result)
    if removed == 0:
        print("No matching markers found.")
        return

    update_duration(header, result)
    out = args.output or args.file
    write_cast(out, header, result)
    print(f"Removed {removed} marker(s)")
    print(f"  Output: {out} ({len(result)} events)")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="asciineditor",
        description="Editor for asciicast v2 (.cast) files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # split
    p_split = sub.add_parser("split", help="Split a cast file into two at a given position")
    p_split.add_argument("file", help="Input .cast file")
    p_split.add_argument("--at", required=True,
                         help="Position to split at: seconds (e.g. 5.0) or marker:<label>")
    p_split.add_argument("--output1", "-o1", help="Output file for part 1")
    p_split.add_argument("--output2", "-o2", help="Output file for part 2")
    p_split.set_defaults(func=cmd_split)

    # join
    p_join = sub.add_parser("join", help="Join multiple cast files into one")
    p_join.add_argument("files", nargs="+", help="Input .cast files (in order)")
    p_join.add_argument("--output", "-o", help="Output file (default: joined.cast)")
    p_join.add_argument("--gap", type=float, default=0.5,
                        help="Gap in seconds between joined files (default: 0.5)")
    p_join.set_defaults(func=cmd_join)

    # cut
    p_cut = sub.add_parser("cut", help="Cut (remove) a section from a cast file")
    p_cut.add_argument("file", help="Input .cast file")
    p_cut.add_argument("--start", required=True,
                        help="Start position: seconds or marker:<label>")
    p_cut.add_argument("--end", required=True,
                        help="End position: seconds or marker:<label>")
    p_cut.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    p_cut.set_defaults(func=cmd_cut)

    # speed
    p_speed = sub.add_parser("speed", help="Change playback speed of a section")
    p_speed.add_argument("file", help="Input .cast file")
    p_speed.add_argument("--start", required=True,
                         help="Start position: seconds or marker:<label>")
    p_speed.add_argument("--end", required=True,
                         help="End position: seconds or marker:<label>")
    p_speed.add_argument("--factor", "-f", type=float, required=True,
                         help="Speed factor (2.0 = 2x faster, 0.5 = half speed)")
    p_speed.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    p_speed.set_defaults(func=cmd_speed)

    # remove-marker
    p_rm = sub.add_parser("remove-marker", help="Remove marker events from a cast file")
    p_rm.add_argument("file", help="Input .cast file")
    p_rm_group = p_rm.add_mutually_exclusive_group(required=True)
    p_rm_group.add_argument("--label", help="Remove markers with this label")
    p_rm_group.add_argument("--at", help="Remove marker at this timestamp (seconds)")
    p_rm_group.add_argument("--all", action="store_true", help="Remove all markers")
    p_rm.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    p_rm.set_defaults(func=cmd_remove_marker)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
