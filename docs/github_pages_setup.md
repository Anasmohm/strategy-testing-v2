# GitHub Pages Setup

This project is prepared to publish the rendered dashboards with GitHub Pages.

## Daily Update

The workflow file is:

`.github/workflows/daily-dashboard.yml`

It runs once per day at `02:15 UTC`, which is `05:15` in Riyadh.

The workflow does four things:

1. Refreshes market data.
2. Rebuilds the portfolio, analytics, and diagnosis dashboards.
3. Commits the refreshed `data/market_data`, `reports`, and `publish_dashboard` files back to the repository.
4. Publishes `publish_dashboard` to GitHub Pages.

## GitHub Settings

After pushing this folder to a GitHub repository:

1. Open the repository on GitHub.
2. Go to `Settings`.
3. Open `Pages`.
4. Under `Build and deployment`, choose `GitHub Actions`.
5. Go to `Actions`.
6. Run `Daily V2 dashboard update` manually once with `Run workflow`.

After the first successful run, GitHub will show the Pages URL.

## Repository Visibility

GitHub Pages works with public repositories on GitHub Free.
Publishing Pages from a private repository generally requires GitHub Pro, Team, or Enterprise.

If you use a public repository, the published dashboard URL is public. This project writes `robots.txt` with `Disallow: /` to reduce search indexing, but it is not password protection.

## Local Build

To update locally without publishing:

```powershell
python update_github_pages_v2.py
```

The local site files will be in:

`publish_dashboard`
