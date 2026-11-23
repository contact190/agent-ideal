# Mise a jour a distance de l'Agent Ideal (pour les versions qui n'ont pas encore /majour).
# Lancement depuis Telegram, sans guillemets :
#   irm https://raw.githubusercontent.com/contact190/agent-ideal/main/maj_distance.ps1 | iex
$ErrorActionPreference = 'Stop'
$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*app.py*' } | Select-Object -First 1
if (-not $p) { throw 'Agent introuvable : aucun processus app.py en cours.' }
$dir = Split-Path ([regex]::Match($p.CommandLine, '"?([^"]*app\.py)').Groups[1].Value)
if (-not (Test-Path (Join-Path $dir 'app.py'))) { throw "Dossier de l'agent introuvable : $dir" }
Write-Output "Dossier de l'agent : $dir"
$z = Join-Path $env:TEMP 'ai-maj.zip'
$d = Join-Path $env:TEMP 'ai-maj'
Invoke-WebRequest 'https://github.com/contact190/agent-ideal/archive/refs/heads/main.zip' -OutFile $z -UseBasicParsing
if (Test-Path $d) { Remove-Item $d -Recurse -Force }
Expand-Archive $z $d
$src = Get-ChildItem $d -Directory | Select-Object -First 1
Copy-Item (Join-Path $src.FullName '*') $dir -Recurse -Force
Write-Output 'Fichiers copies.'
$py = Join-Path $dir '.venv\Scripts\python.exe'
$ErrorActionPreference = 'Continue'
& $py -m pip install qrcode --quiet --disable-pip-version-check 2>&1 | Out-Null
$ErrorActionPreference = 'Stop'
$sha = (Invoke-RestMethod 'https://api.github.com/repos/contact190/agent-ideal/commits/main').sha
Set-Content (Join-Path $dir '.version') $sha -NoNewline
$donnees = Join-Path $env:APPDATA 'AgentIdeal'
if (Test-Path $donnees) { Set-Content (Join-Path $donnees 'maj_terminee.json') ('{"version":"' + $sha.Substring(0,7) + '"}') }
$pythonw = Join-Path $dir '.venv\Scripts\pythonw.exe'
$app = Join-Path $dir 'app.py'
$r = Join-Path $env:TEMP 'ai-redemarrer.ps1'
$lignes = @(
  'Start-Sleep 8',
  ('Stop-Process -Id ' + $p.ProcessId + ' -Force -ErrorAction SilentlyContinue'),
  'Start-Sleep 2',
  ("Start-Process -FilePath '" + $pythonw + "' -ArgumentList @('""" + $app + """','--sans-navigateur','--apres-maj') -WorkingDirectory '" + $dir + "'")
)
Set-Content $r $lignes -Encoding UTF8
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',$r
Write-Output ('OK : mise a jour installee (version ' + $sha.Substring(0,7) + '). Redemarrage de l agent dans 8 secondes.')
