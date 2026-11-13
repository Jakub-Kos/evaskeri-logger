#!/usr/bin/env python3
"""
Plot e-vaskeri usage from the log produced by fetch_sample.py.

    pip install pandas matplotlib
    python3 plot_usage.py                 # uses evaskeri_log.csv
    python3 plot_usage.py mylog.csv

Produces PNGs and prints a text summary (best / worst times to start a wash):
    usage_heatmap.png      washers and dryers: weekday x half-hour occupancy
    best_time.png          chance of a smooth wash -> dry, by start time
    now.png                live board: every machine, minutes left, outlook
    usage_by_hour.png      average share of machines in use, per hour of day
    usage_by_weekday.png   same, per weekday

Times are shown in Copenhagen time (the log itself is UTC).
"Occupancy" = fraction of (non-offline) machines in use. Offline machines are
excluded so a broken machine doesn't look like heavy usage. "Free" means the
machine's status is Available; a machine marked Done still has laundry in it.

A "smooth wash -> dry" is: a washer is free when you arrive AND a dryer is free
WASH_MIN minutes later, when the wash finishes.
"""

import sys
import matplotlib
matplotlib.use("Agg")          # save to files, no display needed
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

WASH_MIN = 45                   # minutes a wash takes before the dryer
WAKING = (7, 21)                # start hours worth recommending

WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TZ = "Europe/Copenhagen"

# Chart tokens (light surface; the PNGs carry their own opaque background so
# they read the same on GitHub's light and dark themes).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CARD = "#f4f3ee"
WEEKDAY = "#2a78d6"     # categorical slot 1
WEEKEND = "#eb6834"     # categorical slot 2
GOOD, SERIOUS, MUTED = "#0ca30c", "#ec835a", "#898781"   # status palette

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2,
    "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def load(path):
    df = pd.read_csv(path)
    # the log is UTC; bucket by Copenhagen wall-clock time (handles DST)
    df["ts"] = (pd.to_datetime(df["timestamp_iso"]).dt.tz_localize("UTC")
                .dt.tz_convert(TZ))
    df["hour"] = df["ts"].dt.hour
    df["weekday"] = pd.Categorical(df["ts"].dt.day_name().str[:3],
                                   categories=WEEK, ordered=True)
    df["offline"] = df["status"].str.contains("offline", case=False, na=False)
    # keep only machines that were online when sampled
    return df[~df["offline"]].copy()


# ---------------------------------------------------------------- shared bits

def span_text(df):
    a, b = df["ts"].min(), df["ts"].max()
    return (f"{df['ts'].nunique():,} samples, "
            f"{a:%b} {a.day} - {b:%b} {b.day} · Copenhagen time")


def titled(fig, title, sub):
    fig.text(0.015, 0.975, title, ha="left", va="top", fontsize=15,
             fontweight="semibold", color=INK)
    fig.text(0.015, 0.918, sub, ha="left", va="top", fontsize=9.5, color=INK2)


def style(ax, grid="y"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(length=0, labelsize=9)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(name, dpi=130)
    plt.close(fig)
    print(f"wrote {name}")


def slot_of(ts):
    """Half-hour slot of the day, 0..47."""
    return ts.dt.hour * 2 + (ts.dt.minute >= 30)


def hhmm(slot):
    return f"{int(slot) // 2:02d}:{30 * (int(slot) % 2):02d}"


# ------------------------------------------------------ wash -> dry planning

def wash_dry(df):
    """One row per sample time t: ok = washer free at t AND dryer free later."""
    free = df.assign(free=df["status"].str.lower().eq("available"))
    per = (free.groupby(["ts", "kind"])["free"].any().unstack("kind")
               .dropna().astype(bool).sort_index())
    left = pd.DataFrame({"ts": per.index, "washer": per["washer"].values})
    left["target"] = left["ts"] + pd.Timedelta(minutes=WASH_MIN)
    right = pd.DataFrame({"t_later": per.index,
                          "dryer_later": per["dryer"].values})
    m = pd.merge_asof(left, right, left_on="target", right_on="t_later",
                      direction="nearest", tolerance=pd.Timedelta(minutes=6))
    m = m.dropna(subset=["t_later"])        # no sample near t + WASH_MIN
    m["ok"] = m["washer"] & m["dryer_later"].astype(bool)
    m["slot"] = slot_of(m["ts"])
    m["daytype"] = np.where(m["ts"].dt.day_of_week >= 5, "Weekend", "Weekdays")
    return m


def plan_curves(df):
    """{daytype: 48-slot % chance of a smooth wash -> dry}, smoothed 2.5 h."""
    m = wash_dry(df)
    raw = m.groupby(["daytype", "slot"])["ok"].mean().mul(100)
    out = {}
    for dt in ("Weekdays", "Weekend"):
        if dt in raw.index.get_level_values(0):
            s = raw.loc[dt].reindex(range(48))
        else:
            s = pd.Series(np.nan, index=range(48))
        wrapped = pd.concat([s.iloc[-2:], s, s.iloc[:2]])   # wrap midnight
        out[dt] = (wrapped.rolling(5, center=True, min_periods=3).mean()
                          .iloc[2:-2].reset_index(drop=True))
    days = m.groupby("daytype")["ts"].apply(lambda s: s.dt.date.nunique())
    return out, days.to_dict()


def waking_slots(s):
    lo, hi = WAKING
    return s.iloc[lo * 2: hi * 2 + 1].dropna()


# -------------------------------------------------------------------- summary

def summary(df, curves):
    span = df["ts"].max() - df["ts"].min()
    print(f"\nData span: {span}  ({df['ts'].min():%Y-%m-%d %H:%M} "
          f"-> {df['ts'].max():%Y-%m-%d %H:%M}, Copenhagen time)")
    print(f"Samples:   {df['ts'].nunique()} timestamps, "
          f"{len(df)} machine-readings\n")
    print(f"Start a wash -> washer free now AND a dryer free {WASH_MIN} min later "
          f"({WAKING[0]:02d}:00-{WAKING[1]:02d}:00 starts, 2.5 h smoothed):")
    for dt, s in curves.items():
        w = waking_slots(s)
        if w.empty:
            continue
        print(f"  {dt:9s} best {hhmm(w.idxmax())} ({w.max():.0f}%)   "
              f"worst {hhmm(w.idxmin())} ({w.min():.0f}%)")
    print()


# --------------------------------------------------------------------- charts

def plot_heatmap(df):
    """Weekday x half-hour occupancy, one panel each for washers and dryers."""
    df = df.copy()
    df["slot"] = slot_of(df["ts"])
    cmap = plt.get_cmap("YlOrRd").copy()
    cmap.set_bad("#efeeea")                     # cells with no data yet
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.2), sharex=True)
    mesh = None
    for ax, kind, label in zip(axes, ("washer", "dryer"),
                               ("Washers", "Dryers")):
        sub = df[df["kind"] == kind]
        piv = (sub.pivot_table(index="weekday", columns="slot",
                               values="in_use", aggfunc="mean", observed=True)
                  .reindex(index=WEEK, columns=range(48)))
        mesh = ax.pcolormesh(np.arange(49), np.arange(8),
                             np.ma.masked_invalid(piv.values * 100),
                             cmap=cmap, vmin=0, vmax=100,
                             edgecolors=SURFACE, linewidth=1.0)
        ax.set_ylim(7, 0)                       # Monday on top
        ax.set_yticks(np.arange(7) + 0.5)
        ax.set_yticklabels(WEEK)
        ax.set_xticks(range(0, 48, 4))
        ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
        ax.set_title(f"{label} ({sub['machine'].nunique()} machines)",
                     loc="left", fontsize=10.5, color=INK, pad=6)
        style(ax, grid=None)
        ax.spines["bottom"].set_visible(False)
    cbar = fig.colorbar(mesh, cax=fig.add_axes([0.945, 0.08, 0.014, 0.74]))
    cbar.set_label("% of machines in use", fontsize=9)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(length=0, labelsize=9)
    titled(fig, "When are the machines busy?",
           span_text(df) + " · grey = no data yet")
    fig.subplots_adjust(left=0.06, right=0.925, top=0.86, bottom=0.07,
                        hspace=0.22)
    save(fig, "usage_heatmap.png")


def plot_best_time(curves, days, df):
    """Chance of a smooth wash -> dry by start time, weekdays vs weekend."""
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(48) / 2
    series = (("Weekdays", WEEKDAY), ("Weekend", WEEKEND))
    for dt, color in series:
        s = curves[dt]
        n = days.get(dt, 0)
        ax.plot(x, s.values, color=color, linewidth=2.4, solid_capstyle="round",
                label=f"{dt} ({n} day{'s' if n != 1 else ''} of data)")
    # call out the single best start (both lines peak early) and each line's worst
    marks = []
    wake = {dt: waking_slots(curves[dt]) for dt, _ in series}
    wake = {dt: w for dt, w in wake.items() if not w.empty}
    if wake:
        dt_best = max(wake, key=lambda d: wake[d].max())
        marks.append((dt_best, wake[dt_best].idxmax(), "bottom", 11))
    marks += [(dt, w.idxmin(), "top", -12) for dt, w in wake.items()]
    colors = dict(series)
    for dt, slot, va, dy in marks:
        v = wake[dt][slot]
        ax.plot(slot / 2, v, "o", markersize=8, color=colors[dt],
                markeredgecolor=SURFACE, markeredgewidth=2, zorder=5)
        ax.annotate(f"{hhmm(slot)} · {v:.0f}%", (slot / 2, v),
                    textcoords="offset points", xytext=(0, dy),
                    ha="center", va=va, fontsize=9, color=INK,
                    fontweight="semibold", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.25", fc=SURFACE,
                              ec="none", alpha=0.9))
    ax.set_xlim(WAKING[0] - 1, WAKING[1] + 2)
    ax.set_xticks(range(WAKING[0] - 1, WAKING[1] + 3, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(WAKING[0] - 1,
                                                      WAKING[1] + 3, 2)])
    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 25))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 25)])
    ax.set_xlabel("when you put the wash on", fontsize=9)
    ax.set_ylabel("chance it goes smoothly", fontsize=9)
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper right", ncol=2,
               frameon=False, fontsize=9.5, bbox_to_anchor=(0.985, 0.985))
    titled(fig, "Best time to start a wash",
           f"A washer is free when you arrive AND a dryer is free "
           f"{WASH_MIN} min later · {span_text(df)}")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.12)
    save(fig, "best_time.png")


def plot_now(df, curves):
    """Live board: every machine with status and minutes left, plus outlook."""
    last = df["ts"].max()
    cur = df[df["ts"] == last].sort_values("machine")
    fig, ax = plt.subplots(figsize=(11, 5.3))
    ax.set_xlim(-2.75, 6.05)
    ax.set_ylim(-0.55, 2.75)
    ax.axis("off")

    rows = (("washer", "Washers", 1.95), ("dryer", "Dryers", 0.8))
    for kind, label, y in rows:
        sub = cur[cur["kind"] == kind]
        n_free = int(sub["status"].str.lower().eq("available").sum())
        busy = sub[sub["in_use"] == 1]["remaining_min"].dropna()
        if n_free:
            nxt = "free now"
        elif not busy.empty:
            nxt = f"next one in ~{int(busy.min())} min"
        else:
            nxt = "none finishing soon"
        ax.text(-2.65, y + 0.22, label, fontsize=14, fontweight="semibold",
                va="center", color=INK)
        ax.text(-2.65, y - 0.06, f"{n_free} of {len(sub)} free", fontsize=11,
                va="center", color=INK)
        ax.text(-2.65, y - 0.30, nxt, fontsize=9.5, va="center", color=INK2)
        for i, (_, r) in enumerate(sub.iterrows()):
            st = r["status"].lower()
            if st == "available":
                color, main, small = GOOD, "Free", "available"
            elif st == "done":
                color, main, small = SERIOUS, "Done", "laundry inside"
            elif pd.notna(r["remaining_min"]):
                color, main, small = MUTED, f"{int(r['remaining_min'])} min", "left"
            else:
                color, main, small = MUTED, "In use", ""
            x = i + 0.04
            ax.add_patch(Rectangle((x, y - 0.45), 0.92, 0.9, fc=CARD,
                                   ec=GRID, linewidth=1))
            ax.add_patch(Rectangle((x, y - 0.45), 0.92, 0.1, fc=color,
                                   ec="none"))
            ax.text(x + 0.46, y + 0.28, r["machine"], ha="center", va="center",
                    fontsize=9, color=INK2)
            ax.text(x + 0.46, y + 0.02, main, ha="center", va="center",
                    fontsize=17, fontweight="semibold", color=INK)
            ax.text(x + 0.46, y - 0.2, small, ha="center", va="center",
                    fontsize=8.5, color=INK2)

    # outlook: how likely is a dryer to be free when a wash started now ends
    dt = "Weekend" if last.day_of_week >= 5 else "Weekdays"
    v = curves[dt].iloc[int(slot_of(pd.Series([last])).iloc[0])]
    if pd.notna(v):
        ax.text(-2.65, -0.3,
                f"Start a wash now and, typically, a washer is free and a dryer "
                f"is free {WASH_MIN} min later {v:.0f}% of the time "
                f"({dt.lower()} at this hour).",
                fontsize=10, va="center", color=INK)
    titled(fig, "Right now",
           f"as of {last:%H:%M} Copenhagen time · refreshed after every sample")
    fig.subplots_adjust(left=0.015, right=0.985, top=0.86, bottom=0.02)
    save(fig, "now.png")


def plot_by_hour(df):
    fig, ax = plt.subplots(figsize=(10, 4))
    for kind, grp in df.groupby("kind"):
        s = grp.groupby("hour")["in_use"].mean().reindex(range(24))
        ax.plot(s.index, s.values * 100, marker="o", label=kind)
    overall = df.groupby("hour")["in_use"].mean().reindex(range(24))
    ax.plot(overall.index, overall.values * 100, color="black",
            linewidth=2, label="all")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("hour of day (Copenhagen time)")
    ax.set_ylabel("% of machines in use")
    ax.set_title("Laundry usage by hour of day")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig("usage_by_hour.png", dpi=120)
    plt.close(fig)
    print("wrote usage_by_hour.png")


def plot_by_weekday(df):
    s = df.groupby("weekday", observed=True)["in_use"].mean() * 100
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(s.index.astype(str), s.values)
    ax.set_ylabel("% of machines in use")
    ax.set_title("Laundry usage by weekday")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig("usage_by_weekday.png", dpi=120)
    plt.close(fig)
    print("wrote usage_by_weekday.png")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "evaskeri_log.csv"
    df = load(path)
    if df.empty:
        sys.exit("No usable rows in the log yet — let the recorder run first.")
    curves, days = plan_curves(df)
    summary(df, curves)
    plot_heatmap(df)
    plot_best_time(curves, days, df)
    plot_now(df, curves)
    plot_by_hour(df)
    plot_by_weekday(df)
    print("\nDone.")


if __name__ == "__main__":
    main()
