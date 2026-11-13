#!/usr/bin/env python3
"""
Plot e-vaskeri usage from the log produced by fetch_sample.py.

    pip install pandas matplotlib
    python3 plot_usage.py                 # uses evaskeri_log.csv
    python3 plot_usage.py mylog.csv

Produces PNGs and prints a text summary (best / worst times to do laundry):
    usage_heatmap.png      washers and dryers: weekday x half-hour occupancy
    best_time.png          chance that a washer / dryer is free, by hour of day
    machine_status.png     how each machine's time splits: in use / done / free
    daily_load.png         average load per day (07:00-22:00)
    usage_by_hour.png      average share of machines in use, per hour of day
    usage_by_weekday.png   same, per weekday

Times are shown in Copenhagen time (the log itself is UTC).
"Occupancy" = fraction of (non-offline) machines in use. Offline machines are
excluded so a broken machine doesn't look like heavy usage. "Free" means the
machine's status is Available; a machine marked Done still has laundry in it.
"""

import sys
import matplotlib
matplotlib.use("Agg")          # save to files, no display needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TZ = "Europe/Copenhagen"

# Chart tokens (light surface; the PNGs carry their own opaque background so
# they read the same on GitHub's light and dark themes).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
WASHER = "#2a78d6"      # categorical slot 1 - washers, in every chart
DRYER = "#1baf7a"       # categorical slot 3 - dryers, in every chart
ACCENT = "#eb6834"      # emphasis: finished laundry left in a machine
IN_USE = INK2
FREE = "#dedcd5"
SEQ = LinearSegmentedColormap.from_list(
    "seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
SEQ.set_bad("#efeeea")  # cells with no data yet
KIND_COLOR = {"washer": WASHER, "dryer": DRYER}
KIND_LABEL = {"washer": "Washers", "dryer": "Dryers"}

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


def titled(fig, title, df, note=None):
    fig.text(0.015, 0.975, title, ha="left", va="top", fontsize=15,
             fontweight="semibold", color=INK)
    sub = span_text(df) + (f" · {note}" if note else "")
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


def free_chance(df):
    """Per (day type, kind, hour): share of samples with >= 1 free machine."""
    per_ts = (df.assign(free=df["status"].str.lower().eq("available"))
                .groupby(["ts", "kind"])["free"].any().reset_index())
    per_ts["hour"] = per_ts["ts"].dt.hour
    per_ts["daytype"] = np.where(per_ts["ts"].dt.day_of_week >= 5,
                                 "Weekend", "Weekdays")
    raw = (per_ts.groupby(["daytype", "kind", "hour"])["free"].mean()
                 .mul(100))
    # smooth over 3 hours (wrapping past midnight): single hours are noisy
    def smooth(s):
        s = s.droplevel([0, 1]).reindex(range(24))
        wrapped = pd.concat([s.iloc[-1:], s, s.iloc[:1]])
        return wrapped.rolling(3, center=True, min_periods=2).mean().iloc[1:-1]
    return raw.groupby(level=[0, 1]).apply(smooth)


def waking(s, lo=7, hi=22):
    """Restrict an hour-indexed series to hours people actually do laundry."""
    return s[(s.index >= lo) & (s.index <= hi)]


# -------------------------------------------------------------------- summary

def summary(df):
    span = df["ts"].max() - df["ts"].min()
    print(f"\nData span: {span}  ({df['ts'].min():%Y-%m-%d %H:%M} "
          f"-> {df['ts'].max():%Y-%m-%d %H:%M}, Copenhagen time)")
    print(f"Samples:   {df['ts'].nunique()} timestamps, "
          f"{len(df)} machine-readings\n")
    fc = free_chance(df)
    for daytype in ("Weekdays", "Weekend"):
        for kind in ("washer", "dryer"):
            try:
                s = fc.loc[(daytype, kind)]
            except KeyError:
                continue
            w = waking(s)
            print(f"{daytype:9s} {kind:7s} best {int(w.idxmax()):02d}:00 "
                  f"({w.max():.0f}% a machine is free)   "
                  f"worst {int(w.idxmin()):02d}:00 ({w.min():.0f}%)   "
                  f"[07:00-22:00, 3 h smoothed]")
    print()


# --------------------------------------------------------------------- charts

def plot_heatmap(df):
    """Weekday x half-hour occupancy, one panel each for washers and dryers."""
    df = df.copy()
    df["slot"] = df["ts"].dt.hour * 2 + (df["ts"].dt.minute >= 30)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.2), sharex=True)
    mesh = None
    for ax, kind in zip(axes, ("washer", "dryer")):
        sub = df[df["kind"] == kind]
        piv = (sub.pivot_table(index="weekday", columns="slot",
                               values="in_use", aggfunc="mean", observed=True)
                  .reindex(index=WEEK, columns=range(48)))
        mesh = ax.pcolormesh(np.arange(49), np.arange(8),
                             np.ma.masked_invalid(piv.values * 100),
                             cmap=SEQ, vmin=0, vmax=100,
                             edgecolors=SURFACE, linewidth=1.2)
        ax.set_ylim(7, 0)                       # Monday on top
        ax.set_yticks(np.arange(7) + 0.5)
        ax.set_yticklabels(WEEK)
        ax.set_xticks(range(0, 48, 4))
        ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
        ax.set_title(f"{KIND_LABEL[kind]} ({sub['machine'].nunique()} machines)",
                     loc="left", fontsize=10.5, color=INK, pad=6)
        style(ax, grid=None)
        ax.spines["bottom"].set_visible(False)
    cbar = fig.colorbar(mesh, cax=fig.add_axes([0.945, 0.08, 0.014, 0.74]))
    cbar.set_label("% of machines in use", fontsize=9)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(length=0, labelsize=9)
    titled(fig, "When are the machines busy?", df,
           note="grey = no data yet; fills in as samples accumulate")
    fig.subplots_adjust(left=0.06, right=0.925, top=0.86, bottom=0.07,
                        hspace=0.22)
    save(fig, "usage_heatmap.png")


def plot_best_time(df):
    """Chance that at least one washer / dryer is free, by hour of day."""
    fc = free_chance(df)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, daytype in zip(axes, ("Weekdays", "Weekend")):
        for kind in ("dryer", "washer"):
            try:
                s = fc.loc[(daytype, kind)].reindex(range(24))
            except KeyError:
                continue
            ax.plot(s.index, s.values, color=KIND_COLOR[kind], linewidth=2.2,
                    label=KIND_LABEL[kind], solid_capstyle="round")
            w = waking(s).dropna()
            if kind != "washer" or w.empty:
                continue
            # call out the best and the worst hour to wash (waking hours only)
            for h, va, dy in ((w.idxmax(), "bottom", 10), (w.idxmin(), "top", -12)):
                ax.plot(h, s[h], "o", markersize=8, color=WASHER,
                        markeredgecolor=SURFACE, markeredgewidth=2, zorder=5)
                ax.annotate(f"{h:02d}:00 · {s[h]:.0f}%", (h, s[h]),
                            textcoords="offset points", xytext=(0, dy),
                            ha="center", va=va, fontsize=9, color=INK,
                            fontweight="semibold", zorder=6,
                            bbox=dict(boxstyle="round,pad=0.25", fc=SURFACE,
                                      ec="none", alpha=0.9))
        ax.set_title(daytype, loc="left", fontsize=10.5, color=INK, pad=8)
        ax.set_ylim(-8, 112)
        ax.set_yticks(range(0, 101, 25))
        ax.set_yticklabels([f"{v}%" for v in range(0, 101, 25)])
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 3)])
        style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    handles, labels = handles[::-1], labels[::-1]       # washers first
    fig.legend(handles, labels, loc="upper right", ncol=2, frameon=False,
               fontsize=9.5, bbox_to_anchor=(0.985, 0.985))
    axes[0].set_ylabel("chance at least one is free", fontsize=9)
    titled(fig, "Best time to do laundry", df,
           note="dots: best and worst washer hour, 07:00-22:00")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.80, bottom=0.09,
                        wspace=0.06)
    save(fig, "best_time.png")


def plot_machine_status(df):
    """Where each machine's time goes: in use / done and not emptied / free."""
    st = df["status"].str.lower()
    d = df.assign(cat=np.select([st.eq("in use"), st.eq("done")],
                                ["in_use", "done"], default="free"))
    share = (d.groupby(["machine", "cat"]).size().unstack(fill_value=0)
              .reindex(columns=["in_use", "done", "free"], fill_value=0))
    share = share.div(share.sum(axis=1), axis=0) * 100
    kinds = d.groupby("machine")["kind"].first()
    order = sorted(share.index, key=lambda m: (kinds[m] != "washer", m))
    # gap between the washer group and the dryer group
    ypos, y, prev = {}, 0, None
    for m in order:
        if prev is not None and kinds[m] != kinds[prev]:
            y += 0.7
        ypos[m] = y
        y += 1
        prev = m

    fig, ax = plt.subplots(figsize=(11, 0.5 * len(order) + 2.2))
    for m in order:
        left = 0
        for cat, color in (("in_use", IN_USE), ("done", ACCENT), ("free", FREE)):
            w = share.loc[m, cat]
            ax.barh(ypos[m], w, left=left, height=0.62, color=color,
                    edgecolor=SURFACE, linewidth=1.5)
            if cat == "in_use" and w >= 6:
                ax.text(left + w / 2, ypos[m], f"{w:.0f}%", ha="center",
                        va="center", color="#ffffff", fontsize=9,
                        fontweight="semibold")
            left += w
        done = share.loc[m, "done"]
        ax.text(103, ypos[m], f"{done:.0f}%", ha="left", va="center",
                fontsize=9.5, color=INK, fontweight="semibold")
    ax.text(103, -0.95, "left\nwaiting", ha="left", va="center", fontsize=8.5,
            color=INK2, linespacing=1.1)
    ax.set_xlim(0, 100)
    ax.set_ylim(max(ypos.values()) + 0.6, -1.3)
    ax.set_yticks([ypos[m] for m in order])
    ax.set_yticklabels(order)
    ax.set_xticks(range(0, 101, 25))
    ax.set_xticklabels([f"{v}%" for v in range(0, 101, 25)])
    style(ax, grid="x")
    ax.spines["bottom"].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c)
               for c in (IN_USE, ACCENT, FREE)]
    fig.legend(handles, ["In use", "Done - laundry left inside", "Free"],
               loc="upper right", ncol=3, frameon=False, fontsize=9.5,
               bbox_to_anchor=(0.985, 0.985))
    titled(fig, "Which machines get used - and left full", df,
           note="share of time per machine")
    fig.subplots_adjust(left=0.09, right=0.93, top=0.86, bottom=0.07)
    save(fig, "machine_status.png")


def plot_daily_load(df):
    """Average share of machines in use per day, 07:00-22:00, washers vs dryers."""
    d = df[(df["hour"] >= 7) & (df["hour"] < 22)].copy()
    d["date"] = d["ts"].dt.tz_localize(None).dt.normalize()
    # a full 15 h day at 10 min spacing is ~90 samples; skip partial days
    per_day = d.groupby("date")["ts"].nunique()
    full = per_day[per_day >= 60].index
    load = (d[d["date"].isin(full)].groupby(["date", "kind"])["in_use"]
              .mean().mul(100).unstack("kind").tail(28))
    if load.empty:
        print("daily_load.png skipped: no complete day yet")
        return
    x = np.arange(len(load))
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for i, kind in enumerate(("washer", "dryer")):
        ax.bar(x + (i - 0.5) * 0.4, load[kind], width=0.4,
               color=KIND_COLOR[kind], edgecolor=SURFACE, linewidth=1.5,
               label=KIND_LABEL[kind])
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t:%a}\n{t.day} {t:%b}" for t in load.index],
                       fontsize=8.5)
    ax.set_xlim(-0.7, len(load) - 0.3)
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 25))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 25)])
    ax.set_ylabel("average % of machines in use", fontsize=9)
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper right", ncol=2,
               frameon=False, fontsize=9.5, bbox_to_anchor=(0.985, 0.985))
    titled(fig, "Busiest days", df,
           note="average load 07:00-22:00; partial days left out")
    fig.subplots_adjust(left=0.07, right=0.985, top=0.84, bottom=0.14)
    save(fig, "daily_load.png")


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
    summary(df)
    plot_heatmap(df)
    plot_best_time(df)
    plot_machine_status(df)
    plot_daily_load(df)
    plot_by_hour(df)
    plot_by_weekday(df)
    print("\nDone.")


if __name__ == "__main__":
    main()
