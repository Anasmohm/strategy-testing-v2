This folder is the public Netlify package.
It intentionally contains only the rendered dashboard pages, not Python source files.
Run this after every local dashboard refresh:

python paper_portfolio_v2.py
python prepare_netlify_publish.py

Then deploy this folder to Netlify:
publish_dashboard
