# Deploying SignalForge

Step-by-step guide to deploying SignalForge to Railway (backend) + Vercel (frontend) + Supabase (auth & storage).

---

## Prerequisites

- GitHub account with the repo pushed
- Railway account (https://railway.app) -- Hobby plan ($5/mo credit)
- Vercel account (https://vercel.com) -- Free tier
- Supabase project (https://supabase.com) -- Free tier

---

## 1. Supabase Setup

If you haven't already configured Supabase:

1. Create a new project at https://app.supabase.com
2. Note down these values from **Settings > API**:
   - `Project URL` -> used as `SUPABASE_URL`
   - `anon public` key -> used as `SUPABASE_ANON_KEY`
   - `service_role` key -> used as `SUPABASE_SERVICE_KEY`
3. From **Settings > API > JWT Settings**:
   - `JWT Secret` -> used as `SUPABASE_JWT_SECRET`
4. Create the charts storage bucket:
   - Go to **Storage** > **New bucket**
   - Name: `charts`, set to **Public**
5. Add RLS policies to the `charts` bucket:
   - Public read: `SELECT` for all users
   - Authenticated upload: `INSERT` for authenticated users (path starts with their user ID)
   - Authenticated delete: `DELETE` for authenticated users (path starts with their user ID)

Email/password auth is enabled by default -- no extra configuration needed.

---

## 2. Railway Setup (Backend)

1. Go to https://railway.app and create a **New Project**
2. Choose **Deploy from GitHub repo** and select `signalForge`
3. Railway will auto-detect the `Dockerfile` at the project root

### Add PostgreSQL

1. In the Railway project, click **+ New** > **Database** > **PostgreSQL**
2. Railway automatically creates a `DATABASE_URL` variable and links it to your service

### Set Environment Variables

In the Railway service settings, go to **Variables** and add:

```
ENVIRONMENT=production
PERPLEXITY_API_KEY=<your key>
ANTHROPIC_API_KEY=<your key>
GOOGLE_API_KEY=<your key>
OPENAI_API_KEY=<your key>
CHARTIMG_API_KEY=<your key>
SUPABASE_URL=<from Supabase dashboard>
SUPABASE_ANON_KEY=<from Supabase dashboard>
SUPABASE_SERVICE_KEY=<from Supabase dashboard>
SUPABASE_JWT_SECRET=<from Supabase dashboard>
ALLOWED_ORIGINS=https://your-app.vercel.app
```

Notes:
- `DATABASE_URL` is set automatically by the Postgres addon
- `PORT` is set automatically by Railway
- Set `ALLOWED_ORIGINS` to your Vercel domain (update after Vercel deploy)

### Verify

After deploy completes, hit `https://<your-railway-url>/health`. You should see:

```json
{"status": "ok", "version": "0.1.0"}
```

---

## 3. Vercel Setup (Frontend)

1. Go to https://vercel.com and click **Add New Project**
2. Import the `signalForge` GitHub repo
3. Configure these settings:
   - **Root Directory:** `src/frontend`
   - **Framework Preset:** Vite
   - **Build Command:** `bun run build`
   - **Output Directory:** `dist`

### Set Environment Variables

In the Vercel project settings, add:

```
VITE_API_URL=https://<your-railway-url>
VITE_SUPABASE_URL=<from Supabase dashboard>
VITE_SUPABASE_ANON_KEY=<from Supabase dashboard>
```

### Update Railway CORS

After Vercel assigns your domain (e.g., `https://signalforge.vercel.app`), go back to Railway and update:

```
ALLOWED_ORIGINS=https://signalforge.vercel.app
```

If you also develop locally, use a comma-separated list:

```
ALLOWED_ORIGINS=https://signalforge.vercel.app,http://localhost:5173
```

---

## 4. Create Your First Account

1. Open your Vercel URL in a browser
2. Click **Sign up** on the login page
3. Enter your email and a password (min 6 characters)
4. Check your email for the confirmation link from Supabase
5. After confirming, sign in

---

## 5. Local Development

For local development alongside the cloud deployment:

### Backend

```bash
# Copy and fill in .env at project root
cp .env.example .env

# Start the backend
cd src/backend
uv run uvicorn main:app --reload --port 8420
```

### Frontend

```bash
# Copy and fill in frontend env
cp src/frontend/.env.example src/frontend/.env.local

# Set these in .env.local:
# VITE_API_URL=http://localhost:8420
# VITE_SUPABASE_URL=<your supabase url>
# VITE_SUPABASE_ANON_KEY=<your supabase anon key>

cd src/frontend
bun run dev
```

---

## CI/CD

GitHub Actions runs automatically on push to `main` or `feature/cloud-migration`:

- **Backend job:** ruff check, ruff format check, ty type check
- **Frontend job:** TypeScript check, production build

Railway and Vercel each have their own GitHub integrations that auto-deploy on push -- no additional CI config needed for deployment.

---

## Estimated Monthly Cost

| Service  | Tier            | Cost          |
|----------|-----------------|---------------|
| Railway  | Hobby ($5 credit) | ~$5-10/mo   |
| Vercel   | Free            | $0            |
| Supabase | Free            | $0            |
| **Total**|                 | **~$5-10/mo** |

LLM API costs (OpenAI, Anthropic, Google, Perplexity) are separate and usage-dependent.
