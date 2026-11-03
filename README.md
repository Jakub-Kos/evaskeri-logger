# e-vaskeri usage logger (GitHub Actions)

Logs the laundry board at **Signalhuset** every 10 minutes using GitHub's free
scheduled Actions, and commits each reading into `evaskeri_log.csv` in this
repo. No server to run — the repo itself is the database. A second workflow
turns the log into charts showing when the laundry is busiest and quietest.

## What's in here

| File | What it does |
|------|--------------|
| `fetch_sample.py` | Logs in, reads the board once, appends one row per machine. Standard library only. |
| `.github/workflows/record.yml` | Scheduled job: runs `fetch_sample.py` and commits the new row. |
| `.github/workflows/plot.yml` | Manual job: builds charts and uploads them as an artifact. |
| `plot_usage.py` | Reads the CSV → `usage_by_hour.png`, `usage_by_weekday.png`, `usage_heatmap.png`. |
| `requirements.txt` | `pandas`, `matplotlib` (only needed for plotting). |

## One-time setup (about 3 minutes)

1. **Create a new GitHub repository** and push these files to it (default branch
   `main`). A **public** repo is recommended — Actions minutes are unlimited for
   public repos. The data is just machine-occupancy numbers, nothing sensitive.
   (Private also works: see *Private repos* below.)

2. **Add your login as secrets.** In the repo: **Settings → Secrets and variables
   → Actions → New repository secret**. Add two:
   - `EVASKERI_USER` — your e-vaskeri username
   - `EVASKERI_PASS` — your e-vaskeri password

   Secrets are encrypted and never printed in logs.

3. **Allow the workflow to commit.** **Settings → Actions → General → Workflow
   permissions → Read and write permissions → Save.**

4. **Enable Actions.** Open the **Actions** tab and enable workflows if prompted.
   Scheduled workflows only run from the default branch, so make sure these files
   are on `main`.

That's it. Within ~15 minutes the first row lands in `evaskeri_log.csv`, and it
keeps appending on its own. You can also hit **Run workflow** on *Record laundry
usage* to grab a sample immediately and confirm it works.

## Getting your charts

**Easiest:** Actions tab → **Plot usage** → **Run workflow**. When it finishes,
open the run and download the **usage-charts** artifact (the three PNGs).

**Or locally**, once you've collected some data:

```bash
git pull                       # fetch the latest log
pip install -r requirements.txt
python plot_usage.py           # reads evaskeri_log.csv
```

It also prints a text summary — busiest/quietest hour and weekday. A couple of
days gives a usable daily shape; a week or two makes the weekday pattern solid.

## Notes & tuning

- **Interval:** set in `record.yml` (`cron: '*/10 * * * *'`, UTC but
  interval-based so timezone doesn't matter). Minimum GitHub allows is 5 minutes.
- **Scheduling isn't exact:** GitHub may delay or occasionally skip scheduled
  runs under load. Fine for usage statistics.
- **Private repos:** you get a monthly free-minutes cap and **each run is billed
  as a whole minute**. At 15-min spacing that's ~2,880 min/month, over the free
  tier — so on a private repo change the cron to **`*/30 * * * *`** (~1,440/month).
  Public repos have no such limit.
- **Won't get auto-disabled:** GitHub disables scheduled workflows after 60 days
  of repo inactivity, but every sample is a commit, so this repo stays active.
- **Timestamps** in the log are UTC; `plot_usage.py` derives hour/weekday from
  them. If you want the charts in local (Copenhagen) time, shift there — ask and
  it's a one-line change.
