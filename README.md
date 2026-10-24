# Team Name Standardizer

Keep one standard list of team names (plus aliases) per league, upload a CSV from
any data source, and download it with the names standardized.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Mappings are saved to `mappings.json` next to `app.py`.

## Put it on GitHub
```bash
git init
git add .
git commit -m "Team name standardizer"
git branch -M main
git remote add origin https://github.com/<you>/team-name-standardizer.git
git push -u origin main
```

## Deploy (optional): Streamlit Community Cloud
Connect the repo at share.streamlit.io, main file `app.py`.
Note: the cloud filesystem resets on restart, so edits made in the hosted app are
temporary. Use **Export all mappings** to back up, or build your lists locally and
commit `mappings.json`. Running locally is the simplest way to keep your data.
