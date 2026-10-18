param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9]{20}$')][string]$ProjectRef,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]{1,100}$')][string]$VaultSecretName,
 [switch]$Prepare,
 [string]$OutputPath
)
$ErrorActionPreference='Stop'
# Preparation only: no credential reads, CLI calls, provider calls, or cloud writes.
$activationText=@"
Ticket 9 activation requires separate reviewed infrastructure authorization.
Project: $ProjectRef (verify FREE DEVELOPMENT resource before any operation).
1. Enable and verify anonymous Auth; confirm two real owners.
2. Review all four migrations in timestamp order. All three applied migrations are
   immutable. The fourth, capture_server_only_photo_reads, is pending fresh source
   inspection and separate coordinator application. Keep all six Capture gates0.
   Before applying it verify EMPTY public.captures, Storage captures objects and
   private.capture_cleanup_jobs; the migration raises if any exist, deleting nothing.
   Do not create new Captures until the server-only policy is installed. Review
   advisors, Postgres/extension versions and compatibility.
   npx --yes supabase@2.120.0 link --project-ref $ProjectRef
   npx --yes supabase@2.120.0 db push --dry-run
   npx --yes supabase@2.120.0 db push
3. Securely set function secrets via CLI --env-file outside Git. Include current
   random 64-hex cleanup secret, URL, server secret, publishable key. Never log it.
   npx --yes supabase@2.120.0 functions deploy capture-cleanup --project-ref $ProjectRef
4. Enable scheduler extensions BEFORE capture_install_schedule (later authorization):
   Read versions first: select name,default_version,installed_version from
   pg_available_extensions where name in ('pg_cron','pg_net','supabase_vault');
   Enable pg_cron through Supabase Integrations > Cron > Enable Cron:
   https://supabase.com/docs/guides/cron/install
   Enable pg_net through Database > Extensions > pg_net > Enable:
   https://supabase.com/docs/guides/database/extensions/pg_net
   Verify installed versions/schemas and current compatibility, without blind upgrades:
   select e.extname,e.extversion,n.nspname from pg_extension e join pg_namespace n
   on n.oid=e.extnamespace where e.extname in ('pg_cron','pg_net','supabase_vault');
   Verify cron.schedule(text,text,text), net.http_post(text,jsonb,jsonb,jsonb,integer)
   and vault.decrypted_secrets exist. The schedule invocation allows 70000 ms for
   the bounded 60-second worker; individual Storage/RPC requests remain 5000 ms.
   The initial SUPABASE-OPERATION-READ.json was historical: Vault 0.3.1 only,
   pg_cron/pg_net uninstalled and zero Capture tables. Later coordinator evidence
   records the reviewed schedule installed and scheduled physical deletion observed.
   Verify current readiness; neither observation proves the new photo-read boundary.
   Create/update Vault secret '$VaultSecretName' securely, then service SQL:
   select public.capture_install_schedule('https://$ProjectRef.supabase.co/functions/v1/capture-cleanup','$VaultSecretName');
5. Observe cron.job, cron.job_run_details, net._http_response, worker last scheduled
   run and actual Storage absence. Run docs/capture.md fault/expiry/rotation gates.
6. With a readiness-isolated deployment run scripts/ticket9_supabase_evidence.py
   --authorized-live --api-url <development-api> --output <external-report>.
   Prove signed owner API200 exact accepted JPEG, same API URL404 after deletion,
   direct A/B/publishable Storage denial before/after API warm and after deletion,
   unchanged metadata authority and actual cron uncached physical removal.
7. After live proof only, enable all six documented attestations, including
   FURNITUREOS_CAPTURE_SERVER_PHOTOS_VERIFIED (default0). Paid/private
   owner/tape-reference/physical-phone gates remain separately authorized.
The Vercel CLI is absent; npm i -g vercel is recommended in a separate tooling
session for secure environment pull, deployment and logs. This script installs nothing.
"@
if ($Prepare) {
 if ([string]::IsNullOrWhiteSpace($OutputPath)) {throw 'An explicit external OutputPath is required.'}
 $resolvedOutput=[IO.Path]::GetFullPath($OutputPath)
 $workspacePath=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
 if ($resolvedOutput.StartsWith($workspacePath+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {throw 'Activation artifacts must be outside source.'}
 [IO.File]::WriteAllText($resolvedOutput,$activationText+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
} else {Write-Output $activationText}
