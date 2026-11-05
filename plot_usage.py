#!/usr/bin/env python3
"""
Plot e-vaskeri usage from a log produced by evaskeri_recorder.py.

    pip install pandas matplotlib
    python3 plot_usage.py                 # uses evaskeri_log.csv
    python3 plot_usage.py mylog.csv

Produces three PNGs and prints a text summary (busiest / quietest times):
    usage_by_hour.png      average share of machines in use, per hour of day
    usage_by_weekday.png   same, per weekday
    usage_heatmap.png      weekday x hour heatmap of occupancy

"Occupancy" = fraction of (non-offline) machines in use. Offline machines are
excluded so a broken machine doesn't look like heavy usage.
"""

import sys
import matplotlib
matplotlib.use("Agg")          # save to files, no display needed
import matplotlib.pyplot as plt
import pandas as pd

WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def load(path):
    df = pd.read_csv(path)
    # the log is UTC; bucket by Copenhagen wall-clock time (handles DST)
    df["ts"] = (pd.to_datetime(df["timestamp_iso"]).dt.tz_localize("UTC")
                .dt.tz_convert("Europe/Copenhagen"))
    df["hour"] = df["ts"].dt.hour
    df["weekday"] = pd.Categorical(df["ts"].dt.day_name().str[:3],
                                   categories=WEEK, ordered=True)
    df["offline"] = df["status"].str.contains("offline", case=False, na=False)
    # keep only machines that were online when sampled
    return df[~df["offline"]].copy()


def summary(df):
    span = df["ts"].max() - df["ts"].min()
    by_hour = df.groupby("hour")["in_use"].mean()
    by_wday = df.groupby("weekday", observed=True)["in_use"].mean()
    print(f"\nData span: {span}  ({df['ts'].min():%Y-%m-%d %H:%M} "
          f"-> {df['ts'].max():%Y-%m-%d %H:%M})")
    print(f"Samples:   {df['ts'].nunique()} timestamps, "
          f"{len(df)} machine-readings\n")
    if not by_hour.empty:
        print(f"Busiest hour:   {int(by_hour.idxmax()):02d}:00  "
              f"({by_hour.max()*100:.0f}% of machines in use)")
        print(f"Quietest hour:  {int(by_hour.idxmin()):02d}:00  "
              f"({by_hour.min()*100:.0f}%)")
    if not by_wday.empty:
        print(f"Busiest day:    {by_wday.idxmax()}  ({by_wday.max()*100:.0f}%)")
        print(f"Quietest day:   {by_wday.idxmin()}  ({by_wday.min()*100:.0f}%)")
    print()


def plot_by_hour(df):
    fig, ax = plt.subplots(figsize=(10, 4))
    for kind, grp in df.groupby("kind"):
        s = grp.groupby("hour")["in_use"].mean().reindex(range(24))
        ax.plot(s.index, s.values * 100, marker="o", label=kind)
    overall = df.groupby("hour")["in_use"].mean().reindex(range(24))
    ax.plot(overall.index, overall.values * 100, color="black",
            linewidth=2, label="all")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("hour of day")
    ax.set_ylabel("% of machines in use")
    ax.set_title("Laundry usage by hour of day")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig("usage_by_hour.png", dpi=120)
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
    print("wrote usage_by_weekday.png")


def plot_heatmap(df):
    piv = (df.pivot_table(index="weekday", columns="hour",
                          values="in_use", aggfunc="mean", observed=True)
             .reindex(index=WEEK, columns=range(24)))
    fig, ax = plt.subplots(figsize=(11, 4))
    im = ax.imshow(piv.values * 100, aspect="auto", cmap="YlOrRd",
                   vmin=0, vmax=100, origin="upper")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels(range(0, 24, 2))
    ax.set_yticks(range(len(WEEK)))
    ax.set_yticklabels(WEEK)
    ax.set_xlabel("hour of day (Copenhagen time)")
    ax.set_title("Occupancy heatmap (% machines in use)")
    fig.colorbar(im, ax=ax, label="% in use")
    fig.tight_layout()
    fig.savefig("usage_heatmap.png", dpi=120)
    print("wrote usage_heatmap.png")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "evaskeri_log.csv"
    df = load(path)
    if df.empty:
        sys.exit("No usable rows in the log yet — let the recorder run first.")
    summary(df)
    plot_by_hour(df)
    plot_by_weekday(df)
    plot_heatmap(df)
    print("\nDone.")


if __name__ == "__main__":
    main()
