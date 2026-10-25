# Deployment

There are two ways to show the dashboard:

| | Where | Data | Needs |
|---|---|---|---|
| Lab (recommended for the live demo) | On the VM, http://127.0.0.1:5173 | LIVE LAB: real data from Flask, Ryu and the hosts | `bash scripts/start_lab.sh` |
| Public site | Vercel, https://<project>.vercel.app | DEMO MODE: invented sample data, clearly labelled | Nothing running |

The Vercel site is a static copy of the frontend only. The controller,
Mininet and Flask never run in the cloud, and nothing on the VM is opened
to the internet unless you deliberately follow the optional tunnel steps
at the end.

## 1. Settings used by the build

`frontend/.env.production` (used by `npm run build`):

| Variable | Value | Meaning |
|---|---|---|
| `VITE_DEFAULT_MODE` | `demo` | The page opens in DEMO MODE. Viewers can switch to LIVE LAB, which shows an error state when no backend is reachable. |
| `VITE_API_BASE_URL` | `http://127.0.0.1:5000` | Backend used in LIVE LAB mode. Viewers can change it in the Connection panel. |

`frontend/.env.example` shows the same variables for local overrides
(`frontend/.env.local`, not committed). No secret is ever put into the
build: the API token is typed into the Connection panel and stays in that
browser.

`frontend/vercel.json`: Vite framework, `npm ci`, `npm run build`, output
`dist`, plus security headers (no framing, no MIME sniffing, no referrer,
and a Content-Security-Policy that only allows the site's own scripts and
connections to HTTPS or to localhost).

## 2. Test the production build locally

```
cd frontend
npm run build
npm run preview          # http://127.0.0.1:4173 opens in DEMO MODE
```
Switch to LIVE LAB in the page to use the local backend (the preview
origin 127.0.0.1:4173 is in the backend's default CORS allowlist).

Checked on 2026-10-25: the build served with the exact `vercel.json`
headers renders every page in DEMO MODE, with no Content-Security-Policy
problems, and works at phone width (390 px).

## 3. Deploy to Vercel (GitHub + Vercel, done by you)

These steps publish code to GitHub and a site to Vercel, so they are done
from your accounts, not by the project scripts.

1. Create an empty repository on GitHub (for example `sdn-qos`). Private
   is fine; Vercel can read private repositories you grant it.
2. In the project folder, make the first commit and push:
   ```
   cd ~/sdn-qos
   git status                 # check: no .venv, node_modules, results, environment.env
   git add .
   git commit -m "SDN QoS for video streaming"
   git branch -M main
   git remote add origin https://github.com/<you>/sdn-qos.git
   git push -u origin main
   ```
   `.gitignore` already keeps out `.venv/`, `node_modules/`,
   `frontend/dist/`, `results/` and `config/environment.env` (the token).
3. On https://vercel.com: Add New, Project, import the GitHub repository.
4. Set **Root Directory** to `frontend`. Vercel then reads
   `frontend/vercel.json` (framework Vite, build `npm run build`, output
   `dist`). Leave the environment variables empty: `.env.production`
   already sets DEMO MODE.
5. Deploy. Open the URL and check:
   - the yellow DEMO MODE banner, and "DEMO DATA" on every card and chart
   - all five pages load, and reloading a page works (the app uses
     `#/page` addresses, so no rewrite rules are needed)
   - switching to LIVE LAB shows a red "Cannot reach the backend" error,
     not numbers. That is correct: there is no lab behind the public site.

Every later `git push` to `main` redeploys automatically.

## 4. LIVE LAB on the Vercel site, in a browser on the VM

The deployed page runs in the viewer's browser, so its LIVE LAB mode
calls `http://127.0.0.1:5000` on the viewer's own computer. On the VM
itself that is the real backend, so this works without any tunnel:

1. Allow the site in `config/environment.env` (gitignored, local only):
   ```
   SDN_QOS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,https://sdn-qos.vercel.app
   ```
   and restart the backend (`bash scripts/stop_lab.sh`, then
   `bash scripts/start_lab.sh`).
2. Start the lab: `bash scripts/start_lab.sh`.
3. In Firefox on the VM open https://sdn-qos.vercel.app and click LIVE LAB.

Why this is safe: Flask still listens on 127.0.0.1 only, so no other
computer can reach it; the allowlist only lets that one website read the
API from a browser running on the VM. Browsers allow an https:// page to
call http://127.0.0.1 because loopback counts as a secure address (newer
Chrome versions may first ask for permission to access local devices).

On any other computer the same button shows the red "Cannot reach the
backend" state, which is correct.

## 5. Live mode from somewhere else (optional, explain only)

For the faculty demo, run the dashboard on the VM itself (table above).
If a live view is ever needed on another machine, the safe way is:

1. **Token.** Set a long random token for the backend, in
   `config/environment.env` (not committed):
   ```
   SDN_QOS_API_TOKEN=<output of: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
   ```
   With a token set, every `/api` route except `/api/health` needs
   `Authorization: Bearer <token>`. The dashboard sends it after you type
   it into the Connection panel.
2. **CORS allowlist.** Allow only the site that will call the API:
   ```
   SDN_QOS_CORS_ORIGINS=https://<project>.vercel.app
   ```
   Other websites cannot read the API from a viewer's browser.
3. **HTTPS tunnel to port 5000 only.** A tunnel (for example a Cloudflare
   quick tunnel, `cloudflared tunnel --url http://127.0.0.1:5000`) gives a
   temporary `https://...` address that forwards to Flask, while Flask
   stays bound to 127.0.0.1 and no firewall or router port is opened. The
   HTTPS address is needed because an https:// site may not call plain
   http:// on another machine. Enter that address and the token in the
   Connection panel. Stop the tunnel right after the demo.
4. **What the backend enforces by itself.** Requests that came through a
   proxy or tunnel are refused unless a token is set, and `/api/ingest`
   (where Ryu and the lab push data) never accepts them, so nobody outside
   can inject fake numbers. Only reads are possible remotely.
5. **Never tunnel or expose** the OpenFlow port 6653, the Ryu REST port
   8080, or SSH. Only the read API on port 5000 is ever meant to be
   reached, and only through the tunnel, with the token.

Installing and running a tunnel tool is a system change and publishes a
service, so it is not done by the project scripts and was not tested.
