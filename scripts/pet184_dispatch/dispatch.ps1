<#
PET-184 dispatch runner.

Replaces the prose mechanics that lived in spec Decisions 3, 4 and 6. The spec
keeps the what-and-why; this file is the how, because the how is a program and
prose review cannot check a marker schema, a meta schema and a manifest join key
against each other.

Two dispatch kinds behind one contract:
  codex  -> node <codex.js> exec ... -o <stem>.json      (the primary reviewer)
  http   -> POST {base_url}/chat/completions             (the Decision 3 fallback)

Also owned here, not in prose:
  Resolve-FallbackTarget  Decision 3 / Design step 0d: per-target credential,
                          LM Studio warm-up, byte ceiling, and the deadline probe
  Get-FallbackDeadline    scales the probe to a part's bytes, floored at the primary
  Add-AttemptRecord /     the Decision 4 retry ledger (attempts.json), contract in
  Get-AttemptsSpent       attempts.schema.json

Both write the SAME four-file stem plus an in-flight marker:
  <stem>.json        the reviewer's last message (codex -o, or choices[0].message.content)
  <stem>.meta.json   the completion sentinel and audit record (meta.schema.json)
  <stem>.log         console transcript, or the HTTP envelope
  <stem>.stderr.txt  stderr, or the transport error -- ALWAYS created, empty if clean

Run the self-test to exercise every mechanic without codex auth or LM Studio:
  powershell -NoProfile -File dispatch.ps1 -SelfTest

--------------------------------------------------------------------------
MACHINE DEPENDENCIES -- read this before running on a new box.
--------------------------------------------------------------------------
This runner is an internal ops tool, NOT part of the published `petasos`
package. `pyproject.toml` has no [tool.hatch.build] section, so hatchling
packages `petasos/` only and nothing here ships to PyPI. It therefore does
NOT carry the "runs on any deployment and hardware" obligation a Petasos
feature carries. It is pinned to one developer workstation on purpose, and
every pin is listed here so the next person migrating it knows the full set
rather than discovering them one failure at a time.

  1. Windows + Windows PowerShell 5.1. Not PowerShell 7, not POSIX. The
     script relies on 5.1 behaviours that 7 changed: Invoke-WebRequest
     throwing on non-2xx (the catch block recovers the real status), and
     $r.Content decoding to ISO-8859-1 without a charset. Both are handled;
     both handlings become wrong under 7.
  2. The codex entrypoint is hard-coded at line ~1690:
       $env:APPDATA\npm\node_modules\@openai\codex\bin\codex.js
     invoked through `node`, NOT through the `codex` command. `codex` is an
     npm shim with no .exe, and Start-Process -FilePath codex with
     redirection throws "%1 is not a valid Win32 application". A global npm
     prefix elsewhere, or a non-global codex install, breaks this path. The
     -FakeCodexJs parameter overrides it (self-test only).
  3. The local fallback assumes LM Studio serving an OpenAI-compatible API
     on http://127.0.0.1:1234/v1, and reads LM Studio's PROPRIETARY
     /api/v0/models endpoint for `loaded_context_length`. A different local
     server will not expose that field and Resolve-FallbackTarget will
     record the target unusable.
  4. The hosted fallback's credential is read from Hermes profile .env
     files under $env:LOCALAPPDATA\hermes\profiles\{gibson,ops}\.env. Those
     paths are a KEY LOCATION and nothing more -- see Get-FallbackTargets.
  5. `python` must be on PATH for schema validation (validate.py). Missing
     python throws; it never fails open.

The self-test covers every mechanic above with stubs, so `-SelfTest` passing
on a new box proves the LOGIC survived the move. It does NOT prove items 2,
3 or 4 resolve there; those are live-path facts that Design step 0c/0d
probe at run time.
#>

[CmdletBinding()]
param(
  [ValidateSet('codex','http')] [string] $Kind,
  [string]   $Area,
  [string[]] $Units,
  [ValidateSet('first','resplit','requote','contest','readjudicate','fallback','sanity')]
  [string]   $Pass = 'first',
  [string]   $Model,
  [string]   $PromptPath,
  [int]      $DeadlineSeconds = 900,
  [int]      $Attempt = 1,
  [int]      $RetriesSpent = 0,
  [string]   $ReportDir,
  [string]   $Cwd,
  [string]   $ReasoningEffort = 'high',
  [string]   $BaseUrl,
  [string]   $ApiKey,
  [int]      $MaxTokens = 0,           # http kind: completion budget (max_tokens). 0 = unset.
                                       # The fix for the measured 32,474-reasoning-token,
                                       # zero-content dispatch on the thinking fallback.
  [int]      $ReasoningMaxTokens = 0,  # http kind: reasoning budget (reasoning.max_tokens,
                                       # OpenRouter convention). 0 = unset.
  [switch]   $Smoke,          # route the stem under raw/smoke/ (smoke passes 1 and 3,
                              # and the negative control) so manifest.py excludes them
  [switch]   $SelfTest,
  [string]   $FakeCodexJs      # self-test only: stand-in for codex.js
)

# Dot-sourcing must NOT mutate the caller's session. A helper that silently flips
# StrictMode / $ErrorActionPreference under a host script is a debugging trap for
# exactly the resume-path caller this file is meant to serve.
$script:DotSourced = ($MyInvocation.InvocationName -eq '.')

if (-not $script:DotSourced) {
  Set-StrictMode -Version Latest
  $ErrorActionPreference = 'Stop'
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
}
# TLS is process-wide and idempotent; needed by any caller that dispatches.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $ReportDir) {
  # NO $PSScriptRoot fallback for a real dispatch. This runner is COMMITTED under
  # scripts/, while its output is not: raw reviewer text, prompt copies and
  # attempts.json belong in the gitignored run directory. Defaulting -ReportDir to
  # the script's own folder -- which is what this line used to do, back when the
  # tool and the run shared one gitignored directory -- would now write every run
  # artifact into a TRACKED path and silently break the payload fence that keeps
  # this ticket non-shipping. Fail loudly instead.
  #
  # The two schema families are deliberately NOT symmetric about this:
  #   marker/meta/attempts.schema.json  travel with the TOOL   -> $PSScriptRoot
  #   schema.json (reviewer contract)   belongs to the RUN     -> $ReportDir
  if ($SelfTest -or $script:DotSourced) {
    # Neither writes run artifacts here; both only need a root for schema lookup.
    $ReportDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
  } else {
    throw "-ReportDir is required. It is the gitignored run directory (docs/research/<date>-pet-184-cross-model-release-review/), never this script's directory."
  }
}

# ---------------------------------------------------------------- primitives

function Write-Utf8NoBom {
  <# BOM-less (manifest.py reads these with Python's json) and atomic
     (a torn .meta.json is worse than a missing one: the resume path fires on
     its existence, so a truncated sentinel is neither classifiable nor
     recoverable). The temp name is unique per writer -- the orchestrator-side
     kill and a revived launching shell must never share one. #>
  param([string]$Path, [string]$Text)
  $tmp = "$Path.$PID.$([guid]::NewGuid().ToString('N')).tmp"
  [System.IO.File]::WriteAllText($tmp, $Text, [System.Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Read-Utf8 {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
}

function Get-ObjProp {
  <# StrictMode-safe optional-property read on a PSCustomObject or IDictionary.
     External JSON (LM Studio's /api/v0/models, OpenRouter's /models) does not
     promise a field set, and under StrictMode a missing property THROWS. #>
  param($o, [string]$n)
  if ($null -eq $o) { return $null }
  if ($o -is [System.Collections.IDictionary]) {
    if ($o.Contains($n)) { return $o[$n] } else { return $null }
  }
  if ($null -ne $o.PSObject.Properties[$n]) { return $o.PSObject.Properties[$n].Value }
  $null
}

# ------------------------------------------------------------- schema checks

$script:PythonExe = 'C:\python310\python.exe'   # has jsonschema 4.26.0
$script:ReportDir = $ReportDir                  # for callers that omit -SchemaValidator

function Test-AgainstSchema {
  <# Returns @{ valid; errors }. PS 5.1 has no Test-Json -Schema (6.1+), so the
     validator is validate.py. This is what makes marker.schema.json and
     meta.schema.json enforced contracts rather than documentation that happens
     to live in .json files. #>
  param([string]$SchemaPath,[string]$Json)
  if (-not (Test-Path -LiteralPath $script:PythonExe)) {
    # THROW, never skip-as-valid: a validator that fails open turns every
    # schema gate into a silent false-clean, the design's named worst failure.
    throw "schema validation unavailable: $($script:PythonExe) not found (needed for $SchemaPath)."
  }
  $vp = Join-Path (Split-Path -Parent $SchemaPath) 'validate.py'
  if (-not (Test-Path -LiteralPath $vp)) { $vp = Join-Path $PSScriptRoot 'validate.py' }
  $tmp = Join-Path $env:TEMP ("pet184-val-$([guid]::NewGuid().ToString('N')).json")
  [System.IO.File]::WriteAllText($tmp, $Json, [System.Text.UTF8Encoding]::new($false))
  try {
    $out = & $script:PythonExe $vp $SchemaPath $tmp 2>&1
    @{ valid = ($LASTEXITCODE -eq 0); errors = @($out) }
  } finally { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
}

function New-SchemaValidator {
  <# The default for Get-DispatchClass's -SchemaValidator. Without a default,
     omitting it makes every healthy response fall to rule 4 -- the whole-run
     failure mode, one layer up from round 6's null ExitCode. Missing python is
     a THROW, not a skip: the schema-valid predicate failing OPEN is a silent
     false-clean, this design's named worst failure. #>
  param([string]$ReportDir)
  if (-not (Test-Path -LiteralPath $script:PythonExe)) {
    throw "schema validator unavailable: $($script:PythonExe) not found. The schema-valid predicate must not fail open (silent false-clean); install python+jsonschema or pass -SchemaValidator explicitly."
  }
  $schemaPath = Join-Path $ReportDir 'schema.json'
  { param($t) (Test-AgainstSchema -SchemaPath $schemaPath -Json $t).valid }.GetNewClosure()
}

function ConvertTo-StemSlug {
  # '/' and other path-illegal characters -> '-'  (qwen/qwen3.8-27b -> qwen-qwen3.8-27b)
  param([string]$Value)
  ($Value -replace '[\\/:*?"<>|]', '-')
}

function Get-Stamp { (Get-Date).ToString('yyyyMMddTHHmmssfff') }   # colon-free: filenames
function Get-Iso   { param($d = (Get-Date)) ([datetime]$d).ToString('o') }  # parseable: documents

function Get-SchemaHash {
  param([string]$ReportDir)
  (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $ReportDir 'schema.json')).Hash
}

function New-Stem {
  param([string]$ReportDir,[string]$Area,[string[]]$Units,[string]$Pass,[string]$Model,[switch]$Smoke)
  # <subprobe-or-part> is the single unit, or the literal 'all' for a whole-area dispatch.
  $token = if ($Units.Count -eq 1) { $Units[0] } else { 'all' }
  $root  = if ($Smoke) { Join-Path $ReportDir 'raw\smoke' } else { Join-Path $ReportDir 'raw' }
  Join-Path $root ("{0}.{1}.{2}.{3}.{4}" -f $Area, $token, $Pass, (ConvertTo-StemSlug $Model), (Get-Stamp))
}

# ------------------------------------------------------------------- records

function New-InvocationString {
  <# The audit `invocation` field, minted in ONE place. It must carry the escaped
     model_reasoning_effort=\"...\" substring: Decision 6's smoke assertion reads
     it back from .meta.json, and the orphan path recovers reasoning_effort by
     parsing it -- an invocation without it fails a whole-ticket-halt gate on a
     healthy stack and degrades every codex orphan to reasoning_effort 'unknown'. #>
  param([string]$Kind,[string]$Model,[string]$Cwd,[string]$ReasoningEffort,[string]$BaseUrl)
  if ($Kind -eq 'codex') {
    "exec -m $Model --sandbox read-only -C $Cwd -c model_reasoning_effort=\`"$ReasoningEffort`\`""
  } else {
    "POST $($BaseUrl.TrimEnd('/'))/chat/completions"
  }
}

function Copy-PromptToStem {
  <# § Files: the prompt file is named from the stem leaf (prompts/<stem-leaf>.md)
     so it inherits every disambiguating component. The stem's timestamp exists
     only at mint time, so the RUNNER produces this file by copying the caller's
     -PromptPath -- the caller cannot pre-name it. Byte copy: the encoding
     discipline is not re-entered here. #>
  param([string]$PromptPath,[string]$Stem,[string]$ReportDir)
  $dir = Join-Path $ReportDir 'prompts'
  if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $dest = Join-Path $dir ((Split-Path -Leaf $Stem) + '.md')
  if ($PromptPath -ne $dest) { Copy-Item -LiteralPath $PromptPath -Destination $dest -Force }
  $dest
}

function New-MarkerObject {
  <# The canonical marker, built ONCE and reused for the pre-launch and
     post-launch writes, so the two can never drift. Shape is enforced by
     marker.schema.json. #>
  param(
    [string]$Kind,[string]$Stem,[string]$Area,[string[]]$Units,[string]$Pass,
    [string]$Model,[string]$PromptPath,[string]$Invocation,
    [string]$ReportDir,[string]$SchemaHash,
    [int]$DeadlineSeconds,[int]$Attempt,[int]$RetriesSpent,[string]$BaseUrl
  )
  $m = [ordered]@{
    kind            = $Kind
    stem            = $Stem
    area            = $Area
    units           = @($Units)
    pass            = $Pass
    expected_units  = $Units.Count
    model           = $Model
    prompt_path     = $PromptPath
    output_path     = "$Stem.json"
    invocation      = $Invocation
    schema_path     = (Join-Path $ReportDir 'schema.json')
    schema_sha256   = $SchemaHash
    pid             = $null
    startTime       = $null
    dispatchedAt    = (Get-Iso)
    deadlineSeconds = $DeadlineSeconds
    attempt         = $Attempt
    retriesSpent    = $RetriesSpent
  }
  if ($Kind -eq 'http') { $m['base_url'] = $BaseUrl }
  $m
}

function New-MetaObject {
  # Shape enforced by meta.schema.json. Superset of the marker's audit fields.
  param([hashtable]$Marker,$Exit,[bool]$TimedOut,[bool]$Orphaned,$Seconds,[hashtable]$Extra)

  # Carry the kind-conditional fields the schema requires. Without this the
  # orphan path (which passes no -Extra) writes a record that fails its own
  # contract: codex orphans lose reasoning_effort/sandbox/cwd, http orphans lose
  # base_url/http_status -- and base_url is sitting right there on the marker.
  if (-not $Extra) { $Extra = @{} }
  if ($Marker.kind -eq 'http') {
    if (-not $Extra.ContainsKey('base_url'))      { $Extra['base_url']      = $Marker.base_url }
    if (-not $Extra.ContainsKey('http_status'))   { $Extra['http_status']   = $null }
    if (-not $Extra.ContainsKey('finish_reason')) { $Extra['finish_reason'] = $null }
  } else {
    # Recoverable from the marker's invocation string, which pins them.
    if (-not $Extra.ContainsKey('reasoning_effort')) {
      $m = [regex]::Match([string]$Marker.invocation, 'model_reasoning_effort=\\?"?([a-z]+)')
      $Extra['reasoning_effort'] = if ($m.Success) { $m.Groups[1].Value } else { 'unknown' }
    }
    if (-not $Extra.ContainsKey('sandbox')) {
      $m = [regex]::Match([string]$Marker.invocation, '--sandbox\s+(\S+)')
      $Extra['sandbox'] = if ($m.Success) { $m.Groups[1].Value } else { 'unknown' }
    }
    if (-not $Extra.ContainsKey('cwd')) {
      $m = [regex]::Match([string]$Marker.invocation, '-C\s+(\S+)')
      $Extra['cwd'] = if ($m.Success) { $m.Groups[1].Value } else { 'unknown' }
    }
  }

  $o = [ordered]@{
    kind           = $Marker.kind
    stem           = $Marker.stem
    area           = $Marker.area
    units          = @($Marker.units)
    pass           = $Marker.pass
    expected_units = $Marker.expected_units
    model          = $Marker.model
    prompt_path    = $Marker.prompt_path
    output_path    = $Marker.output_path
    invocation     = $Marker.invocation
    schema_path    = $Marker.schema_path
    schema_sha256  = $Marker.schema_sha256
    exit           = $Exit          # integer or null -- NEVER a string
    timed_out      = $TimedOut
    orphaned       = $Orphaned
    seconds        = $Seconds
    dispatched_at  = $Marker.dispatchedAt
  }
  if ($Extra) { foreach ($k in $Extra.Keys) { $o[$k] = $Extra[$k] } }
  $o
}

function Write-Marker { param([string]$Path,$Obj) Write-Utf8NoBom $Path ($Obj | ConvertTo-Json -Depth 12) }

function Remove-Marker {
  # Never silently swallowed: a surviving marker causes a completed dispatch to
  # be re-classified on the next resume, double-charging the retry budget.
  param([string]$Path)
  for ($i = 0; $i -lt 3; $i++) {
    try { Remove-Item -LiteralPath $Path -ErrorAction Stop; return $true } catch { Start-Sleep -Milliseconds 150 }
  }
  Write-Warning "marker not deleted: $Path"
  $false
}

# ------------------------------------------------------------------ dispatch

function Invoke-CodexDispatch {
  param([hashtable]$Marker,[string]$MarkerPath,[string]$CodexJs,[string]$Cwd,[string]$ReasoningEffort)

  $stem = $Marker.stem
  $t0   = Get-Date

  # Set HERE, not at script scope: the launching shell IS the dispatching shell, and
  # a codex run that loses this can block on the interactive stdin prompt and present
  # as a hung job that burns the whole deadline (codex/SKILL.md:24).
  $env:CODEX_NON_INTERACTIVE = '1'

  Write-Marker $MarkerPath $Marker          # pre-launch: pid/startTime null, everything else real

  $argList = @(
    $CodexJs,
    'exec','-m',$Marker.model,'--sandbox','read-only',
    '-C',$Cwd,
    '-c',"model_reasoning_effort=\`"$ReasoningEffort\`"",   # escaped: -ArgumentList strips bare quotes
    '--output-schema',$Marker.schema_path,
    '-o',"$stem.json",'-'
  )

  $p = Start-Process -FilePath node -PassThru -NoNewWindow `
        -ArgumentList $argList `
        -RedirectStandardInput  $Marker.prompt_path `
        -RedirectStandardOutput "$stem.log" `
        -RedirectStandardError  "$stem.stderr.txt"

  $null = $p.Handle                          # REQUIRED before WaitForExit, else ExitCode is null
  $Marker.pid       = $p.Id
  $Marker.startTime = Get-Iso $p.StartTime
  Write-Marker $MarkerPath $Marker           # post-launch: real identity

  $timedOut = -not $p.WaitForExit($Marker.deadlineSeconds * 1000)
  if ($timedOut) { try { $p.Kill($true) } catch { try { $p.Kill() } catch { } } ; $null = $p.WaitForExit(15000) }

  $meta = New-MetaObject -Marker $Marker -Exit $p.ExitCode -TimedOut $timedOut -Orphaned $false `
            -Seconds ((Get-Date) - $t0).TotalSeconds `
            -Extra @{ reasoning_effort = $ReasoningEffort; sandbox = 'read-only'; cwd = $Cwd }
  Write-Utf8NoBom "$stem.meta.json" ($meta | ConvertTo-Json -Depth 12)
  Remove-Marker $MarkerPath | Out-Null
  $meta
}

function New-HttpRequestBody {
  <# The chat-completions request body, built in one place so the token-budget
     fields cannot silently diverge between the dispatch path and the step-0d
     probe. -MaxTokens exists because the configured fallback is a THINKING
     model: measured live, an unbudgeted trivial prompt returned 200 with
     finish_reason='length', 32,474 reasoning tokens, and ZERO content. A null
     -SchemaObj omits response_format (the warm-up probe needs no schema). #>
  param([string]$Model,[string]$PromptText,$SchemaObj,[int]$MaxTokens = 0,[int]$ReasoningMaxTokens = 0)
  $b = [ordered]@{ model = $Model; temperature = 0 }
  if ($null -ne $SchemaObj) {
    $b['response_format'] = @{ type = 'json_schema'
                               json_schema = @{ name = 'petasos_review'; strict = $true; schema = $SchemaObj } }
  }
  $b['messages'] = @(@{ role = 'user'; content = $PromptText })
  if ($MaxTokens -gt 0)          { $b['max_tokens'] = $MaxTokens }
  if ($ReasoningMaxTokens -gt 0) { $b['reasoning']  = @{ max_tokens = $ReasoningMaxTokens } }
  $b | ConvertTo-Json -Depth 40 -Compress
}

function Invoke-HttpDispatch {
  param([hashtable]$Marker,[string]$MarkerPath,[string]$ApiKey,[int]$MaxTokens = 0,[int]$ReasoningMaxTokens = 0)

  $stem = $Marker.stem
  $t0   = Get-Date

  # pid is THIS shell: an http dispatch owns no child, and the poller still needs a target.
  $Marker.pid       = $PID
  $Marker.startTime = Get-Iso (Get-Process -Id $PID).StartTime
  Write-Marker $MarkerPath $Marker

  # Request-direction read is pinned UTF-8: this is the fifth encoding surface,
  # and it is on the send side where nothing downstream can detect a mojibake.
  $promptText = Read-Utf8 $Marker.prompt_path
  $schemaObj  = (Read-Utf8 $Marker.schema_path) | ConvertFrom-Json

  $body = New-HttpRequestBody -Model $Marker.model -PromptText $promptText -SchemaObj $schemaObj `
            -MaxTokens $MaxTokens -ReasoningMaxTokens $ReasoningMaxTokens

  $headers = @{}
  if ($ApiKey) { $headers['Authorization'] = "Bearer $ApiKey" }

  $timedOut = $false; $envelope = ''; $stderrText = ''
  try {
    $r = Invoke-WebRequest -Uri "$($Marker.base_url)/chat/completions" -Method Post -Headers $headers `
           -ContentType 'application/json; charset=utf-8' `
           -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
           -TimeoutSec $Marker.deadlineSeconds -UseBasicParsing
    $status = [int]$r.StatusCode
    $r.RawContentStream.Position = 0
    $envelope = (New-Object IO.StreamReader($r.RawContentStream, [Text.UTF8Encoding]::new($false))).ReadToEnd()
  } catch {
    # PS 5.1 throws on EVERY non-2xx and has no -SkipHttpErrorCheck, so the real
    # status is reachable only here. Flattening it to 599 would make a 400, a 401,
    # a 429 and a dropped socket indistinguishable in the audit record.
    $resp = $null
    if ($_.Exception.PSObject.Properties.Name -contains 'Response') { $resp = $_.Exception.Response }
    if ($resp) {
      $status   = [int]$resp.StatusCode
      $envelope = (New-Object IO.StreamReader($resp.GetResponseStream(), [Text.UTF8Encoding]::new($false))).ReadToEnd()
    } else {
      $status   = 599        # transport error ONLY
      $timedOut = ($_.Exception -is [Net.WebException]) -and ($_.Exception.Status -eq 'Timeout')
    }
    $stderrText = $_.Exception.Message
  }

  # All four files, on every path. .stderr.txt written unconditionally: a healthy
  # 2xx must not fail a four-file assertion.
  Write-Utf8NoBom "$stem.stderr.txt" $stderrText
  Write-Utf8NoBom "$stem.log" $envelope
  $content = ''; $finishReason = $null; $reasoningTokens = $null
  if ($envelope) {
    try {
      $j = $envelope | ConvertFrom-Json
      $content      = $j.choices[0].message.content
      $finishReason = $j.choices[0].finish_reason
      if ($j.PSObject.Properties['usage'] -and $j.usage.PSObject.Properties['completion_tokens_details']) {
        $reasoningTokens = $j.usage.completion_tokens_details.reasoning_tokens
      }
    } catch { $content = '' }
  }
  Write-Utf8NoBom "$stem.json" $content     # analogue of codex's -o file, NOT the envelope

  $meta = New-MetaObject -Marker $Marker `
            -Exit $(if ($status -ge 200 -and $status -lt 300) { 0 } else { $status }) `
            -TimedOut $timedOut -Orphaned $false -Seconds ((Get-Date) - $t0).TotalSeconds `
            -Extra @{ base_url = $Marker.base_url; http_status = $status
                      finish_reason = $finishReason; reasoning_tokens = $reasoningTokens
                      max_tokens = $(if ($MaxTokens -gt 0) { $MaxTokens } else { $null })
                      reasoning_max_tokens = $(if ($ReasoningMaxTokens -gt 0) { $ReasoningMaxTokens } else { $null }) }
  Write-Utf8NoBom "$stem.meta.json" ($meta | ConvertTo-Json -Depth 12)
  Remove-Marker $MarkerPath | Out-Null
  $meta
}

# --------------------------------- fallback resolution (Decision 3 / step 0d)

function Read-EnvValue {
  <# Minimal .env reader: first `NAME=value` line wins, surrounding quotes
     stripped, comment lines never match (the '#' is not whitespace, so the
     anchored name cannot start a commented line). Returns $null when the file
     or the key is absent -- absence is a RESULT here (it is what marks a
     target unusable), never an error. #>
  param([string]$Path,[string]$Name)
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $null }
  foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
    if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.+?)\s*$')) {
      return $Matches[1].Trim('"').Trim("'")
    }
  }
  $null
}

function Invoke-JsonGet {
  # GET + parse, PS 5.1-safe. Never throws: @{ ok; json; status; error }.
  param([string]$Uri,[hashtable]$Headers = @{},[int]$TimeoutSec = 30)
  try {
    $r = Invoke-WebRequest -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec -UseBasicParsing
    @{ ok = $true; json = ($r.Content | ConvertFrom-Json); status = [int]$r.StatusCode; error = $null }
  } catch {
    $status = 599
    if ($_.Exception.PSObject.Properties.Name -contains 'Response' -and $_.Exception.Response) {
      $status = [int]$_.Exception.Response.StatusCode
    }
    @{ ok = $false; json = $null; status = $status; error = $_.Exception.Message }
  }
}

function Get-FallbackTargets {
  <# Decision 3's qualifying targets, in promotion order.

     A TARGET IS A MODEL ENDPOINT, NOT A HERMES PROFILE. Earlier revisions
     named these 'discord' and 'bard' after the Hermes profiles whose config
     supplied the base_url and the model ID. That was a category error with a
     live hazard attached: `discord` is a delivery-channel profile and `bard`
     is a Serenade songwriting profile, neither is a reviewer, and nothing
     about either persona is used here -- no system prompt, no profile config
     beyond the two coordinates below. Worse, naming them coupled the review's
     reproducibility to two unrelated profiles: retuning `bard`'s songwriting
     model would have silently changed which model reviews the release.

     So targets are named for what they are. The Hermes profile paths survive
     ONLY as the filesystem location of an API key file, which is a fact about
     this box (see MACHINE DEPENDENCIES, item 4) and not a role assignment.
     The credential detail is still load-bearing: OPENROUTER_API_KEY lives in
     gibson's and ops' .env, and never in the .env of whatever profile happens
     to name minimax as its default. #>
  $profiles = Join-Path $env:LOCALAPPDATA 'hermes\profiles'
  @(
    @{ name = 'local-qwen3.8-27b'; kind = 'lmstudio'
       base_url = 'http://127.0.0.1:1234/v1'; model = 'qwen/qwen3.8-27b'
       key_env = $null; key_files = @() },
    @{ name = 'openrouter-minimax-m3'; kind = 'openrouter'
       base_url = 'https://openrouter.ai/api/v1'; model = 'minimax/minimax-m3'
       key_env = 'OPENROUTER_API_KEY'
       key_files = @((Join-Path $profiles 'gibson\.env'), (Join-Path $profiles 'ops\.env')) }
  )
}

function Resolve-FallbackTarget {
  <# Design step 0d: resolve ONE Decision 3 target to a usable/unusable record,
     BEFORE any dispatch. This is the producer for what were five prose-only
     consumers: the per-target credential, the LM Studio warm-up, the byte
     ceiling, the deadline probe ($fbDeadline's source), and the report-header
     record. A target that fails any step is recorded unusable UP FRONT with its
     reason and is skipped without consuming a fallback hop -- never dispatched
     into a 401 (which rule 2b/1c cannot name and rule 1b would misattribute as
     infrastructure).

     Order per target: credential -> models endpoint (presence) -> warm-up
     completion (LM Studio loads on demand; measured live, and this round trip
     IS the deadline probe) -> ceiling from the LOADED context length. The
     ceiling reads loaded_context_length, never max_context_length: the
     architectural maximum (262144) converts to ~589 KB, above the primary's
     ceiling, so the re-split would never fire and a 250 KB payload would be
     silently truncated into a false-clean. #>
  param(
    [Parameter(Mandatory)][hashtable]$Target,
    [int]$PrimaryCeilingBytes = 250000,
    [int]$MinCeilingBytes     = 4096,   # fixed per-part overhead: preamble + bullet list + topics
    [int]$ProbeMaxTokens      = 512,    # measured: 512 gives finish_reason 'stop' with content
                                        # on the thinking model where 64 gives 'length' and nothing
    [int]$ProbeTimeoutSec     = 600
  )

  $out = [ordered]@{
    name = $Target.name; kind = $Target.kind; base_url = $Target.base_url; model = $Target.model
    usable = $false; reason = $null
    api_key = $null; key_source = $null
    context_tokens = $null; ceiling_bytes = $null
    probe_seconds = $null; probe_bytes = $null; probe_finish_reason = $null
    resolved_at = (Get-Iso)
  }

  function Get-CeilingBytes([long]$CtxTokens) {
    # 3 bytes/token with a 25% headroom reserve, never above the primary's ceiling.
    [int][math]::Min([math]::Floor($CtxTokens * 3 * 0.75), $PrimaryCeilingBytes)
  }
  function Find-ModelEntry($Json,[string]$Id) {
    foreach ($e in @((Get-ObjProp $Json 'data'))) { if ((Get-ObjProp $e 'id') -eq $Id) { return $e } }
    $null
  }

  # 1) credential -- resolved from the named .env files, never assumed. Returns
  #    before any network I/O, so a keyless target costs nothing to skip.
  if ($Target.key_env) {
    foreach ($f in @($Target.key_files)) {
      $v = Read-EnvValue -Path $f -Name $Target.key_env
      if ($v) { $out.api_key = $v; $out.key_source = $f; break }
    }
    if (-not $out.api_key) {
      $out.reason = "no credential: $($Target.key_env) not found in " + (@($Target.key_files) -join ', ')
      return $out
    }
  }

  $headers = @{}
  if ($out.api_key) { $headers['Authorization'] = "Bearer $($out.api_key)" }

  # 2) model presence, and (openrouter) the context length, from the ceiling endpoint.
  $modelsUri = if ($Target.kind -eq 'lmstudio') {
    ($Target.base_url -replace '/v1/?$','') + '/api/v0/models'   # the native endpoint; /v1/models has no context field
  } else {
    ($Target.base_url.TrimEnd('/')) + '/models'
  }
  $g = Invoke-JsonGet -Uri $modelsUri -Headers $headers
  if (-not $g.ok) { $out.reason = "models endpoint unreachable ($($g.status)): $($g.error)"; return $out }
  $entry = Find-ModelEntry $g.json $Target.model
  if (-not $entry) { $out.reason = "model $($Target.model) not served at $modelsUri"; return $out }

  if ($Target.kind -eq 'openrouter') {
    $ctx = Get-ObjProp $entry 'context_length'
    if (-not $ctx) { $out.reason = "models endpoint reports no context_length for $($Target.model)"; return $out }
    $out.context_tokens = [long]$ctx
    $out.ceiling_bytes  = Get-CeilingBytes ([long]$ctx)
    if ($out.ceiling_bytes -lt $MinCeilingBytes) {
      $out.reason = "resolved ceiling $($out.ceiling_bytes) B is below the per-part overhead ($MinCeilingBytes B)"
      return $out
    }
  }

  # 3) warm-up + deadline probe, one round trip serving both: LM Studio loads a
  #    not-loaded model on the first completion (measured live), and the timing
  #    is the probe Get-FallbackDeadline scales.
  $probeBody = New-HttpRequestBody -Model $Target.model -PromptText 'Reply with exactly: OK' -SchemaObj $null -MaxTokens $ProbeMaxTokens
  $t0 = Get-Date
  try {
    $pr = Invoke-WebRequest -Uri ($Target.base_url.TrimEnd('/') + '/chat/completions') -Method Post -Headers $headers `
            -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($probeBody)) -TimeoutSec $ProbeTimeoutSec -UseBasicParsing
    $pj = $pr.Content | ConvertFrom-Json
    $ch = @((Get-ObjProp $pj 'choices'))
    if ($ch.Count -gt 0) { $out.probe_finish_reason = Get-ObjProp $ch[0] 'finish_reason' }
  } catch {
    $status = 599
    if ($_.Exception.PSObject.Properties.Name -contains 'Response' -and $_.Exception.Response) {
      $status = [int]$_.Exception.Response.StatusCode
    }
    $out.reason = "warm-up/probe failed ($status): $($_.Exception.Message)"
    return $out
  }
  $out.probe_seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 3)
  $out.probe_bytes   = [Text.Encoding]::UTF8.GetByteCount($probeBody)

  # 4) LM Studio: the ceiling exists only AFTER the warm-up, and only from the
  #    loaded state.
  if ($Target.kind -eq 'lmstudio') {
    $g2 = Invoke-JsonGet -Uri $modelsUri -Headers $headers
    if (-not $g2.ok) { $out.reason = "models endpoint unreachable after warm-up ($($g2.status))"; return $out }
    $entry2 = Find-ModelEntry $g2.json $Target.model
    $state  = Get-ObjProp $entry2 'state'
    $loaded = Get-ObjProp $entry2 'loaded_context_length'
    if ($state -ne 'loaded' -or -not $loaded) {
      $out.reason = "state=$state after warm-up; loaded_context_length unavailable"
      return $out
    }
    $out.context_tokens = [long]$loaded
    $out.ceiling_bytes  = Get-CeilingBytes ([long]$loaded)
    if ($out.ceiling_bytes -lt $MinCeilingBytes) {
      $out.reason = "resolved ceiling $($out.ceiling_bytes) B is below the per-part overhead ($MinCeilingBytes B)"
      return $out
    }
  }

  $out.usable = $true
  $out
}

function Get-FallbackDeadline {
  <# Decision 3: the fallback deadline is the step-0d probe scaled by the ratio
     of part bytes to probe bytes, floored at the primary's deadline -- reusing
     Sol's figure would kill a healthy-but-slow local model and misattribute it
     as INFRASTRUCTURE_FAILURE. Capped at the Decision 4 measurement ceiling
     (3600 s): the probe includes the one-time model load, so naive scaling can
     project a multi-hour deadline that would let one hung fallback dispatch
     stall the whole sequential run. #>
  param([Parameter(Mandatory)]$Resolved,[Parameter(Mandatory)][long]$PartBytes,
        [int]$PrimaryDeadlineSeconds = 900,[int]$MaxSeconds = 3600)
  $pb = [double](Get-ObjProp $Resolved 'probe_bytes')
  $ps = [double](Get-ObjProp $Resolved 'probe_seconds')
  if ($pb -le 0) { return $PrimaryDeadlineSeconds }
  $scaled = [math]::Ceiling($ps * ($PartBytes / $pb))
  [int][math]::Min([math]::Max($PrimaryDeadlineSeconds, $scaled), $MaxSeconds)
}

function Get-FallbackReportRecord {
  <# The report-header copy of a resolved target. The raw api_key must never
     enter report.md: the report is the human-circulated artifact, and the key
     is a live credential. Shape-tolerant like Get-FallbackDeadline: accepts the
     live ordered dictionary AND a JSON-round-tripped PSCustomObject (a resumed
     session reads the record back from disk). #>
  param([Parameter(Mandatory)]$Resolved)
  $o = [ordered]@{}
  if ($Resolved -is [System.Collections.IDictionary]) {
    foreach ($k in @($Resolved.Keys)) { if ($k -ne 'api_key') { $o[$k] = $Resolved[$k] } }
  } else {
    foreach ($p in $Resolved.PSObject.Properties) { if ($p.Name -ne 'api_key') { $o[$p.Name] = $p.Value } }
  }
  $o['api_key_present'] = [bool](Get-ObjProp $Resolved 'api_key')
  $o
}

# ------------------------------------------- retry ledger (Decision 4)

function Read-AttemptsLedger {
  <# attempts.json -> nested hashtable. An unparseable ledger THROWS
     (halt-and-surface): a silently reset budget un-terminates the rule-4
     resplit loop, which is the exact failure the ledger exists to prevent. #>
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return @{} }
  $raw = Read-Utf8 $Path
  if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
  try { $j = $raw | ConvertFrom-Json } catch {
    throw "attempts.json unparseable at $Path -- halt and surface; never restart the budget from zero."
  }
  $h = @{}
  foreach ($p in $j.PSObject.Properties) {
    $h[$p.Name] = @{ spent = [int](Get-ObjProp $p.Value 'spent'); attempts = @((Get-ObjProp $p.Value 'attempts')) }
  }
  $h
}

function Get-AttemptsSpent {
  # Read before every dispatch. A missing key is zero -- first attempt.
  param([string]$Path,[string]$Key)
  $l = Read-AttemptsLedger $Path
  if ($l.ContainsKey($Key)) { [int]$l[$Key].spent } else { 0 }
}

function Test-ChargesRetry {
  <# Which Decision 4 classes consume the 2-retry budget. CLASSIFIER_TRIP spends
     fallback hops, not retries; AUTH_LAPSED and ENTITLEMENT_BLOCKED halt (both
     are permanent and need a human, so a retry can only waste budget);
     ACCEPTED/BLOCKED terminate. #>
  param([string]$Class)
  $Class -in @('INFRASTRUCTURE_FAILURE','TRUNCATED_OR_MALFORMED','UNGROUNDED_RESPONSE')
}

function Add-AttemptRecord {
  <# Written at classification time, AFTER the marker is cleared -- the ledger,
     not the marker, is what survives a session boundary. -Keys is the meta's
     `units` list: a whole-area dispatch charges every key it carried, and a
     resplit/requote part inherits its parent's spent count by recording under
     the same key. 'all' is a stem token, never a budget key. Atomic via
     Write-Utf8NoBom (tmp-then-rename). #>
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string[]]$Keys,
    [Parameter(Mandatory)][string]$Stem,
    [Parameter(Mandatory)][string]$Pass,
    [Parameter(Mandatory)][string]$Class,
    [Parameter(Mandatory)][string]$Rule,
    [Parameter(Mandatory)][bool]$Charge
  )
  if ('all' -in $Keys) {
    throw "'all' is a stem token, never a budget key: pass the enumerated units list (the marker/meta 'units' field)."
  }
  $l = Read-AttemptsLedger $Path
  $rec = [ordered]@{ stem = $Stem; pass = $Pass; class = $Class; rule = $Rule; charged = $Charge; at = (Get-Iso) }
  foreach ($k in $Keys) {
    if (-not $l.ContainsKey($k)) { $l[$k] = @{ spent = 0; attempts = @() } }
    if ($Charge) { $l[$k].spent = [int]$l[$k].spent + 1 }
    $l[$k].attempts = @($l[$k].attempts) + ,([pscustomobject]$rec)
  }
  Write-Utf8NoBom $Path ($l | ConvertTo-Json -Depth 10)
  $l
}

# ---------------------------------------------------------------- classifier

<#
Decision 4's ordered, total rule set. First match wins. Returns
@{ rule; class; reason }.

Ordering differs from the prose in one place, deliberately: the http refusal and
http context-overflow rules fire BEFORE 1b. In the prose they sat after rule 2,
which is after 1b -- so 1b's bare "non-zero exit" claimed every hosted 4xx first
and the refusal rule was unreachable. Order here is the authority.
#>
# First-person only: bare 'safety'/'policy' are this corpus's own vocabulary
# (a content-security library) and fabricate refusals on innocent dispatches.
# Broad on the verb side, though -- a refusal the classifier misses is re-sent
# to the model that refused it.
$script:RefusalMarkers = @(
  "I (can'?t|cannot|won'?t|am unable|'m unable|must decline)",
  'cannot (assist|help|comply)',
  "can'?t (assist|help|comply)",
  'refuse to',
  'not able to (assist|help)'
)
$script:AuthMarkers    = @('refresh_token_reused','401 Unauthorized','Please\s+try\s+signing\s+in\s+again','not logged in')

# Entitlement (billing / quota) markers -- rule 1a', a SEPARATE halt from 1a.
# A billing block is permanent and needs a human, exactly like an auth lapse,
# but it is NOT an auth lapse and must not be reported as one. Before this rule
# existed a billing block fell through to 1b as INFRASTRUCTURE_FAILURE, which
# CHARGES the retry budget: two identical retries per sub-probe across 22
# bullets plus sweep parts, every one failing the same way, before dropping to
# the fallback -- and a final report naming infrastructure for a cause that is
# nothing of the kind. Broad on the noun side because the CLI's wording for
# this class is not pinned by any contract; anchored on 402 for the http path.
$script:BillingMarkers = @(
  'insufficient[_ ](credit|quota|funds|balance)',
  'quota (exceeded|exhausted)',
  'exceeded your current quota',
  'billing (issue|required|hard limit)',
  'payment (required|method)',
  'out of credits','no credits',
  'usage limit reached','spending limit',
  '\b402\b'
)

# 'exceeds' must be qualified: a 422 schema error saying "value exceeds enum"
# would otherwise terminate a sub-probe as a context overflow, with no retry.
$script:OverflowMarkers= @(
  'context (length|window)','maximum context','context_length_exceeded',
  'too many tokens','exceeds .{0,20}(context|token)'
)

function Test-AnyMarker {
  param([string]$Text,[string[]]$Markers)
  if (-not $Text) { return $false }
  # Models routinely emit U+2019/U+02BC where the marker list has a straight
  # apostrophe; normalize so "I can<U+2019>t" is not a false negative.
  $t = $Text -replace [char]0x2019, "'" -replace [char]0x02BC, "'"
  foreach ($m in $Markers) { if ($t -match $m) { return $true } }
  $false
}

function Get-DispatchClass {
  param(
    [Parameter(Mandatory)] $Meta,      # parsed <stem>.meta.json
    [string] $OutputText,              # <stem>.json contents
    [string] $LogText,                 # <stem>.log contents
    [string] $StderrText,              # <stem>.stderr.txt contents
    [scriptblock] $SchemaValidator     # {param($t) [bool] } -- schema-valid?
  )

  # Read optional properties defensively: meta.schema.json does not require
  # finish_reason, so a schema-VALID record would otherwise terminate the
  # classifier under StrictMode. Get-DispatchClass is a public function the
  # orchestrator calls on arbitrary on-disk metas.
  # Must handle BOTH shapes: a PSCustomObject (a .meta.json parsed from disk) and
  # an IDictionary (the ordered hashtable the dispatch functions return in memory).
  # PSObject.Properties is empty for a dictionary, so a PSObject-only reader silently
  # returns null for every field -- which sends a live 403 to rule 8.
  function Get-MetaProp { param($o,[string]$n)
    if ($o -is [System.Collections.IDictionary]) {
      if ($o.Contains($n)) { return $o[$n] } else { return $null }
    }
    if ($null -ne $o.PSObject.Properties[$n]) { return $o.PSObject.Properties[$n].Value }
    $null
  }

  $isHttp       = (Get-MetaProp $Meta 'kind') -eq 'http'
  $exit         = Get-MetaProp $Meta 'exit'
  $finishReason = Get-MetaProp $Meta 'finish_reason'
  $timedOut     = [bool](Get-MetaProp $Meta 'timed_out')
  $orphaned     = [bool](Get-MetaProp $Meta 'orphaned')
  $expected     = Get-MetaProp $Meta 'expected_units'
  if ($null -eq $expected) { $expected = 1 }
  $hasOut       = -not [string]::IsNullOrWhiteSpace($OutputText)

  if (-not $SchemaValidator) { $SchemaValidator = New-SchemaValidator -ReportDir $script:ReportDir }

  # 1a  auth lapse (codex only; there is no codex auth on the http path).
  #     Requires a NON-NULL exit: an orphan's exit is null and its non-empty
  #     artifact promotes to exit 0 (Design step 1b), so stale auth noise in a
  #     successful orphan's stderr must not halt the ticket.
  if (-not $isHttp -and $null -ne $exit -and $exit -ne 0 -and (Test-AnyMarker $StderrText $script:AuthMarkers)) {
    return @{ rule = '1a'; class = 'AUTH_LAPSED'; reason = 'auth marker in stderr' }
  }

  # 1a' entitlement lapse (billing / quota). Halts like 1a, spends no retries,
  #     and is named separately so the report does not call a billing block an
  #     auth problem. BEFORE 1b for the same reason 1c and 2b are: 1b's bare
  #     non-zero-exit claim would otherwise swallow it and retry a permanent
  #     condition twice per sub-probe.
  #     Codex side carries the same non-null, non-zero exit guard as 1a -- a
  #     successful orphan (null exit, promoted to 0) must not halt the ticket on
  #     stale billing noise left in stderr by an earlier failed call.
  if (-not $isHttp -and $null -ne $exit -and $exit -ne 0 -and (Test-AnyMarker $StderrText $script:BillingMarkers)) {
    return @{ rule = "1a'"; class = 'ENTITLEMENT_BLOCKED'; reason = 'billing/quota marker in stderr' }
  }
  #     Http side: 402 is the status for this class and needs no marker; any
  #     other non-2xx still qualifies if the body names a billing cause.
  if ($isHttp -and ($exit -eq 402 -or ($exit -ne 0 -and (Test-AnyMarker $LogText $script:BillingMarkers)))) {
    return @{ rule = "1a'"; class = 'ENTITLEMENT_BLOCKED'; reason = "http $exit with billing/quota cause" }
  }

  # 1c  http context overflow -- BEFORE 1b, else it is retried twice as "infrastructure"
  #     with the identical oversized payload.
  if ($isHttp -and $exit -in 400,413,422 -and (Test-AnyMarker $LogText $script:OverflowMarkers)) {
    return @{ rule = '1c'; class = 'BLOCKED'; reason = 'fallback-context-exceeded' }
  }

  # 2b  http moderation refusal -- BEFORE 1b, for the same reason.
  if ($isHttp -and $exit -in 400,403,422,451 -and (Test-AnyMarker $LogText $script:RefusalMarkers)) {
    return @{ rule = '2b'; class = 'CLASSIFIER_TRIP'; reason = "http $exit with refusal marker" }
  }

  # 3c  200 + empty content + finish_reason 'length' -- a TRUNCATION, not a refusal.
  #     Measured live: a thinking model can spend its whole budget on reasoning
  #     tokens and return zero content with finish_reason='length'. Reading that
  #     as a refusal fabricates a classifier trip on a healthy server.
  if ($isHttp -and $exit -eq 0 -and -not $hasOut -and $finishReason -eq 'length') {
    return @{ rule = '3c'; class = 'TRUNCATED_OR_MALFORMED'; reason = 'empty content, finish_reason=length (reasoning-token exhaustion)' }
  }

  # 1b  transport / process failure
  if ($exit -ne 0 -and $null -ne $exit) {
    return @{ rule = '1b'; class = 'INFRASTRUCTURE_FAILURE'; reason = "non-zero exit $exit" }
  }
  if ($timedOut) {
    return @{ rule = '1b'; class = 'INFRASTRUCTURE_FAILURE'; reason = 'deadline exceeded' }
  }

  # An orphan's null exit is promoted to 0 by the resume path only when the
  # artifact is non-empty; a null exit with no artifact never reaches here.
  if ($null -eq $exit -and -not $orphaned) {
    return @{ rule = '8'; class = 'BLOCKED'; reason = 'unclassified: null exit on a non-orphan' }
  }

  $schemaOk = $false
  if ($hasOut -and $SchemaValidator) { $schemaOk = & $SchemaValidator $OutputText }

  # 2  schema-valid declined
  if ($schemaOk) {
    try {
      $parsed = $OutputText | ConvertFrom-Json
      foreach ($e in $parsed.entries) {
        if ($e.status -eq 'declined') { return @{ rule = '2'; class = 'CLASSIFIER_TRIP'; reason = 'entry status declined' } }
      }
    } catch { }
  }

  # 3  prose refusal in the output, or an empty output whose transcript refuses.
  #    The transcript clause uses FIRST-PERSON phrases only: bare 'safety' and
  #    'policy' match this corpus's own vocabulary (a content-security library),
  #    so they would fire on innocent dispatches.
  if (-not $schemaOk -and $hasOut -and (Test-AnyMarker $OutputText $script:RefusalMarkers)) {
    return @{ rule = '3'; class = 'CLASSIFIER_TRIP'; reason = 'prose refusal in output' }
  }
  if (-not $hasOut -and (Test-AnyMarker $LogText $script:RefusalMarkers)) {
    return @{ rule = '3'; class = 'CLASSIFIER_TRIP'; reason = 'empty output, refusal in transcript' }
  }

  # 4  empty / whitespace / unparseable / schema-invalid
  if (-not $hasOut -or -not $schemaOk) {
    return @{ rule = '4'; class = 'TRUNCATED_OR_MALFORMED'; reason = $(if ($hasOut) { 'schema-invalid' } else { 'empty output' }) }
  }

  # 5  short entry count
  try {
    $parsed = $OutputText | ConvertFrom-Json
    $n = @($parsed.entries).Count
    if ($n -lt $expected) {
      return @{ rule = '5'; class = 'TRUNCATED_OR_MALFORMED'; reason = "entries $n < expected $expected" }
    }
    # 6  grounding: two quotes per sub-probe
    foreach ($e in $parsed.entries) {
      if (@($e.evidence_quotes).Count -lt 2) {
        return @{ rule = '6'; class = 'UNGROUNDED_RESPONSE'; reason = "sub-probe $($e.sub_probe) has fewer than two quotes" }
      }
    }
  } catch {
    return @{ rule = '4'; class = 'TRUNCATED_OR_MALFORMED'; reason = 'unparseable on re-read' }
  }

  # 7  accepted
  @{ rule = '7'; class = 'ACCEPTED'; reason = 'schema-valid, all units present, quote obligations met' }
}

# -------------------------------------------------------------------- resume

function Resolve-Marker {
  <# Ordered predicates, first match wins. Liveness is an INPUT, computed up
     front -- branch (b) needs it, so "test liveness last" was never
     implementable. What comes last is the conclusion "dead, charge a retry".
     Returns a hashtable: @{ action; meta } #>
  param([string]$MarkerPath)

  $raw = Read-Utf8 $MarkerPath
  if (-not $raw) { return @{ action = 'infrastructure-failure'; reason = 'marker unreadable' } }
  try { $m = $raw | ConvertFrom-Json } catch { return @{ action = 'halt'; reason = 'marker unparseable' } }

  # Property-existence tested explicitly: under StrictMode a missing property
  # THROWS rather than returning null, so `if (-not $m.stem)` would crash the
  # resume path on exactly the torn marker it is meant to catch.
  function Has-Prop { param($o,[string]$n) $null -ne $o.PSObject.Properties[$n] }
  function Get-Prop { param($o,[string]$n) if (Has-Prop $o $n) { $o.PSObject.Properties[$n].Value } else { $null } }

  $stem = Get-Prop $m 'stem'
  if (-not $stem) {
    Remove-Marker $MarkerPath | Out-Null
    return @{ action = 'infrastructure-failure'; reason = 'marker has no stem (pre-launch write torn)' }
  }

  $metaPath = "$stem.meta.json"
  $outPath  = "$stem.json"
  $mPid       = Get-Prop $m 'pid'
  $mStartTime = Get-Prop $m 'startTime'
  $mKind      = Get-Prop $m 'kind'

  $live = $false
  if ($mPid) {
    $p = Get-Process -Id $mPid -ErrorAction SilentlyContinue
    if ($p -and $mStartTime) {
      $expectName = if ($mKind -eq 'http') { 'powershell' } else { 'node' }
      $st = [datetime]::MinValue
      $parsed = [datetime]::TryParse([string]$mStartTime, [ref]$st)
      $skew = if ($parsed) { [math]::Abs(($p.StartTime - $st).TotalSeconds) } else { [double]::MaxValue }
      $live = $parsed -and ($p.ProcessName -eq $expectName) -and ($skew -lt 120)
      if ($live -and $mKind -eq 'codex') {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$mPid" -ErrorAction SilentlyContinue).CommandLine
        $live = $cmd -like '*codex.js*'
      }
    }
  }

  # (a) sentinel present. The KILLED record is checked first and preferred: it is
  #     the only evidence the orchestrator-side backstop fired, and a revived
  #     launching shell writing .meta.json later must not shadow it. (Separate
  #     paths by design -- there is no same-path race to tie-break.)
  $killedPath = "$stem.meta.killed.json"
  foreach ($sentinel in @($killedPath, $metaPath)) {
    if (Test-Path -LiteralPath $sentinel) {
      $mt = Read-Utf8 $sentinel
      # PS 5.1: '' | ConvertFrom-Json yields a SILENT null (no catchable error in
      # either EAP mode), so without this guard a zero-byte kill record -- written
      # by hand, non-atomically -- would clear the marker and return a null meta,
      # permanently shadowing a healthy .meta.json beside it.
      if ([string]::IsNullOrWhiteSpace($mt)) {
        return @{ action = 'halt'; reason = "sentinel zero-byte or whitespace (torn): $sentinel" }
      }
      try { $null = $mt | ConvertFrom-Json } catch { return @{ action = 'halt'; reason = "sentinel unparseable (torn): $sentinel" } }
      Remove-Marker $MarkerPath | Out-Null
      return @{ action = 'classify'; meta = ($mt | ConvertFrom-Json) }
    }
  }
  # (b) orphan-complete: finished while the launching shell was gone
  if ((Test-Path -LiteralPath $outPath) -and -not $live) {
    $len = (Get-Item -LiteralPath $outPath).Length
    if ($len -gt 0) {
      $marker = @{}
      foreach ($prop in $m.PSObject.Properties) { $marker[$prop.Name] = $prop.Value }
      $meta = New-MetaObject -Marker $marker -Exit $null -TimedOut $false -Orphaned $true -Seconds $null
      Write-Utf8NoBom $metaPath ($meta | ConvertTo-Json -Depth 12)
      Remove-Marker $MarkerPath | Out-Null
      return @{ action = 'classify-orphan'; meta = $meta }
    }
    # (b-empty) started-but-unfinished write is not a result
    Remove-Marker $MarkerPath | Out-Null
    return @{ action = 'infrastructure-failure'; reason = 'orphan artifact is zero-byte' }
  }
  # (c) still running
  if ($live) { return @{ action = 'wait'; pid = $mPid; deadlineSeconds = (Get-Prop $m 'deadlineSeconds') } }

  Remove-Marker $MarkerPath | Out-Null
  @{ action = 'infrastructure-failure'; reason = 'no live job and no artifact' }
}

# ----------------------------------------------------------------- self-test

function Invoke-SelfTest {
  param([string]$ReportDir)

  $fails = New-Object System.Collections.Generic.List[string]
  $skips = New-Object System.Collections.Generic.List[string]
  $script:selfTestPasses = 0
  function Check($name, $cond, $detail) {
    if ($cond) { Write-Host ("  PASS  {0}" -f $name); $script:selfTestPasses++ }
    else { Write-Host ("  FAIL  {0}  -- {1}" -f $name, $detail) -ForegroundColor Red; $script:selfTestFails.Add($name) }
  }
  function Skip($name, $why) {
    # A skipped leg is UNVERIFIED, and the gate fails on it (exit 1): three
    # reviewers independently caught this test passing green with whole legs
    # silently skipped under port contention and a transient file lock.
    Write-Host ("  SKIP  {0}  -- {1}" -f $name, $why) -ForegroundColor Yellow
    $script:selfTestSkips.Add($name)
  }
  function Get-FreePort {
    # Fixed ports collide with the documented parallel-session workflow; ask the
    # OS for a free one per leg instead.
    $t = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $t.Start(); $p = ([Net.IPEndPoint]$t.LocalEndpoint).Port; $t.Stop(); $p
  }
  $script:selfTestFails = $fails
  $script:selfTestSkips = $skips

  Write-Host "PET-184 dispatch.ps1 self-test"
  Write-Host "------------------------------"

  # TEMP, never $ReportDir. This file is committed under scripts/, and for a
  # -SelfTest run $ReportDir resolves to the script's own folder -- so rooting the
  # sandbox there wrote ~30 fixture files (fake codex shims, .env stubs, whole
  # stem sets) straight into a TRACKED directory. Verified by running it once
  # that way: `git status scripts/` came back dirty. A committed tool's self-test
  # must leave the working tree exactly as it found it.
  $sandbox = Join-Path $env:TEMP 'pet184-dispatch-selftest'
  if (Test-Path $sandbox) { Remove-Item -Recurse -Force $sandbox }
  New-Item -ItemType Directory -Force -Path (Join-Path $sandbox 'raw\inflight') | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $sandbox 'raw\smoke')    | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $sandbox 'prompts')      | Out-Null

  # A real schema.json stand-in so the hash and the http body path are exercised.
  Write-Utf8NoBom (Join-Path $sandbox 'schema.json') (@{
    type='object'; additionalProperties=$false
    required=@('dispatch_id','entries')
    properties=@{ dispatch_id=@{type='string'}; entries=@{type='array'} }
  } | ConvertTo-Json -Depth 10)

  $hash = Get-SchemaHash $sandbox
  Check 'schema hash is 64 hex' ($hash -match '^[0-9A-Fa-f]{64}$') $hash

  # --- the non-ASCII sentinel, end to end through a prompt file
  $sentinel = "SMOKE-FIXTURE-LINE-1`n" + ([char]0x0430) + ([char]0x200B) + ([char]0x202E) + "`nSMOKE-FIXTURE-LINE-3"
  $promptPath = Join-Path $sandbox 'prompts\selftest.md'
  Write-Utf8NoBom $promptPath $sentinel
  $roundTrip = Read-Utf8 $promptPath
  Check 'prompt file round-trips non-ASCII byte-identical' ($roundTrip -ceq $sentinel) 'mojibake or BOM'
  $bytes = [System.IO.File]::ReadAllBytes($promptPath)
  Check 'prompt file has no BOM' (-not ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) 'BOM present'
  Check 'no ? substitution in prompt' (-not ($roundTrip -match '\?')) 'ASCII pipe corruption'

  # --- stem grammar
  $stemAll = New-Stem -ReportDir $sandbox -Area '1' -Units @('1.1','1.2') -Pass 'first' -Model 'gpt-5.6-sol'
  $stemOne = New-Stem -ReportDir $sandbox -Area '3' -Units @('3.1')       -Pass 'fallback' -Model 'qwen/qwen3.8-27b'
  Check 'whole-area stem uses the all token' ((Split-Path -Leaf $stemAll) -like '1.all.first.*') (Split-Path -Leaf $stemAll)
  Check 'model slug strips the slash'        ((Split-Path -Leaf $stemOne) -like '3.3.1.fallback.qwen-qwen3.8-27b.*') (Split-Path -Leaf $stemOne)
  Check 'timestamp is colon-free'            (-not ((Split-Path -Leaf $stemAll) -match ':')) 'illegal filename char'

  # --- marker + meta shape, and the pre-launch write that was {"pid":null}
  $marker = New-MarkerObject -Kind 'codex' -Stem $stemAll -Area '1' -Units @('1.1','1.2') -Pass 'first' `
              -Model 'gpt-5.6-sol' -PromptPath $promptPath -Invocation 'exec -m gpt-5.6-sol' `
              -ReportDir $sandbox -SchemaHash $hash -DeadlineSeconds 900 -Attempt 1 -RetriesSpent 0
  $markerPath = Join-Path $sandbox 'raw\inflight\selftest.json'
  Write-Marker $markerPath $marker
  $mk = (Read-Utf8 $markerPath) | ConvertFrom-Json
  Check 'pre-launch marker carries stem' ([bool]$mk.stem) 'no stem -- unresolvable by the resume path'
  Check 'pre-launch marker carries kind' ($mk.kind -eq 'codex') 'no kind'
  Check 'pre-launch marker carries area/units/pass' (($mk.area -eq '1') -and ($mk.units.Count -eq 2) -and ($mk.pass -eq 'first')) 'attribution fields missing'
  Check 'expected_units matches units' ($mk.expected_units -eq 2) "$($mk.expected_units)"
  Check 'pre-launch pid is null' ($null -eq $mk.pid) 'pid should be null before launch'

  # --- timestamps must be parseable by something other than PowerShell
  Check 'dispatchedAt is ISO 8601, not /Date(ms)/' ($mk.dispatchedAt -match '^\d{4}-\d{2}-\d{2}T') $mk.dispatchedAt

  # --- meta shape
  $meta = New-MetaObject -Marker $marker -Exit 0 -TimedOut $false -Orphaned $false -Seconds 1.5 `
            -Extra @{ reasoning_effort='high'; sandbox='read-only'; cwd='C:/x' }
  $metaPath = "$stemAll.meta.json"
  Write-Utf8NoBom $metaPath ($meta | ConvertTo-Json -Depth 12)
  $mt = (Read-Utf8 $metaPath) | ConvertFrom-Json
  Check 'meta exit is an integer' ($mt.exit -is [int]) ("type=" + $mt.exit.GetType().Name)
  Check 'meta carries area/units/pass' (($mt.area -eq '1') -and ($mt.units.Count -eq 2) -and ($mt.pass -eq 'first')) 'unattributable dispatch'
  Check 'meta dispatched_at is ISO 8601' ($mt.dispatched_at -match '^\d{4}-\d{2}-\d{2}T') $mt.dispatched_at

  # --- atomic write leaves no residue in a directory two gates read as a set
  $residue = Get-ChildItem (Join-Path $sandbox 'raw\inflight') -Filter '*.tmp' -ErrorAction SilentlyContinue
  Check 'no .tmp residue in raw/inflight' ($null -eq $residue -or $residue.Count -eq 0) 'tmp blocks the teardown gate'

  # --- resume: (a) sentinel present
  $r = Resolve-Marker $markerPath
  Check 'resume (a): classifies from an existing sentinel' ($r.action -eq 'classify') $r.action

  # --- resume: (b) orphan-complete
  Remove-Item -LiteralPath $metaPath -Force
  Write-Utf8NoBom "$stemAll.json" '{"dispatch_id":"x","entries":[]}'
  $marker.pid = 999999; $marker.startTime = Get-Iso    # a PID that is not live
  Write-Marker $markerPath $marker
  $r = Resolve-Marker $markerPath
  Check 'resume (b): orphan-complete synthesizes a meta' ($r.action -eq 'classify-orphan') $r.action
  if ($r.action -eq 'classify-orphan') {
    Check 'orphan meta is flagged and exit is null' (($r.meta.orphaned -eq $true) -and ($null -eq $r.meta.exit)) 'flags wrong'
    Check 'orphan meta still carries prompt_path' ([bool]$r.meta.prompt_path) 'audit chain broken for orphans'
    Check 'orphan meta still carries area/units'  (($r.meta.area -eq '1') -and ($r.meta.units.Count -eq 2)) 'unattributable orphan'
  }

  # --- resume: (b-empty) zero-byte artifact is not a result
  Remove-Item -LiteralPath "$stemAll.meta.json" -Force
  Write-Utf8NoBom "$stemAll.json" ''
  Write-Marker $markerPath $marker
  $r = Resolve-Marker $markerPath
  Check 'resume (b-empty): zero-byte artifact -> infrastructure-failure' ($r.action -eq 'infrastructure-failure') $r.action
  Check 'resume (b-empty): marker cleared' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives'

  # --- resume: no artifact at all
  Remove-Item -LiteralPath "$stemAll.json" -Force
  Write-Marker $markerPath $marker
  $r = Resolve-Marker $markerPath
  Check 'resume (c): no artifact, not live -> infrastructure-failure' ($r.action -eq 'infrastructure-failure') $r.action
  Check 'resume (c): dead fall-through clears the marker' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives'

  # --- resume: torn pre-launch marker (the {"pid":null} regression)
  Write-Utf8NoBom $markerPath '{"pid":null}'
  $r = Resolve-Marker $markerPath
  Check 'resume: stem-less marker is caught, not silently unresolvable' ($r.action -eq 'infrastructure-failure') $r.action
  Check 'resume: stem-less marker is cleared' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives'

  # --- Python must be able to read what PowerShell wrote (manifest.py)
  $py = 'C:\python310\python.exe'
  if (Test-Path $py) {
    Write-Marker $markerPath $marker
    $probe = Join-Path $sandbox 'pycheck.py'
    Write-Utf8NoBom $probe @"
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding='utf-8'))
assert d['stem'], 'no stem'
assert d['area'] == '1', 'area lost'
assert isinstance(d['expected_units'], int), 'expected_units not int'
assert d['dispatchedAt'][:4].isdigit(), 'timestamp not ISO: ' + str(d['dispatchedAt'])
print('OK')
"@
    $out = & $py $probe $markerPath 2>&1
    Check 'manifest.py can parse the marker (no BOM, ISO dates)' ($out -match 'OK') "$out"
  } else {
    Skip 'python round-trip' 'no C:\python310\python.exe'
  }

  # --- codex dispatch against a fake codex.js: exercises launch, Handle, exit code, four files
  $fake = Join-Path $sandbox 'fake-codex.js'
  Write-Utf8NoBom $fake @'
const fs = require('fs');
let out = null, i = process.argv.indexOf('-o');
if (i > -1) out = process.argv[i+1];
let chunks = [];
process.stdin.on('data', d => chunks.push(d));
process.stdin.on('end', () => {
  const prompt = Buffer.concat(chunks).toString('utf8');
  process.stdout.write('transcript: received ' + Buffer.byteLength(prompt) + ' bytes\n');
  const echoed = prompt.split('\n')[1] || '';
  if (out) fs.writeFileSync(out, JSON.stringify({dispatch_id:'selftest', entries:[{echo: echoed}]}), 'utf8');
  process.exit(0);
});
'@
  $stemC = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.1') -Pass 'first' -Model 'fake' -Smoke
  $mC = New-MarkerObject -Kind 'codex' -Stem $stemC -Area 'smoke' -Units @('smoke.1') -Pass 'first' `
          -Model 'fake' -PromptPath $promptPath -Invocation 'fake' -ReportDir $sandbox -SchemaHash $hash `
          -DeadlineSeconds 60 -Attempt 1 -RetriesSpent 0
  $mkPathC = Join-Path $sandbox 'raw\inflight\smokecodex.json'
  $metaC = Invoke-CodexDispatch -Marker $mC -MarkerPath $mkPathC -CodexJs $fake -Cwd $sandbox -ReasoningEffort 'high'

  Check 'codex dispatch: exit code is an integer, not null' ($metaC.exit -is [int]) ("got " + $(if ($null -eq $metaC.exit) {'null'} else {$metaC.exit.GetType().Name}))
  Check 'codex dispatch: exit 0 on success' ($metaC.exit -eq 0) "$($metaC.exit)"
  foreach ($ext in @('.json','.meta.json','.log','.stderr.txt')) {
    Check "codex dispatch: writes $ext" (Test-Path -LiteralPath "$stemC$ext") 'missing'
  }
  Check 'codex dispatch: marker cleared' (-not (Test-Path -LiteralPath $mkPathC)) 'marker survives -> teardown gate blocked'
  $echo = ((Read-Utf8 "$stemC.json") | ConvertFrom-Json).entries[0].echo
  $wantSentinel = ([char]0x0430).ToString() + ([char]0x200B) + ([char]0x202E)
  Check 'codex dispatch: non-ASCII survived stdin round-trip' ($echo -ceq $wantSentinel) "got [$echo]"

  # --- deadline: a child that outlives its deadline is killed and recorded
  $slow = Join-Path $sandbox 'slow.js'
  Write-Utf8NoBom $slow 'setTimeout(()=>process.exit(0), 30000); process.stdin.resume();'
  $stemS = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.2') -Pass 'first' -Model 'fake' -Smoke
  $mS = New-MarkerObject -Kind 'codex' -Stem $stemS -Area 'smoke' -Units @('smoke.2') -Pass 'first' `
          -Model 'fake' -PromptPath $promptPath -Invocation 'fake' -ReportDir $sandbox -SchemaHash $hash `
          -DeadlineSeconds 2 -Attempt 1 -RetriesSpent 0
  $mkPathS = Join-Path $sandbox 'raw\inflight\slow.json'
  $metaS = Invoke-CodexDispatch -Marker $mS -MarkerPath $mkPathS -CodexJs $slow -Cwd $sandbox -ReasoningEffort 'high'
  Check 'deadline: slow child is killed inside the deadline' ($metaS.timed_out -eq $true) "timed_out=$($metaS.timed_out)"
  Check 'deadline: killed child still writes a sentinel' (Test-Path -LiteralPath "$stemS.meta.json") 'no sentinel -> orphan'
  Check 'deadline: marker cleared after a kill' (-not (Test-Path -LiteralPath $mkPathS)) 'marker survives'

  # ---- classifier: the cases prose review kept getting wrong -----------------
  $validator = { param($t) try { $o = $t | ConvertFrom-Json; return ($null -ne $o.dispatch_id -and $null -ne $o.entries) } catch { return $false } }
  function Meta([hashtable]$over) {
    $base = @{ kind='codex'; exit=0; timed_out=$false; orphaned=$false; expected_units=1; finish_reason=$null }
    foreach ($k in $over.Keys) { $base[$k] = $over[$k] }
    [pscustomobject]$base
  }
  $good = '{"dispatch_id":"d","entries":[{"area":"1","sub_probe":"1.1","status":"no-findings","evidence_quotes":["a","b"],"findings":[]}]}'

  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText $good -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: healthy dispatch is ACCEPTED' ($c.class -eq 'ACCEPTED') "$($c.class)/$($c.rule)"

  # The live-measured case: 200, empty content, finish_reason=length.
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=0; finish_reason='length'; http_status=200}) `
        -OutputText '' -LogText 'usage policy applies to all requests' -StderrText '' -SchemaValidator $validator
  Check 'classify: 200+empty+length is TRUNCATION, not a refusal' ($c.class -eq 'TRUNCATED_OR_MALFORMED' -and $c.rule -eq '3c') "$($c.class)/$($c.rule)"

  # Bare 'policy'/'safety' in a security corpus must not fabricate a refusal.
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText '' `
        -LogText 'scanning fail-mode policy and safety config' -StderrText '' -SchemaValidator $validator
  Check 'classify: corpus vocabulary does not fabricate a CLASSIFIER_TRIP' ($c.class -ne 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"

  # A genuine first-person refusal in the transcript still routes.
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText '' `
        -LogText "I can't help with that request." -StderrText '' -SchemaValidator $validator
  Check 'classify: real refusal in transcript is a CLASSIFIER_TRIP' ($c.class -eq 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"

  # Hosted 4xx moderation must reach 2b, not be eaten by 1b.
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=403; http_status=403}) -OutputText '' `
        -LogText 'I refuse to analyze this content' -StderrText '' -SchemaValidator $validator
  Check 'classify: hosted 4xx refusal reaches 2b, not 1b' ($c.rule -eq '2b' -and $c.class -eq 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"

  # Context overflow must not be retried as infrastructure.
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=400; http_status=400}) -OutputText '' `
        -LogText 'the request exceeds the maximum context length' -StderrText '' -SchemaValidator $validator
  Check 'classify: context overflow is BLOCKED, not retried' ($c.rule -eq '1c' -and $c.class -eq 'BLOCKED') "$($c.class)/$($c.rule)"

  # Auth lapse halts.
  $c = Get-DispatchClass -Meta (Meta @{exit=1}) -OutputText '' -LogText '' `
        -StderrText '401 Unauthorized: refresh_token_reused' -SchemaValidator $validator
  Check 'classify: auth lapse is AUTH_LAPSED' ($c.class -eq 'AUTH_LAPSED') "$($c.class)/$($c.rule)"

  # Targets are model endpoints, never Hermes profile names. Pinned because the
  # profile-named revision coupled the review's reproducibility to two unrelated
  # profiles: retuning bard's songwriting model would have changed the reviewer.
  $tgts = Get-FallbackTargets
  Check 'fallback targets are named for the model, not a Hermes profile' (
    $tgts[0].name -eq 'local-qwen3.8-27b' -and $tgts[1].name -eq 'openrouter-minimax-m3' -and
    -not ($tgts.name -match '^(discord|bard)$')
  ) "$($tgts.name -join ',')"

  # Rule 1a': a billing block halts, and is NOT reported as an auth lapse.
  # Before this rule it reached 1b and charged the retry budget on a permanent
  # condition -- two wasted retries on every one of 22 bullets plus sweep parts.
  $c = Get-DispatchClass -Meta (Meta @{exit=1}) -OutputText '' -LogText '' `
        -StderrText 'ERROR: insufficient_quota - you have exceeded your current quota' -SchemaValidator $validator
  Check 'classify: codex billing block is ENTITLEMENT_BLOCKED' ($c.class -eq 'ENTITLEMENT_BLOCKED' -and $c.rule -eq "1a'") "$($c.class)/$($c.rule)"
  Check 'classify: a billing block is not reported as an auth lapse' ($c.class -ne 'AUTH_LAPSED') "$($c.class)"
  Check 'classify: ENTITLEMENT_BLOCKED spends no retry budget' (-not (Test-ChargesRetry $c.class)) 'billing charges the retry budget'

  # Http side: 402 needs no marker at all.
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=402; http_status=402}) -OutputText '' `
        -LogText 'Payment Required' -StderrText '' -SchemaValidator $validator
  Check 'classify: http 402 is ENTITLEMENT_BLOCKED without a marker' ($c.class -eq 'ENTITLEMENT_BLOCKED' -and $c.rule -eq "1a'") "$($c.class)/$($c.rule)"

  # ...but an ordinary transport failure must still reach 1b. The billing rule
  # is broad on the noun side, so this pins that it did not swallow rule 1b.
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=500; http_status=500}) -OutputText '' `
        -LogText 'upstream error: model failed to load' -StderrText '' -SchemaValidator $validator
  Check 'classify: a 500 with no billing cause is still 1b infrastructure' ($c.rule -eq '1b' -and $c.class -eq 'INFRASTRUCTURE_FAILURE') "$($c.class)/$($c.rule)"

  # The 1a-shaped orphan guard, re-pinned for 1a': stale billing noise in a
  # SUCCESSFUL orphan's stderr must not halt the ticket.
  $c = Get-DispatchClass -Meta (Meta @{exit=0; orphaned=$true}) -OutputText $good -LogText '' `
        -StderrText 'earlier call failed: insufficient_quota' -SchemaValidator $validator
  Check 'classify: billing noise in a successful orphan is not ENTITLEMENT_BLOCKED' ($c.class -ne 'ENTITLEMENT_BLOCKED') "$($c.class)/$($c.rule)"

  # Short entry count.
  $c = Get-DispatchClass -Meta (Meta @{expected_units=3}) -OutputText $good -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: short entry count is rule 5' ($c.rule -eq '5') "$($c.class)/$($c.rule)"

  # Ungrounded.
  $thin = '{"dispatch_id":"d","entries":[{"area":"1","sub_probe":"1.1","status":"no-findings","evidence_quotes":["only-one"],"findings":[]}]}'
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText $thin -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: one quote is UNGROUNDED (rule 6)' ($c.class -eq 'UNGROUNDED_RESPONSE') "$($c.class)/$($c.rule)"

  # Declined.
  $dec = '{"dispatch_id":"d","entries":[{"area":"1","sub_probe":"1.1","status":"declined","evidence_quotes":["a","b"],"findings":[]}]}'
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText $dec -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: declined entry is a CLASSIFIER_TRIP' ($c.class -eq 'CLASSIFIER_TRIP' -and $c.rule -eq '2') "$($c.class)/$($c.rule)"

  # Orphan with a good artifact classifies normally.
  $c = Get-DispatchClass -Meta (Meta @{exit=$null; orphaned=$true}) -OutputText $good -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: orphan with a valid artifact is ACCEPTED' ($c.class -eq 'ACCEPTED') "$($c.class)/$($c.rule)"

  # Totality: no input reaches rule 8 except a null exit on a non-orphan.
  $c = Get-DispatchClass -Meta (Meta @{exit=$null; orphaned=$false}) -OutputText '' -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: rule 8 fires only on a null exit for a non-orphan' ($c.rule -eq '8') "$($c.class)/$($c.rule)"

  # ---- REAL schema validation --------------------------------------------
  # Previously the "contracts" were hand-asserted field by field, which is the
  # restatement the schema files were introduced to replace -- and it is why an
  # invalid orphan meta passed 49 green checks.
  $mkSchema = Join-Path $PSScriptRoot 'marker.schema.json'
  $mtSchema = Join-Path $PSScriptRoot 'meta.schema.json'
  if ((Test-Path $mkSchema) -and (Test-Path $script:PythonExe)) {
    $r1 = Test-AgainstSchema -SchemaPath $mkSchema -Json ((Read-Utf8 $markerPath))
    Check 'marker validates against marker.schema.json' $r1.valid ($r1.errors -join '; ')

    $mtGood = New-MetaObject -Marker $marker -Exit 0 -TimedOut $false -Orphaned $false -Seconds 1.0 `
                -Extra @{ reasoning_effort='high'; sandbox='read-only'; cwd='C:/x' }
    $r2 = Test-AgainstSchema -SchemaPath $mtSchema -Json ($mtGood | ConvertTo-Json -Depth 12)
    Check 'codex meta validates against meta.schema.json' $r2.valid ($r2.errors -join '; ')

    # The orphan path passes no -Extra: this is the case that was invalid.
    $mtOrphan = New-MetaObject -Marker $marker -Exit $null -TimedOut $false -Orphaned $true -Seconds $null
    $r3 = Test-AgainstSchema -SchemaPath $mtSchema -Json ($mtOrphan | ConvertTo-Json -Depth 12)
    Check 'ORPHAN codex meta validates against meta.schema.json' $r3.valid ($r3.errors -join '; ')

    $hm = New-MarkerObject -Kind 'http' -Stem $stemAll -Area '3' -Units @('3.1') -Pass 'fallback' `
            -Model 'qwen/qwen3.8-27b' -PromptPath $promptPath -Invocation 'POST /chat/completions' `
            -ReportDir $sandbox -SchemaHash $hash -DeadlineSeconds 300 -Attempt 1 -RetriesSpent 0 `
            -BaseUrl 'http://127.0.0.1:1234/v1'
    $r4 = Test-AgainstSchema -SchemaPath $mkSchema -Json ($hm | ConvertTo-Json -Depth 12)
    Check 'http marker validates against marker.schema.json' $r4.valid ($r4.errors -join '; ')
    $mtOrphanHttp = New-MetaObject -Marker $hm -Exit $null -TimedOut $false -Orphaned $true -Seconds $null
    $r5 = Test-AgainstSchema -SchemaPath $mtSchema -Json ($mtOrphanHttp | ConvertTo-Json -Depth 12)
    Check 'ORPHAN http meta validates (base_url carried from marker)' $r5.valid ($r5.errors -join '; ')
  } else { Skip 'schema validation' 'no schema files or python' }

  # ---- the real schema.json validator, not a two-property stub -------------
  # Point at the REAL reviewer contract, not the sandbox's reduced copy:
  # validating against the stub is how "the classifier is pinned" can be true
  # while no branch has ever seen the schema the run will actually use.
  #
  # schema.json is the ONE reviewer-contract file that travels with the tool.
  # It is the canonical copy; Design step 0b copies it into <REPORT_DIR> and
  # records its SHA-256 as $schemaHash, and a real dispatch reads the run's copy
  # through -ReportDir. Keeping the canonical beside the tool is what lets this
  # leg run on a clean checkout with no run directory in existence. Before the
  # tool/run split it resolved from $PSScriptRoot only because the two shared a
  # folder, and the split turned this check into a silent skip until the
  # fail-on-skip gate caught it.
  if ((Test-Path $script:PythonExe) -and (Test-Path (Join-Path $PSScriptRoot 'schema.json'))) {
    $realVal = New-SchemaValidator -ReportDir $PSScriptRoot
    Check 'real validator accepts a conforming response' (& $realVal $good) 'rejected a valid doc'
    Check 'real validator rejects entries-as-object'  (-not (& $realVal '{"dispatch_id":"d","entries":{}}')) 'accepted a bad doc'
    Check 'real validator rejects a missing findings[]' (-not (& $realVal '{"dispatch_id":"d","entries":[{"area":"1","sub_probe":"1.1","status":"no-findings","evidence_quotes":["a","b"]}]}')) 'accepted a bad doc'
  } else { Skip 'real validator' 'no python' }

  # ---- rule 1b, which every ordering argument is about --------------------
  $c = Get-DispatchClass -Meta (Meta @{exit=127}) -OutputText '' -LogText '' -StderrText 'boom' -SchemaValidator $validator
  Check 'classify: non-zero exit with no auth marker is INFRASTRUCTURE_FAILURE' ($c.rule -eq '1b') "$($c.class)/$($c.rule)"
  $c = Get-DispatchClass -Meta (Meta @{exit=0; timed_out=$true}) -OutputText '' -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: timed_out is INFRASTRUCTURE_FAILURE' ($c.class -eq 'INFRASTRUCTURE_FAILURE') "$($c.class)/$($c.rule)"

  # ---- refusal false negatives the round-9 review reproduced ---------------
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText 'I cannot assist. The call was `parse({"a":1})`.' -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: refusal containing a brace still reaches rule 3' ($c.class -eq 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText ("I can" + [char]0x2019 + "t help with that.") -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: curly apostrophe refusal is caught' ($c.class -eq 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText 'Sorry, I cannot help with this request.' -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: "cannot help" is caught' ($c.class -eq 'CLASSIFIER_TRIP') "$($c.class)/$($c.rule)"

  # ---- a 422 schema error must NOT be read as a context overflow ----------
  $c = Get-DispatchClass -Meta (Meta @{kind='http'; exit=422; http_status=422}) -OutputText '' `
        -LogText 'schema error: value exceeds enum' -StderrText '' -SchemaValidator $validator
  Check 'classify: 422 schema error is not fallback-context-exceeded' ($c.rule -ne '1c') "$($c.class)/$($c.rule)"

  # ---- a schema-valid meta without finish_reason must not throw -----------
  $noFr = [pscustomobject]@{ kind='http'; exit=0; timed_out=$false; orphaned=$false; expected_units=1
                             base_url='http://x'; http_status=200 }
  $threw = $false
  try { $c = Get-DispatchClass -Meta $noFr -OutputText '' -LogText '' -StderrText '' -SchemaValidator $validator } catch { $threw = $true }
  Check 'classify: meta without finish_reason does not throw' (-not $threw) 'StrictMode property access'

  # ---- Resolve-Marker must clear the marker (teardown gate) ----------------
  Write-Utf8NoBom "$stemAll.json" $good
  Write-Utf8NoBom "$stemAll.meta.json" ($mtGood | ConvertTo-Json -Depth 12)
  Write-Marker $markerPath $marker
  $null = Resolve-Marker $markerPath
  Check 'resume: marker is cleared after classify' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives -> teardown gate blocked'
  Remove-Item -LiteralPath "$stemAll.meta.json" -Force -ErrorAction SilentlyContinue
  $marker.pid = 999999; Write-Marker $markerPath $marker
  $null = Resolve-Marker $markerPath
  Check 'resume: marker is cleared after orphan-complete' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives'

  # ---- bad startTime must not kill the resume loop ------------------------
  Write-Utf8NoBom $markerPath (@{ kind='codex'; stem=$stemAll; pid=$PID; startTime='not-a-date' } | ConvertTo-Json)
  $threw = $false
  try { $null = Resolve-Marker $markerPath } catch { $threw = $true }
  Check 'resume: unparseable startTime does not throw' (-not $threw) 'terminating error kills the whole resume loop'

  # ---- -Smoke must actually be reachable ----------------------------------
  $sm = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.1') -Pass 'first' -Model 'm' -Smoke
  Check '-Smoke roots the stem under raw\smoke' ((Split-Path -Parent $sm) -like '*raw\smoke') (Split-Path -Parent $sm)
  Check 'no -Smoke roots the stem under raw'    ((Split-Path -Parent $stemAll) -like '*\raw') (Split-Path -Parent $stemAll)

  # ---- the fence: a real dispatch may never default -ReportDir here ---------
  # This file is committed under scripts/. Its output is not. Spawned as a child
  # because the guard fires at parameter-resolution time, before any function
  # this self-test could call in-process.
  # Start-Process with a file redirect, NOT `& powershell ... 2>&1`: under PS 5.1
  # redirecting a native command's stderr wraps every line in a NativeCommandError
  # and trips $?, which kills this self-test on a check that is PASSING.
  $selfPathForFence = if ($PSCommandPath) { $PSCommandPath } else { Join-Path $PSScriptRoot 'dispatch.ps1' }
  $fenceErrF = Join-Path $sandbox 'fence.stderr.txt'
  $fenceOutF = Join-Path $sandbox 'fence.stdout.txt'
  $fp = Start-Process -FilePath 'powershell' -NoNewWindow -Wait -PassThru `
          -RedirectStandardError $fenceErrF -RedirectStandardOutput $fenceOutF `
          -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$selfPathForFence`"",
                          '-Kind','http','-Area','1','-Units','1.1','-Model','m','-PromptPath','nope.txt')
  $fenceText = if (Test-Path -LiteralPath $fenceErrF) { Read-Utf8 $fenceErrF } else { '' }
  Check 'fence: a real dispatch without -ReportDir refuses to run' (
    ($fenceText -match '-ReportDir is required') -and ($fp.ExitCode -ne 0)
  ) "exit=$($fp.ExitCode) stderr=$($fenceText -replace '\s+',' ')"

  # ...and the self-test's own fixtures stay out of the working tree.
  Check 'fence: the self-test sandbox is outside the repo' (
    -not ($sandbox -like "$PSScriptRoot*")
  ) $sandbox

  # ---- HTTP dispatch end to end against a local listener ------------------
  $listener = New-Object Net.HttpListener
  $port = Get-FreePort
  $listener.Prefixes.Add("http://127.0.0.1:$port/")
  try {
    $listener.Start()
    $job = Start-Job -ScriptBlock {
      param($p)
      $l = New-Object Net.HttpListener; $l.Prefixes.Add("http://127.0.0.1:$p/"); $l.Start()
      foreach ($i in 1..2) {
        $ctx = $l.GetContext()
        $body = if ($i -eq 1) {
          '{"choices":[{"finish_reason":"stop","message":{"content":"{\"dispatch_id\":\"d\",\"entries\":[]}"}}],"usage":{"completion_tokens_details":{"reasoning_tokens":5}}}'
        } else { '{"error":{"message":"I cannot assist with that"}}' }
        $ctx.Response.StatusCode = if ($i -eq 1) { 200 } else { 403 }
        $ctx.Response.ContentType = 'application/json; charset=utf-8'
        $b = [Text.Encoding]::UTF8.GetBytes($body)
        $ctx.Response.OutputStream.Write($b,0,$b.Length); $ctx.Response.Close()
      }
      $l.Stop()
    } -ArgumentList $port
    $listener.Stop(); $listener.Close()
    Start-Sleep -Milliseconds 700

    $stemH = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.3') -Pass 'fallback' -Model 'stub' -Smoke
    $mH = New-MarkerObject -Kind 'http' -Stem $stemH -Area 'smoke' -Units @('smoke.3') -Pass 'fallback' `
            -Model 'stub' -PromptPath $promptPath -Invocation 'POST' -ReportDir $sandbox -SchemaHash $hash `
            -DeadlineSeconds 30 -Attempt 1 -RetriesSpent 0 -BaseUrl "http://127.0.0.1:$port/v1"
    $mkH = Join-Path $sandbox 'raw\inflight\http1.json'
    $metaH = Invoke-HttpDispatch -Marker $mH -MarkerPath $mkH -ApiKey '' -MaxTokens 512
    Check 'http dispatch: exit 0 on 200' ($metaH.exit -eq 0) "exit=$($metaH.exit) status=$($metaH.http_status)"
    Check 'http dispatch: meta records the max_tokens budget' ($metaH.max_tokens -eq 512) "$($metaH.max_tokens)"
    foreach ($ext in @('.json','.meta.json','.log','.stderr.txt')) {
      Check "http dispatch: writes $ext" (Test-Path -LiteralPath "$stemH$ext") 'missing'
    }
    Check 'http dispatch: .json is the content, not the envelope' ((Read-Utf8 "$stemH.json") -notmatch '"choices"') 'wrote the envelope'
    Check 'http dispatch: marker cleared' (-not (Test-Path -LiteralPath $mkH)) 'marker survives'
    if (Test-Path $mtSchema) {
      $rh = Test-AgainstSchema -SchemaPath $mtSchema -Json ($metaH | ConvertTo-Json -Depth 12)
      Check 'http meta validates against meta.schema.json' $rh.valid ($rh.errors -join '; ')
    }

    $stemE = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.4') -Pass 'fallback' -Model 'stub' -Smoke
    $mE = New-MarkerObject -Kind 'http' -Stem $stemE -Area 'smoke' -Units @('smoke.4') -Pass 'fallback' `
            -Model 'stub' -PromptPath $promptPath -Invocation 'POST' -ReportDir $sandbox -SchemaHash $hash `
            -DeadlineSeconds 30 -Attempt 1 -RetriesSpent 0 -BaseUrl "http://127.0.0.1:$port/v1"
    $mkE = Join-Path $sandbox 'raw\inflight\http2.json'
    $metaE = Invoke-HttpDispatch -Marker $mE -MarkerPath $mkE -ApiKey ''
    Check 'http dispatch: real 403 recovered, not flattened to 599' ($metaE.http_status -eq 403) "http_status=$($metaE.http_status)"
    $cE = Get-DispatchClass -Meta $metaE -OutputText (Read-Utf8 "$stemE.json") -LogText (Read-Utf8 "$stemE.log") -StderrText '' -SchemaValidator $validator
    Check 'http 403 refusal classifies 2b, end to end' ($cE.rule -eq '2b') "$($cE.class)/$($cE.rule)"
    Remove-Job $job -Force -ErrorAction SilentlyContinue
  } catch {
    Skip 'http dispatch leg' $_.Exception.Message
  }

  # ---- request-body budgets (the thinking-model fix) ------------------------
  $bodyB = New-HttpRequestBody -Model 'm' -PromptText 'p' -SchemaObj @{type='object'} -MaxTokens 512 -ReasoningMaxTokens 2048
  Check 'body: max_tokens present when budgeted' ($bodyB -match '"max_tokens":512') $bodyB
  Check 'body: reasoning.max_tokens present when budgeted' ($bodyB -match '"reasoning":\{"max_tokens":2048\}') $bodyB
  $bodyU = New-HttpRequestBody -Model 'm' -PromptText 'p' -SchemaObj @{type='object'}
  Check 'body: budgets absent when unset' (($bodyU -notmatch 'max_tokens') -and ($bodyU -notmatch '"reasoning"')) $bodyU
  $bodyP = New-HttpRequestBody -Model 'm' -PromptText 'p' -SchemaObj $null -MaxTokens 8
  Check 'body: null schema omits response_format (the probe shape)' ($bodyP -notmatch 'response_format') $bodyP

  # ---- fallback target resolution (Decision 3 / Design step 0d) -------------
  $envA = Join-Path $sandbox 'a.env'
  Write-Utf8NoBom $envA "OTHER_KEY=x`n# OPENROUTER_API_KEY=commented-out`n"
  $envB = Join-Path $sandbox 'b.env'
  Write-Utf8NoBom $envB "OPENROUTER_API_KEY=`"sk-test-123`"`n"
  Check 'env: value read with quotes stripped' ((Read-EnvValue -Path $envB -Name 'OPENROUTER_API_KEY') -eq 'sk-test-123') 'quote handling'
  Check 'env: commented-out key reads null' ($null -eq (Read-EnvValue -Path $envA -Name 'OPENROUTER_API_KEY')) 'comment line matched'

  # keyless target: must be recorded unusable BEFORE any network I/O (port 9 is unroutable)
  $tKeyless = @{ name='t'; kind='openrouter'; base_url='http://127.0.0.1:9/v1'; model='m'
                 key_env='OPENROUTER_API_KEY'; key_files=@($envA) }
  $rK = Resolve-FallbackTarget -Target $tKeyless
  Check 'fallback: keyless target is unusable (no credential), never dispatched' ((-not $rK.usable) -and ($rK.reason -like 'no credential*')) "$($rK.reason)"

  function Start-StubServer {
    # Routing stub for Resolve-FallbackTarget: /ping for readiness, models
    # responses in sequence (first vs rest), everything else is the chat body.
    # Serves EXACTLY $Requests requests then exits, so the job completes on its
    # own -- Remove-Job -Force on a job blocked in GetContext() stalls for
    # minutes, which is what turned this self-test from seconds into minutes.
    param([int]$Port,[int]$Requests,[string]$ModelsFirst,[string]$ModelsRest,[string]$Chat)
    Start-Job -ScriptBlock {
      param($p,$n,$m1,$m2,$chat)
      $l = New-Object Net.HttpListener; $l.Prefixes.Add("http://127.0.0.1:$p/"); $l.Start()
      $served = 0; $mCount = 0
      while ($served -lt $n) {
        $ctx = $l.GetContext()
        $path = $ctx.Request.Url.AbsolutePath
        # pings are free: readiness polling must not race the request budget
        $body = 'pong'
        if ($path -notlike '*ping*') {
          $served++
          $body = if ($path -like '*models*') { $mCount++; if ($mCount -eq 1) { $m1 } else { $m2 } }
                  else { $chat }
        }
        $b = [Text.Encoding]::UTF8.GetBytes($body)
        $ctx.Response.StatusCode = 200; $ctx.Response.ContentType = 'application/json'
        # explicit length + no keep-alive, and a beat before Stop(): http.sys
        # aborts a still-buffered send when the listener stops immediately.
        $ctx.Response.ContentLength64 = $b.Length
        $ctx.Response.KeepAlive = $false
        $ctx.Response.OutputStream.Write($b,0,$b.Length)
        $ctx.Response.OutputStream.Flush()
        $ctx.Response.Close()
      }
      Start-Sleep -Milliseconds 400
      $l.Stop()
    } -ArgumentList $Port,$Requests,$ModelsFirst,$ModelsRest,$Chat
  }
  function Wait-Stub([int]$Port) {
    foreach ($i in 1..40) {
      try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/ping" -TimeoutSec 2 -UseBasicParsing; return $true }
      catch { Start-Sleep -Milliseconds 150 }
    }
    $false
  }

  $chatOk = '{"choices":[{"finish_reason":"stop","message":{"content":"OK"}}]}'
  try {
    # lmstudio: not-loaded at resolution time; the warm-up completion loads it
    $mNot  = '{"data":[{"id":"stub-fb","object":"model","state":"not-loaded","max_context_length":262144}]}'
    $mLoad = '{"data":[{"id":"stub-fb","object":"model","state":"loaded","max_context_length":262144,"loaded_context_length":32768}]}'
    $portFb = Get-FreePort
    $job1 = Start-StubServer -Port $portFb -Requests 3 -ModelsFirst $mNot -ModelsRest $mLoad -Chat $chatOk
    if (Wait-Stub $portFb) {
      $tLm = @{ name='stubfb'; kind='lmstudio'; base_url="http://127.0.0.1:$portFb/v1"; model='stub-fb'; key_env=$null; key_files=@() }
      $r1 = Resolve-FallbackTarget -Target $tLm -ProbeTimeoutSec 15
      Check 'fallback: warm-up promotes not-loaded to usable' ($r1.usable -eq $true) "$($r1.reason)"
      Check 'fallback: ceiling from loaded_context_length (3 B/token, 25% headroom)' ($r1.ceiling_bytes -eq 73728) "$($r1.ceiling_bytes)"
      Check 'fallback: deadline probe recorded (seconds, bytes, finish_reason)' (($null -ne $r1.probe_seconds) -and ($r1.probe_bytes -gt 0) -and ($r1.probe_finish_reason -eq 'stop')) "s=$($r1.probe_seconds) b=$($r1.probe_bytes) fr=$($r1.probe_finish_reason)"
    } else { Skip 'fallback lmstudio leg' 'stub did not come up' }
    $null = Wait-Job $job1 -Timeout 5; Remove-Job $job1 -Force -ErrorAction SilentlyContinue

    # unserved model
    $portFb = Get-FreePort
    $job2 = Start-StubServer -Port $portFb -Requests 1 -ModelsFirst $mLoad -ModelsRest $mLoad -Chat $chatOk
    if (Wait-Stub $portFb) {
      $tMiss = @{ name='x'; kind='lmstudio'; base_url="http://127.0.0.1:$portFb/v1"; model='nope'; key_env=$null; key_files=@() }
      $r2 = Resolve-FallbackTarget -Target $tMiss -ProbeTimeoutSec 15
      Check 'fallback: unserved model is unusable up front' ((-not $r2.usable) -and ($r2.reason -like '*not served*')) "$($r2.reason)"
    } else { Skip 'fallback unserved-model leg' 'stub did not come up' }
    $null = Wait-Job $job2 -Timeout 5; Remove-Job $job2 -Force -ErrorAction SilentlyContinue

    # loaded context too small for the per-part overhead
    $mTiny = '{"data":[{"id":"stub-fb","object":"model","state":"loaded","loaded_context_length":100}]}'
    $portFb = Get-FreePort
    $job3 = Start-StubServer -Port $portFb -Requests 3 -ModelsFirst $mTiny -ModelsRest $mTiny -Chat $chatOk
    if (Wait-Stub $portFb) {
      $tTiny = @{ name='tiny'; kind='lmstudio'; base_url="http://127.0.0.1:$portFb/v1"; model='stub-fb'; key_env=$null; key_files=@() }
      $r3 = Resolve-FallbackTarget -Target $tTiny -ProbeTimeoutSec 15
      Check 'fallback: ceiling below the per-part overhead is unusable' ((-not $r3.usable) -and ($r3.reason -like '*below the per-part overhead*')) "$($r3.reason)"
    } else { Skip 'fallback tiny-context leg' 'stub did not come up' }
    $null = Wait-Job $job3 -Timeout 5; Remove-Job $job3 -Force -ErrorAction SilentlyContinue

    # openrouter branch: credential from the SECOND .env file, ceiling from context_length
    $mOr = '{"data":[{"id":"mm","context_length":16384}]}'
    $portFb = Get-FreePort
    $job4 = Start-StubServer -Port $portFb -Requests 2 -ModelsFirst $mOr -ModelsRest $mOr -Chat $chatOk
    if (Wait-Stub $portFb) {
      $tOr = @{ name='stub-openrouter'; kind='openrouter'; base_url="http://127.0.0.1:$portFb/v1"; model='mm'
                key_env='OPENROUTER_API_KEY'; key_files=@($envA,$envB) }
      $r4 = Resolve-FallbackTarget -Target $tOr -ProbeTimeoutSec 15
      Check 'fallback: credential resolves from the second .env file' (($r4.usable -eq $true) -and ($r4.key_source -eq $envB) -and ($r4.api_key -eq 'sk-test-123')) "usable=$($r4.usable) reason=$($r4.reason) src=$($r4.key_source)"
      Check 'fallback: openrouter ceiling from context_length' ($r4.ceiling_bytes -eq 36864) "$($r4.ceiling_bytes)"
    } else { Skip 'fallback openrouter leg' 'stub did not come up' }
    $null = Wait-Job $job4 -Timeout 5; Remove-Job $job4 -Force -ErrorAction SilentlyContinue
  } catch {
    Skip 'fallback resolution leg' $_.Exception.Message
  }

  # deadline scaling is pure arithmetic; no stub needed
  $probe = @{ probe_seconds = 10; probe_bytes = 100 }
  Check 'fallback deadline: floored at the primary for a small part' ((Get-FallbackDeadline -Resolved $probe -PartBytes 100) -eq 900) 'floor lost'
  Check 'fallback deadline: scales by the part/probe byte ratio' ((Get-FallbackDeadline -Resolved $probe -PartBytes 20000) -eq 2000) 'scaling wrong'
  Check 'fallback deadline: capped at the 3600 s measurement ceiling' ((Get-FallbackDeadline -Resolved $probe -PartBytes 100000) -eq 3600) 'uncapped multi-hour deadline'

  # the report-header record must never carry the raw credential
  $fakeResolved = [ordered]@{ name='t'; api_key='sk-secret-xyz'; ceiling_bytes=1 }
  $hdr = Get-FallbackReportRecord -Resolved $fakeResolved
  $hdrJson = $hdr | ConvertTo-Json -Compress
  Check 'fallback header record: api_key never enters the report' (($hdrJson -notmatch 'sk-secret') -and ($hdr.api_key_present -eq $true)) $hdrJson

  # a missing validator must throw loud, never fail open into a false-clean
  $savedPy = $script:PythonExe
  $script:PythonExe = 'C:\nonexistent\python.exe'
  $threw = $false
  try { $null = New-SchemaValidator -ReportDir $sandbox } catch { $threw = $true }
  $script:PythonExe = $savedPy
  Check 'schema validator: missing python throws, never fails open' $threw 'silent false-clean'

  # ---- retry ledger (attempts.json / Decision 4) ----------------------------
  $attPath = Join-Path $sandbox 'attempts.json'
  $null = Add-AttemptRecord -Path $attPath -Keys @('1.1','1.2') -Stem 'stem-a' -Pass 'first' -Class 'INFRASTRUCTURE_FAILURE' -Rule '1b' -Charge $true
  $led = Read-AttemptsLedger $attPath
  Check 'attempts: a whole-area dispatch charges every unit key' (($led['1.1'].spent -eq 1) -and ($led['1.2'].spent -eq 1)) "1.1=$($led['1.1'].spent) 1.2=$($led['1.2'].spent)"
  $null = Add-AttemptRecord -Path $attPath -Keys @('1.1') -Stem 'stem-b' -Pass 'resplit' -Class 'TRUNCATED_OR_MALFORMED' -Rule '4' -Charge $true
  Check 'attempts: a resplit part inherits its parent key''s spent count' ((Get-AttemptsSpent -Path $attPath -Key '1.1') -eq 2) "$(Get-AttemptsSpent -Path $attPath -Key '1.1')"
  $null = Add-AttemptRecord -Path $attPath -Keys @('1.1') -Stem 'stem-c' -Pass 'first' -Class 'ACCEPTED' -Rule '7' -Charge $false
  $led = Read-AttemptsLedger $attPath
  Check 'attempts: a non-charging class is recorded without spending' (($led['1.1'].spent -eq 2) -and (@($led['1.1'].attempts).Count -eq 3)) "spent=$($led['1.1'].spent) n=$(@($led['1.1'].attempts).Count)"
  Check 'attempts: a missing key reads as zero' ((Get-AttemptsSpent -Path $attPath -Key 'sweep.9') -eq 0) 'phantom budget'
  Check 'attempts: the charge map follows Decision 4' ((Test-ChargesRetry 'INFRASTRUCTURE_FAILURE') -and (Test-ChargesRetry 'TRUNCATED_OR_MALFORMED') -and (Test-ChargesRetry 'UNGROUNDED_RESPONSE') -and -not (Test-ChargesRetry 'ACCEPTED') -and -not (Test-ChargesRetry 'CLASSIFIER_TRIP') -and -not (Test-ChargesRetry 'BLOCKED') -and -not (Test-ChargesRetry 'AUTH_LAPSED') -and -not (Test-ChargesRetry 'ENTITLEMENT_BLOCKED')) 'wrong class charges the retry budget'
  $threw = $false
  try { $null = Add-AttemptRecord -Path $attPath -Keys @('all') -Stem 's' -Pass 'first' -Class 'ACCEPTED' -Rule '7' -Charge $false } catch { $threw = $true }
  Check 'attempts: the literal all is refused as a budget key' $threw 'all must stay a stem token only'
  if (Test-Path $script:PythonExe) {
    $atSchema = Join-Path $PSScriptRoot 'attempts.schema.json'
    if (Test-Path $atSchema) {
      $rA = Test-AgainstSchema -SchemaPath $atSchema -Json (Read-Utf8 $attPath)
      Check 'attempts ledger validates against attempts.schema.json' $rA.valid ($rA.errors -join '; ')
      $rBad = Test-AgainstSchema -SchemaPath $atSchema -Json '{"all":{"spent":0,"attempts":[]}}'
      Check 'attempts.schema.json rejects an all key' (-not $rBad.valid) 'schema accepted the all key'
    } else { Skip 'attempts schema validation' 'no attempts.schema.json' }
  } else { Skip 'attempts schema validation' 'no python' }
  Write-Utf8NoBom $attPath '{"torn'
  $threw = $false
  try { $null = Read-AttemptsLedger $attPath } catch { $threw = $true }
  Check 'attempts: an unparseable ledger is halt-and-surface, not a fresh start' $threw 'a reset budget un-terminates the resplit loop'
  Remove-Item -LiteralPath $attPath -Force -ErrorAction SilentlyContinue

  # ---- invocation string: the smoke gate reads it back from .meta.json ------
  $inv = New-InvocationString -Kind 'codex' -Model 'gpt-5.6-sol' -Cwd 'C:/wt' -ReasoningEffort 'high'
  Check 'invocation carries the escaped model_reasoning_effort substring' ($inv -like '*model_reasoning_effort=\"high\"*') $inv
  $mInv = New-MarkerObject -Kind 'codex' -Stem $stemAll -Area '1' -Units @('1.1') -Pass 'first' -Model 'gpt-5.6-sol' `
            -PromptPath $promptPath -Invocation $inv -ReportDir $sandbox -SchemaHash $hash `
            -DeadlineSeconds 900 -Attempt 1 -RetriesSpent 0
  $mtInv = New-MetaObject -Marker $mInv -Exit $null -TimedOut $false -Orphaned $true -Seconds $null
  Check 'orphan meta recovers reasoning_effort from the invocation' ($mtInv.reasoning_effort -eq 'high') "$($mtInv.reasoning_effort)"

  # ---- stem-leaf prompt copy (the caller cannot pre-name the timestamp) -----
  $cp = Copy-PromptToStem -PromptPath $promptPath -Stem $stemAll -ReportDir $sandbox
  Check 'prompt copy is stem-leaf-named under prompts/' ($cp -eq (Join-Path (Join-Path $sandbox 'prompts') ((Split-Path -Leaf $stemAll) + '.md'))) $cp
  Check 'prompt copy is byte-identical' ((Read-Utf8 $cp) -ceq (Read-Utf8 $promptPath)) 'bytes differ'

  # ---- classify: stale auth noise must not halt a successful orphan ---------
  $c = Get-DispatchClass -Meta (Meta @{exit=$null; orphaned=$true}) -OutputText $good -LogText '' `
        -StderrText '401 Unauthorized: refresh_token_reused' -SchemaValidator $validator
  Check 'classify: auth noise in a successful orphan''s stderr is not AUTH_LAPSED' ($c.class -ne 'AUTH_LAPSED') "$($c.class)/$($c.rule)"

  # ---- rule 4: schema-invalid output re-dispatches as resplit ---------------
  $c = Get-DispatchClass -Meta (Meta @{}) -OutputText '{"not":"the schema"}' -LogText '' -StderrText '' -SchemaValidator $validator
  Check 'classify: schema-invalid output is rule 4' (($c.rule -eq '4') -and ($c.class -eq 'TRUNCATED_OR_MALFORMED')) "$($c.class)/$($c.rule)"

  # ---- redaction survives a JSON round trip (a resumed session reads the
  #      record back from disk as a PSCustomObject) ---------------------------
  $rtResolved = ('{"name":"t","api_key":"sk-secret-xyz","ceiling_bytes":1}' | ConvertFrom-Json)
  $hdrRt = Get-FallbackReportRecord -Resolved $rtResolved
  Check 'fallback header record: JSON-round-tripped record also redacts' ((($hdrRt | ConvertTo-Json -Compress) -notmatch 'sk-secret') -and ($hdrRt.api_key_present -eq $true)) ($hdrRt | ConvertTo-Json -Compress)

  # ---- killed sentinel: preferred over a revived shell's .meta.json ---------
  Write-Utf8NoBom "$stemAll.json" $good
  Write-Utf8NoBom "$stemAll.meta.json" ($mtGood | ConvertTo-Json -Depth 12)
  $mtKilled = New-MetaObject -Marker $marker -Exit $null -TimedOut $true -Orphaned $false -Seconds $null `
                -Extra @{ reasoning_effort='high'; sandbox='read-only'; cwd='C:/x'; killed_by='orchestrator-deadline' }
  Write-Utf8NoBom "$stemAll.meta.killed.json" ($mtKilled | ConvertTo-Json -Depth 12)
  Write-Marker $markerPath $marker
  $rKs = Resolve-Marker $markerPath
  $rKsKilledBy = if ($rKs.ContainsKey('meta')) { Get-ObjProp $rKs.meta 'killed_by' } else { $null }
  Check 'resume (a): killed sentinel preferred over a revived shell''s meta' (($rKs.action -eq 'classify') -and ($rKsKilledBy -eq 'orchestrator-deadline')) "$($rKs.action)/$rKsKilledBy"
  Check 'resume (a): marker cleared after a killed-sentinel classify' (-not (Test-Path -LiteralPath $markerPath)) 'marker survives'
  if ((Test-Path $script:PythonExe) -and (Test-Path $mtSchema)) {
    $rkv = Test-AgainstSchema -SchemaPath $mtSchema -Json ($mtKilled | ConvertTo-Json -Depth 12)
    Check 'killed meta validates against meta.schema.json' $rkv.valid ($rkv.errors -join '; ')
  }
  Remove-Item -LiteralPath "$stemAll.meta.killed.json" -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath "$stemAll.meta.json" -Force -ErrorAction SilentlyContinue

  # ---- a ZERO-BYTE killed sentinel must halt, never classify-null -----------
  # ('' | ConvertFrom-Json is a silent null in PS 5.1: without the whitespace
  # guard this cleared the marker and shadowed the healthy .meta.json beside it.)
  Write-Utf8NoBom "$stemAll.meta.json" ($mtGood | ConvertTo-Json -Depth 12)
  Write-Utf8NoBom "$stemAll.meta.killed.json" ''
  Write-Marker $markerPath $marker
  $rZ = Resolve-Marker $markerPath
  Check 'resume (a): zero-byte killed sentinel halts, never classify-null' ($rZ.action -eq 'halt') $rZ.action
  Check 'resume (a): halt keeps the marker (a torn sentinel is evidence)' (Test-Path -LiteralPath $markerPath) 'marker cleared on halt'
  Remove-Item -LiteralPath "$stemAll.meta.killed.json" -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath "$stemAll.meta.json" -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue

  # ---- resume: a live in-deadline job waits and KEEPS its marker ------------
  $slowC = Join-Path $sandbox 'slow-codex.js'
  Write-Utf8NoBom $slowC 'setTimeout(()=>process.exit(0), 30000); process.stdin.resume();'
  $stemW = New-Stem -ReportDir $sandbox -Area 'smoke' -Units @('smoke.5') -Pass 'first' -Model 'fake' -Smoke
  $pW = Start-Process -FilePath node -ArgumentList @($slowC) -PassThru -NoNewWindow
  $null = $pW.Handle
  $mW = New-MarkerObject -Kind 'codex' -Stem $stemW -Area 'smoke' -Units @('smoke.5') -Pass 'first' `
          -Model 'fake' -PromptPath $promptPath -Invocation 'fake' -ReportDir $sandbox -SchemaHash $hash `
          -DeadlineSeconds 60 -Attempt 1 -RetriesSpent 0
  $mW.pid = $pW.Id; $mW.startTime = Get-Iso $pW.StartTime
  $mkW = Join-Path $sandbox 'raw\inflight\wait.json'
  Write-Marker $mkW $mW
  $rW = Resolve-Marker $mkW
  Check 'resume (c): live in-deadline job returns wait' ($rW.action -eq 'wait') $rW.action
  Check 'resume (c): the wait branch keeps its marker' (Test-Path -LiteralPath $mkW) 'marker deleted on wait'
  try { $pW.Kill($true) } catch { try { $pW.Kill() } catch { } }
  Remove-Item -LiteralPath $mkW -Force -ErrorAction SilentlyContinue

  Write-Host "------------------------------"
  Write-Host ("CHECKS: passed={0} failed={1} skipped={2}" -f $script:selfTestPasses, $script:selfTestFails.Count, $script:selfTestSkips.Count)
  if ($script:selfTestFails.Count -eq 0 -and $script:selfTestSkips.Count -eq 0) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green; return 0
  }
  if ($script:selfTestFails.Count) {
    Write-Host ("{0} CHECK(S) FAILED: {1}" -f $script:selfTestFails.Count, ($script:selfTestFails -join ', ')) -ForegroundColor Red
  }
  if ($script:selfTestSkips.Count) {
    Write-Host ("{0} LEG(S) SKIPPED: {1} -- a skipped leg is unverified, and unverified must not read as green. Re-run; skips here are environmental (a busy port, a transient lock), not expected states." -f $script:selfTestSkips.Count, ($script:selfTestSkips -join ', ')) -ForegroundColor Yellow
  }
  return 1
}

# ---------------------------------------------------------------------- main

# Dot-sourced (`. .\dispatch.ps1`) means "load the functions" -- manifest.py's
# PowerShell-side helpers and the resume path both need Get-DispatchClass and
# Resolve-Marker without dispatching anything.
if ($MyInvocation.InvocationName -eq '.') { return }

if ($SelfTest) { exit (Invoke-SelfTest -ReportDir $ReportDir) }

if (-not $Kind) { throw "specify -Kind codex|http, or -SelfTest" }

# Preconditions first: nothing is minted and no marker is written until every
# required input is present, so a bad invocation leaves no residue behind.
$missing = @()
if (-not $Area)                      { $missing += 'Area' }
if (-not $Units -or $Units.Count -eq 0) { $missing += 'Units' }
if (-not $Model)                     { $missing += 'Model' }
if (-not $PromptPath)                { $missing += 'PromptPath' }
if ($Kind -eq 'codex' -and -not $Cwd){ $missing += 'Cwd' }
if ($Kind -eq 'http'  -and -not $BaseUrl) { $missing += 'BaseUrl' }
if ($missing.Count) { throw ("missing required parameter(s): " + ($missing -join ', ')) }
if ($Units -contains 'all') {
  throw "'all' is a stem token, never a unit: pass the enumerated sub-probe keys (Decision 4's charging rule needs them, and New-Stem derives the 'all' token itself for a multi-unit dispatch)."
}
if (-not (Test-Path -LiteralPath $PromptPath)) { throw "prompt file not found: $PromptPath" }
if ($Kind -eq 'http') {
  $isLoopback = $BaseUrl -match '^https?://(127\.0\.0\.1|localhost|\[::1\])'
  if (-not $isLoopback -and -not $ApiKey) {
    throw "refusing to dispatch to $BaseUrl without -ApiKey: an unauthenticated request returns 401, which classifies as INFRASTRUCTURE_FAILURE and burns the retry budget on a credential problem. Record the target unusable instead."
  }
}

$hash   = Get-SchemaHash $ReportDir
$stem   = New-Stem -ReportDir $ReportDir -Area $Area -Units $Units -Pass $Pass -Model $Model -Smoke:$Smoke
# The dispatched prompt is the stem-named copy, so every dispatch owns its own
# prompt file and the .meta.json audit chain points at bytes that cannot be
# overwritten by a retry (§ Files).
$stemPrompt = Copy-PromptToStem -PromptPath $PromptPath -Stem $stem -ReportDir $ReportDir
$marker = New-MarkerObject -Kind $Kind -Stem $stem -Area $Area -Units $Units -Pass $Pass `
            -Model $Model -PromptPath $stemPrompt `
            -Invocation (New-InvocationString -Kind $Kind -Model $Model -Cwd $Cwd -ReasoningEffort $ReasoningEffort -BaseUrl $BaseUrl) `
            -ReportDir $ReportDir -SchemaHash $hash -DeadlineSeconds $DeadlineSeconds `
            -Attempt $Attempt -RetriesSpent $RetriesSpent -BaseUrl $BaseUrl
$markerPath = Join-Path $ReportDir ("raw\inflight\" + (Split-Path -Leaf $stem) + ".json")

if ($Kind -eq 'codex') {
  $codexJs = if ($FakeCodexJs) { $FakeCodexJs } else { Join-Path $env:APPDATA 'npm\node_modules\@openai\codex\bin\codex.js' }
  Invoke-CodexDispatch -Marker $marker -MarkerPath $markerPath -CodexJs $codexJs -Cwd $Cwd -ReasoningEffort $ReasoningEffort | ConvertTo-Json -Depth 12
} else {
  Invoke-HttpDispatch  -Marker $marker -MarkerPath $markerPath -ApiKey $ApiKey `
    -MaxTokens $MaxTokens -ReasoningMaxTokens $ReasoningMaxTokens | ConvertTo-Json -Depth 12
}
