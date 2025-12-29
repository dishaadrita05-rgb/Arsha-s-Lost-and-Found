# Arsha’s Lost and Found (Lost & Found Matcher)

One-click try:

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/dishaadrita05-rgb/Arsha-s-Lost-and-Found?quickstart=1)
[![Open in Gitpod](https://gitpod.io/button/open-in-gitpod.svg)](https://gitpod.io/#https://github.com/dishaadrita05-rgb/Arsha-s-Lost-and-Found)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dishaadrita05-rgb/Arsha-s-Lost-and-Found)

## What this project is
A FastAPI + Jinja2 web app for Lost & Found reporting:
- Login required (phone-based login)
- Submit Lost/Found reports
- Auto-match Lost vs Found using text similarity + extracted attributes (item, colors, brand, identifiers)
- Claim flow: Lost users can claim Found reports with proof text (no phone/email in proof)
- Founder manage page: approve/reject claims + mark settled
- Office-only claim details page (shows sensitive claimant details)

## Run locally
### 1) Install dependencies
```bash
pip install -r requirements.txt
