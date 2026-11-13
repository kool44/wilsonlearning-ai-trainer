# Deploying the trainer

Netlify and Vercel host static sites only. This app has a Python backend (FastAPI), so use a host that runs
containers. Render has a free tier and deploys straight from GitHub.

## 1. Push to GitHub (private repo recommended: content is derived from licensed Wilson Learning material)

```bash
gh repo create wilsonlearning-ai-trainer --private --source=. --remote=origin --push
```

## 2. Deploy on Render (free)

1. Sign in at https://dashboard.render.com with GitHub.
2. New + > Blueprint > select `wilsonlearning-ai-trainer`. Render reads `render.yaml`.
3. When prompted, paste `ANTHROPIC_API_KEY`. Leave the other variables as set.
4. Apply. First build takes 3 to 5 minutes. URL looks like `https://csp-trainer.onrender.com`.

Notes:
- Free plan sleeps after 15 minutes idle; first request after that takes about 30 seconds.
- `DB_PATH=/tmp/trainer.db` on free plan: sessions reset on each deploy or restart. Add a Render Disk (paid)
  and set `DB_PATH` to the mount path to persist.
- Microphone input needs HTTPS. Render provides it.

## Alternatives (same Dockerfile works)

| Host | Free tier | How |
|---|---|---|
| Railway | trial credit | New Project > Deploy from GitHub, add `ANTHROPIC_API_KEY` |
| Fly.io | small free allowance | `fly launch` in this folder, `fly secrets set ANTHROPIC_API_KEY=...` |
| Any VPS | | `docker compose up -d` with `.env` present |
