# Computer use on this Windows desktop with the one loop (cu_stack/loop.py in computer-use-stack): each step the fast
# decision model (SubQ, TYPESAFE_* in .env) picks first, and Claude reads the screenshot and acts when it is unsure.
# Claude keeps notes across steps and is warned when it repeats itself. The goal is plain English.
#   desk-goal.ps1 'In Calculator, compute 24*60*60' [--act] [--steps=30] [--model=opus]
# Without --act it is a dry run (one capture and one decision, nothing pressed). Stop a live run with Ctrl-C or the
# mouse in the top-left corner. Logs: runs\loop\<run>\loop.jsonl in this repo. Keys: .env in this repo (git-ignored).
# --model picks Claude's model (default sonnet); effort is medium (scripted Claude calls go no higher). Without
# TYPESAFE_API_KEY in .env the fast model is skipped and Claude decides every step.
param([Parameter(Position = 0)][string]$Goal, [Parameter(ValueFromRemainingArguments = $true)]$Rest)

$Repo = Split-Path $PSScriptRoot -Parent
$env:CLICKER_WRITER_API = 'claude-code'
$env:CLICKER_ANSWER_REASONING = 'medium'
$a = @($Goal)
foreach ($r in $Rest) {
    if ($r -like '--model=*') { $env:CLICKER_ANSWER_MODEL = $r.Substring(8) } else { $a += $r }
}
$envFile = Join-Path $Repo '.env'
if ((Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^TYPESAFE_API_KEY=.' -Quiet)) { $a += '--fast' }
else { Write-Warning 'No TYPESAFE_API_KEY in .env: Claude decides every step (slower).' }
$env:VIRTUAL_ENV = $null  # a caller's venv would make uv warn and ignore the project's
Set-Location $Repo
uv run --project $Repo python -m cu_stack.loop @a
exit $LASTEXITCODE
