# GitHub Pages Setup

This project is prepared to publish the rendered dashboards with GitHub Pages.

## Daily Update

The workflow file is:

`.github/workflows/daily-dashboard.yml`

It runs once per day at `02:15 UTC`, which is `05:15` in Riyadh.

The workflow does four things:

1. Refreshes the approved market data from EODHD at five-minute resolution.
2. Rebuilds the approved portfolio and its analytics pages using the approved V3.1 strategy set. It does not redesign strategies during a routine daily update.
3. Commits the refreshed `reports` and `publish_dashboard` files back to the repository. Raw paid-provider data remains private.
4. Publishes `publish_dashboard` to GitHub Pages.

## GitHub Settings

After pushing this folder to a GitHub repository:

1. Open the repository on GitHub.
2. Go to `Settings`.
3. Open `Pages`.
4. Under `Build and deployment`, choose `GitHub Actions`.
5. Open `Settings` then `Secrets and variables` then `Actions`.
6. Create a repository secret named `EODHD_API_TOKEN` and paste the EODHD API token into its value.
7. Go to `Actions`.
8. Run `Daily approved V3.1 dashboard update` manually once with `Run workflow`.

After the first successful run, GitHub will show the Pages URL.

## Repository Visibility

GitHub Pages works with public repositories on GitHub Free.
Publishing Pages from a private repository generally requires GitHub Pro, Team, or Enterprise.

If you use a public repository, the published dashboard URL is public. This project writes `robots.txt` with `Disallow: /` to reduce search indexing, but it is not password protection.

## Local Build

To update locally without publishing:

```powershell
python update_github_pages.py
```

The local site files will be in:

`publish_dashboard`

The default published page opens `portfolio_dashboard.html`, which is the approved V3.1 Hybrid portfolio with the approved next-session daily-high trailing-stop policy. Comparison pages remain in the project reports only and are not published.

The approved engine uses EODHD five-minute regular-session bars for execution. Targets and the stop already known at session open are executable through those bars. A raised trailing stop is calculated only after a completed daily session from that session's high and is first executable in the following trading session.

The official display begins on `2021-01-01`. The `0.5%` trailing-stop step was selected using 2021 data, so performance beginning on `2022-01-01` is the more conservative out-of-selection reading.
