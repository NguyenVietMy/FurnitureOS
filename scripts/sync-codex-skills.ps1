# Re-copy .claude/skills into Codex's plugin cache.
# Codex snapshots local marketplaces at install time and `plugin marketplace upgrade`
# only refreshes Git sources, so a local marketplace re-syncs via remove + add.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    codex plugin remove furnitureos-skills@furnitureos
    codex plugin add furnitureos-skills@furnitureos
    $cache = "$env:USERPROFILE\.codex\plugins\cache\furnitureos\furnitureos-skills\0.1.0\skills"
    $n = (Get-ChildItem -Path $cache -Filter SKILL.md -Recurse).Count
    Write-Host "Synced $n skills to Codex." -ForegroundColor Green
}
finally { Pop-Location }
