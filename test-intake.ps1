param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$PayloadPath = (Join-Path $PSScriptRoot "8000050-66.2026.8.05.0161__intake-payload.json"),
    [string]$PdfPath = (Join-Path $PSScriptRoot "8000050-66.2026.8.05.0161-1776916884322-247201-habilitacao nos autos.pdf"),
    [string]$ApiKey,
    [int]$TimeoutSeconds = 120,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-FirstApiKey {
    param(
        [string]$RawValue
    )

    if ([string]::IsNullOrWhiteSpace($RawValue)) {
        return $null
    }

    foreach ($candidate in ($RawValue -split ",")) {
        $trimmed = $candidate.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            return $trimmed
        }
    }

    return $null
}

function Get-DotEnvValue {
    param(
        [string]$EnvPath,
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $EnvPath -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $trimmedLine = $line.Trim()
        if ($trimmedLine.StartsWith("#")) {
            continue
        }

        if ($trimmedLine -notmatch "^\s*${Key}\s*=") {
            continue
        }

        $value = $trimmedLine.Substring($trimmedLine.IndexOf("=") + 1).Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }

    return $null
}

function Normalize-BaseUrl {
    param(
        [string]$Url
    )

    if ([string]::IsNullOrWhiteSpace($Url)) {
        throw "BaseUrl não pode ser vazio."
    }

    return $Url.TrimEnd("/")
}

function Get-JsonPreview {
    param(
        [string]$JsonText
    )

    try {
        $parsed = $JsonText | ConvertFrom-Json
        return [pscustomobject]@{
            external_id = $parsed.external_id
            cnj_number = $parsed.cnj_number
        }
    }
    catch {
        throw "O arquivo de payload não contém JSON válido: $($_.Exception.Message)"
    }
}

$resolvedPayloadPath = (Resolve-Path -LiteralPath $PayloadPath).Path
$resolvedPdfPath = (Resolve-Path -LiteralPath $PdfPath).Path
$resolvedBaseUrl = Normalize-BaseUrl -Url $BaseUrl
$endpointUrl = "$resolvedBaseUrl/api/v1/prazos-iniciais/intake"
$envPath = Join-Path $PSScriptRoot ".env"

if (-not $ApiKey) {
    $ApiKey = Resolve-FirstApiKey -RawValue $env:PRAZOS_INICIAIS_API_KEY
}

if (-not $ApiKey) {
    $dotEnvApiKey = Get-DotEnvValue -EnvPath $envPath -Key "PRAZOS_INICIAIS_API_KEY"
    $ApiKey = Resolve-FirstApiKey -RawValue $dotEnvApiKey
}

if (-not $ApiKey) {
    throw "Não encontrei PRAZOS_INICIAIS_API_KEY. Passe -ApiKey ou configure a chave no .env."
}

$payloadJson = Get-Content -LiteralPath $resolvedPayloadPath -Raw -Encoding UTF8
$payloadPreview = Get-JsonPreview -JsonText $payloadJson

Write-Host ""
Write-Host "Teste de intake de prazos iniciais" -ForegroundColor Cyan
Write-Host "Endpoint : $endpointUrl"
Write-Host "Payload  : $resolvedPayloadPath"
Write-Host "PDF      : $resolvedPdfPath"
Write-Host "External : $($payloadPreview.external_id)"
Write-Host "CNJ      : $($payloadPreview.cnj_number)"

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run ativo: nenhuma chamada HTTP foi enviada." -ForegroundColor Yellow
    return
}

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw "curl.exe não está disponível neste Windows. Instale o curl ou rode em outro terminal."
}

$curlArgs = @(
    "-sS",
    "-X", "POST",
    $endpointUrl,
    "-H", "X-Intake-Api-Key: $ApiKey",
    "-F", "payload=<$resolvedPayloadPath;type=application/json",
    "-F", "habilitacao=@$resolvedPdfPath;type=application/pdf",
    "--max-time", $TimeoutSeconds.ToString(),
    "-w", "`n__HTTP_STATUS__:%{http_code}"
)

$rawOutput = & curl.exe @curlArgs 2>&1
$curlExitCode = $LASTEXITCODE

if ($rawOutput -is [System.Array]) {
    $rawOutput = ($rawOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
}

if ($curlExitCode -ne 0) {
    throw "curl falhou com código $curlExitCode.`n$rawOutput"
}

$statusMarker = "__HTTP_STATUS__:"
$markerIndex = $rawOutput.LastIndexOf($statusMarker)

if ($markerIndex -lt 0) {
    throw "Não consegui identificar o status HTTP na resposta do curl.`n$rawOutput"
}

$responseText = $rawOutput.Substring(0, $markerIndex).TrimEnd("`r", "`n")
$statusCodeText = $rawOutput.Substring($markerIndex + $statusMarker.Length).Trim()
$statusCode = 0

if (-not [int]::TryParse($statusCodeText, [ref]$statusCode)) {
    throw "Status HTTP inválido retornado pelo curl: '$statusCodeText'"
}

Write-Host ""
Write-Host "Status HTTP: $statusCode"

if ([string]::IsNullOrWhiteSpace($responseText)) {
    Write-Host "(sem corpo de resposta)"
}
else {
    try {
        $pretty = ($responseText | ConvertFrom-Json) | ConvertTo-Json -Depth 100
        Write-Host $pretty
    }
    catch {
        Write-Host $responseText
    }
}

if ($statusCode -lt 200 -or $statusCode -ge 300) {
    exit 1
}
