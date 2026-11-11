# Workflow commands: the agent end to end

Commands to watch one claim go from the backend through the agent to Supabase, through a sign-off, and into Langfuse. All of them run in PowerShell from the repo root. Use two terminals: **A** for the servers, **B** for the commands.

They need `.env` with `DATABASE_URL`, `DEMO_PASSWORD`, `OPENROUTER_API_KEY` and the three `LANGFUSE_*` settings. One claim on the default model costs about one or two cents.

## 1. Reseed and start (terminal A)

```powershell
cd C:\Users\LENOVO\undercover
uv run --env-file .env -m backend.seed --reset   # wipes and reseeds the undercover schema on Supabase
npm run dev                                      # backend :8000, dashboard :5173, agent service :8002
```

The reset deletes everything in the `undercover` schema on Supabase, runs and decisions included. Skip it if the claim you want to run is still waiting.

Wait until the log shows `POST /api/agent/resumable ... 200 OK`: the agent's service has reached the backend.

## 2. Sign in (terminal B)

```powershell
cd C:\Users\LENOVO\undercover
# Load .env into this PowerShell session
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { Set-Item "env:$($matches[1])" ($matches[2].Trim().Trim('"')) } }

$B = "http://127.0.0.1:8000"
Invoke-RestMethod "$B/api/health"

# Sign in as Dana, a senior handler who can sign off.
# The cookie is Secure, so PowerShell won't keep it over http: take the token from Set-Cookie.
$resp  = Invoke-WebRequest -Method Post "$B/api/auth/login" -ContentType "application/json" `
         -Body (@{ email = "dana.whitfield@undercover.example"; password = $env:DEMO_PASSWORD } | ConvertTo-Json)
$token = [regex]::Match(($resp.Headers["Set-Cookie"] -join ";"), "cc_session=([^;]+)").Groups[1].Value
$H     = @{ Authorization = "Bearer $token" }
```

## 3. Run the agent on a claim over the sign-off limit

CLM-1011 is $1,150.00, over the $1,000.00 limit.

```powershell
$run = Invoke-RestMethod -Method Post "$B/api/claims/CLM-1011/runs" -Headers $H
$run

# Poll until the run stops (1 to 3 minutes from this machine)
do { Start-Sleep 5; $r = Invoke-RestMethod "$B/api/runs/$($run.run_id)" -Headers $H; "$($r.status)  attempt $($r.attempt)" } while ($r.status -in "running","interrupted")

# The steps it took
Invoke-RestMethod "$B/api/runs/$($run.run_id)/events" -Headers $H | Select-Object kind, name | Format-Table
```

Expect `paused`: the claim waits for sign-off. `failed` with `time_limit` means the claim's 240-second limit ran out against the latency to Seoul; run it again. Close the dashboard tab while a run goes if it is slow: its polling shares the backend's three database connections with the agent.

## 4. Check Supabase

```powershell
$env:RUN_ID = $run.run_id
@'
import os, psycopg
run = os.environ["RUN_ID"]
with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as c:
    c.execute("set search_path to undercover")
    print("run        ", c.execute("select status, attempt, failure from runs where run_id=%s", (run,)).fetchone())
    print("claim      ", c.execute("select state, failed_attempts from claims where claim_id='CLM-1011'").fetchone())
    print("checkpoints", c.execute("select count(*) from checkpoints where thread_id=%s", (run,)).fetchone())
    print("decisions  ", c.execute("select decision, payout_cents from decisions where claim_id='CLM-1011'").fetchall())
    print("payments   ", c.execute("select amount_cents, signed_off_by, signed_off_at, created_at from payments where claim_id='CLM-1011'").fetchall())
    print("connections", c.execute("select application_name, count(*) from pg_stat_activity where usename in ('postgres','undercover_app') group by 1").fetchall())
'@ | uv run --env-file .env python -
```

Expect the run `paused`, the claim `waiting_for_signoff`, some checkpoints, one decision (`approve`, `115000` cents) and no payment yet. The same queries work in the Supabase SQL editor after `set search_path to undercover;`.

## 5. Sign off and watch it get paid

On the dashboard: open http://localhost:5173, sign in as Dana, go to **Sign-off** and click **Sign off** on CLM-1011. Or through the API:

```powershell
Invoke-RestMethod -Method Post "$B/api/claims/CLM-1011/sign-off" -Headers $H
do { Start-Sleep 2; $c = Invoke-RestMethod "$B/api/claims/CLM-1011" -Headers $H; "$($c.state)  paid $($c.paid)" } while ($c.paid -eq 0)
$c.payments
```

The sign-off wakes the agent's service, which carries the claim on and pays it: about 9 to 13 seconds from this machine. Run step 4 again: the run is `succeeded`, and there is one payment with `HND-01` and the sign-off time.

## 6. Check Langfuse

In the Langfuse app: **Sessions**, search for `CLM-1011:<run_id>` (the run id is in `$run.run_id`). Or through the API:

```powershell
$auth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($env:LANGFUSE_PUBLIC_KEY):$($env:LANGFUSE_SECRET_KEY)"))
$from = (Get-Date).ToUniversalTime().AddHours(-1).ToString("o")
$obs  = (Invoke-RestMethod "$env:LANGFUSE_BASE_URL/api/public/v2/observations?fields=core,basic&limit=1000&fromStartTime=$from" -Headers @{ Authorization = $auth }).data
$obs | Where-Object sessionId -eq "CLM-1011:$($run.run_id)" |
  Group-Object traceId | ForEach-Object { [pscustomobject]@{ trace = $_.Name.Substring(0,8); observations = $_.Count; start = ($_.Group.startTime | Sort-Object)[0] } }
```

Expect two traces: the work up to the decision, and the payment after the sign-off. Traces can take a minute to show. This organization can't use the legacy `/api/public/traces`; use `/api/public/v2/observations`.

## Optional: kill and carry on

1. Start a run as in step 3 on a claim that is still waiting, such as CLM-1012. When its events show a few steps, press **Ctrl+C** in terminal A.
2. Check that nothing is still listening; this should print nothing:
   ```powershell
   Get-NetTCPConnection -LocalPort 8000,8002 -State Listen -ErrorAction SilentlyContinue
   ```
   If something is listed, `Stop-Process -Id <OwningProcess> -Force`.
3. `npm run dev` again. The service carries the claim on in the same run: same attempt, more checkpoints, and a new trace in its Langfuse session.

## Optional: a queue run

```powershell
$q = Invoke-RestMethod -Method Post "$B/api/runs" -Headers $H -ContentType "application/json" -Body '{"cap": 5}'
do { Start-Sleep 15; $s = Invoke-RestMethod "$B/api/queue-runs/$($q.run_id)" -Headers $H; $s.status } while ($s.status -in "running","stopping")
$s.summary
```

About 15 to 20 minutes from this machine, for a few cents.

## Notes

- On Windows, `uvicorn --reload` can print "Reloading" after a backend change and keep serving the old code. Restart `npm run dev` after editing the backend.
- From this machine every round trip to the database in Seoul takes about 230 ms, so claims and sign-offs are slower than they will be in-region (`docs/STATUS.md`).
