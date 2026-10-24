"""Team Name Standardizer - Streamlit app.

Keep one list of standard team names (plus aliases) per league, upload a CSV
from any data source, and download it with the team names standardized.
"""
import csv
import io
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "mappings.json"

st.set_page_config(page_title="Team Name Standardizer", page_icon="⚽", layout="wide")


# ---------- storage ----------
def load_db() -> dict:
    if DB_PATH.exists():
        try:
            data = json.loads(DB_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "leagues" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"leagues": {}}


def save_db() -> None:
    DB_PATH.write_text(
        json.dumps(st.session_state.db, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def merge_into(db: dict, incoming: dict) -> None:
    for league, info in incoming.get("leagues", {}).items():
        teams = db["leagues"].setdefault(league, {"teams": {}})["teams"]
        for std, aliases in info.get("teams", {}).items():
            merged = list(dict.fromkeys(teams.get(std, []) + list(aliases)))
            teams[std] = merged


if "db" not in st.session_state:
    st.session_state.db = load_db()
db = st.session_state.db


# ---------- matching ----------
def norm(s) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def build_map(league: str) -> dict:
    m = {}
    for std, aliases in db["leagues"].get(league, {}).get("teams", {}).items():
        m[norm(std)] = std
        for a in aliases:
            m[norm(a)] = std
    return m


def sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:5000], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


# ---------- text-file import ----------
SEP = re.compile(r"\s*(?:\.{2,}|=>|->|\||\t)\s*")
SEASON = re.compile(r"\d{4}\s*/\s*\d{2,4}")


def parse_pairs(text: str):
    """Parse lines like 'Name A......Name B' into (left, right) pairs.

    Season header lines and lines without a separator are skipped.
    """
    pairs, skipped = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in SEP.split(line) if p.strip()]
        if len(parts) == 2 and not (SEASON.search(parts[0]) and SEASON.search(parts[1])):
            pairs.append((parts[0], parts[1]))
        elif not (len(parts) == 2):
            skipped.append(line)
    return pairs, skipped


def decode_bytes(b: bytes) -> str:
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp1254", errors="replace")


def guess_league(filename: str) -> str:
    return re.sub(r"[_\-]+", " ", Path(filename).stem).strip().title()


# ---------- UI ----------
st.title("⚽ Team Name Standardizer")
tab_convert, tab_teams = st.tabs(["Convert CSV", "Team names"])

# ===== Team names tab =====
with tab_teams:
    leagues = sorted(db["leagues"])

    c1, c2 = st.columns([3, 2])
    with c2:
        new_league = st.text_input("Add a league", placeholder="e.g. England Premier League")
        if st.button("Add league") and new_league.strip():
            db["leagues"].setdefault(new_league.strip(), {"teams": {}})
            save_db()
            st.rerun()
    with c1:
        league = st.selectbox("League", leagues, index=None, placeholder="Choose a league")

    if league:
        teams = db["leagues"][league]["teams"]
        st.subheader(f"{league} · {len(teams)} teams")

        with st.expander("Bulk add (one team per line: Standard name, alias, alias…)"):
            bulk = st.text_area(
                "Bulk add",
                height=150,
                label_visibility="collapsed",
                placeholder="Manchester United, Man United, Man Utd\nWolverhampton Wanderers, Wolves",
                key=f"bulk_{league}",
            )
            if st.button("Add to league", key=f"bulkbtn_{league}"):
                for line in bulk.splitlines():
                    parts = [p.strip() for p in line.split(",") if p.strip()]
                    if parts:
                        teams[parts[0]] = list(dict.fromkeys(teams.get(parts[0], []) + parts[1:]))
                save_db()
                st.session_state.pop(f"ed_{league}", None)
                st.rerun()

        df = pd.DataFrame(
            [{"Standard name": s, "Aliases (comma separated)": ", ".join(a)} for s, a in sorted(teams.items())],
            columns=["Standard name", "Aliases (comma separated)"],
        )
        edited = st.data_editor(df, num_rows="dynamic", key=f"ed_{league}", hide_index=True)
        if st.button("Save changes", type="primary", key=f"save_{league}"):
            new_teams = {}
            for _, row in edited.iterrows():
                std = str(row["Standard name"] or "").strip()
                if not std or std.lower() == "none":
                    continue
                aliases = [a.strip() for a in str(row["Aliases (comma separated)"] or "").split(",")]
                new_teams[std] = [a for a in aliases if a and a.lower() != "none"]
            db["leagues"][league]["teams"] = new_teams
            save_db()
            st.success("Saved.")

        with st.expander("Delete this league"):
            if st.checkbox("Yes, delete it and all its teams", key=f"delchk_{league}"):
                if st.button("Delete league", key=f"delbtn_{league}"):
                    del db["leagues"][league]
                    save_db()
                    st.rerun()

    st.divider()
    st.subheader("Import from text files")
    st.caption(
        "Lines like `Gaziantep FK......Gaziantep F.K.` become one team with an alias. "
        "Season headers and other lines without a separator are skipped. "
        "Separators supported: two or more dots, `=>`, `->`, `|`, tab."
    )
    side = st.radio(
        "Which name is your standard?",
        ["Left name (first on each line)", "Right name (second on each line)"],
        horizontal=True,
    )
    txt_files = st.file_uploader(
        "Upload one or more files (one per league)", type=["txt", "csv"], accept_multiple_files=True, key="txtimp"
    )
    if txt_files:
        plan = []
        for fl in txt_files:
            pairs, skipped = parse_pairs(decode_bytes(fl.getvalue()))
            a, b = st.columns([2, 3])
            lname = a.text_input("League name", value=guess_league(fl.name), key=f"impname_{fl.name}")
            b.write(f"**{len(pairs)}** pairs found" + (f" · {len(skipped)} lines skipped" if skipped else ""))
            with st.expander(f"Preview: {fl.name}"):
                std_i = 0 if side.startswith("Left") else 1
                st.dataframe(
                    pd.DataFrame(
                        [{"Standard": p[std_i], "Alias": p[1 - std_i]} for p in pairs],
                        columns=["Standard", "Alias"],
                    ),
                    hide_index=True,
                )
                if skipped:
                    st.caption("Skipped: " + " | ".join(skipped[:10]))
            plan.append((lname.strip(), pairs))
        if st.button("Import all", type="primary", key="doimp"):
            std_i = 0 if side.startswith("Left") else 1
            for lname, pairs in plan:
                if not lname:
                    continue
                teams = db["leagues"].setdefault(lname, {"teams": {}})["teams"]
                for p in pairs:
                    std, alias = p[std_i], p[1 - std_i]
                    al = teams.setdefault(std, [])
                    if alias != std and alias not in al:
                        al.append(alias)
            save_db()
            st.success(f"Imported {len(plan)} league(s).")
            st.rerun()

    st.divider()
    st.subheader("Backup")
    st.download_button(
        "Export all mappings (JSON)",
        json.dumps(db, indent=2, ensure_ascii=False),
        file_name="mappings.json",
        mime="application/json",
    )
    up = st.file_uploader("Import mappings (merges with what you have)", type="json", key="imp")
    if up is not None and st.button("Import"):
        try:
            merge_into(db, json.loads(up.getvalue().decode("utf-8")))
            save_db()
            st.success("Imported.")
            st.rerun()
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            st.error("That file isn't a valid mappings backup.")

# ===== Convert tab =====
with tab_convert:
    if not db["leagues"]:
        st.info("Start on the **Team names** tab: add a league and some teams.")
    f = st.file_uploader("Upload a CSV", type=["csv", "txt"])

    if f is not None:
        raw = f.getvalue().decode("utf-8-sig", errors="replace")
        delim = sniff_delimiter(raw)
        df_in = pd.read_csv(io.StringIO(raw), sep=delim, dtype=str, keep_default_na=False)
        st.caption(f"{len(df_in)} rows · {len(df_in.columns)} columns · delimiter “{delim}”")

        guess = [c for c in df_in.columns if re.search(r"team|club|home|away|squad", c, re.I)]
        cols = st.multiselect("Columns containing team names", list(df_in.columns), default=guess)

        mode = st.radio("League source", ["One league for the whole file", "A column in the CSV"], horizontal=True)
        if mode.startswith("One"):
            fixed = st.selectbox("League", sorted(db["leagues"]), index=None, key="conv_league")
            league_col = None
        else:
            fixed = None
            league_col = st.selectbox("League column", list(df_in.columns), index=None)

        keep = st.checkbox("Keep original columns and add new “_std” columns instead of overwriting")

        ready = bool(cols) and (fixed or league_col)
        if ready:
            maps = {}
            unmatched = Counter()
            result = df_in.copy()
            row_leagues = df_in[league_col].str.strip() if league_col else [fixed] * len(df_in)
            hits = 0
            for col in cols:
                out = []
                for lg, v in zip(row_leagues, df_in[col]):
                    s = str(v).strip()
                    if not s:
                        out.append(v)
                        continue
                    m = maps.setdefault(lg, build_map(lg)).get(norm(s))
                    if m:
                        out.append(m)
                        hits += 1
                    else:
                        unmatched[(lg, s)] += 1
                        out.append(v)
                result[col + "_std" if keep else col] = out

            miss = sum(unmatched.values())
            st.write(f"**{hits}** names converted" + (f" · **{miss}** not matched" if miss else ""))

            if unmatched:
                st.subheader("Unmatched names")
                st.caption("Map each to a standard team (it's saved as an alias) or add it as a new team.")
                items = unmatched.most_common(100)
                with st.form("unmatched"):
                    choices = {}
                    for (lg, v), n in items:
                        teams_here = sorted(db["leagues"].get(lg, {}).get("teams", {}))
                        a, b = st.columns([2, 3])
                        a.markdown(f"**{v}**  \n×{n}" + (f" · {lg}" if league_col else ""))
                        choices[(lg, v)] = b.selectbox(
                            "map",
                            ["(skip)", "➕ Add as new team"] + teams_here,
                            key=f"un_{lg}_{v}",
                            label_visibility="collapsed",
                        )
                    if st.form_submit_button("Apply mappings", type="primary"):
                        for (lg, v), pick in choices.items():
                            if pick == "(skip)" or not lg:
                                continue
                            teams = db["leagues"].setdefault(lg, {"teams": {}})["teams"]
                            if pick.startswith("➕"):
                                existing = build_map(lg).get(norm(v))
                                if existing is None:
                                    teams.setdefault(v, [])
                                elif existing != v and v not in teams[existing]:
                                    teams[existing].append(v)  # same name, different punctuation
                            elif v not in teams[pick]:
                                teams[pick].append(v)
                        save_db()
                        st.rerun()
                if len(unmatched) > 100:
                    st.caption(f"Showing the 100 most frequent of {len(unmatched)} unmatched names.")

            st.subheader("Preview")
            st.dataframe(result.head(20))
            st.download_button(
                "Download converted CSV",
                result.to_csv(index=False, sep=delim).encode("utf-8"),
                file_name=Path(f.name).stem + "_standardized.csv",
                mime="text/csv",
                type="primary",
            )
        else:
            st.caption("Choose the team columns and a league to continue.")
