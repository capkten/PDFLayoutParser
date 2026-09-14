[CmdletBinding()]
param(
    [string]$ActualRoot = "output/fix_zh_all_table_pages_review_20260914",
    [string]$TestsetRoot = "output/fix_zh_all_table_pages_rerun_20260903/testset_markdown",
    [string]$ReviewDir = "output/fix_zh_all_table_pages_review_20260914/review"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = (Get-Command python -ErrorAction Stop).Source

Push-Location $repoRoot
try {
    $pathBase = $repoRoot
    if (!(Test-Path (Join-Path $pathBase $ActualRoot)) -and
        (Test-Path (Join-Path $repoRoot "..\..\output"))) {
        $pathBase = (Resolve-Path (Join-Path $repoRoot "..\..")).Path
    }
    $actualPath = (Resolve-Path (Join-Path $pathBase $ActualRoot)).Path
    $testsetPath = (Resolve-Path (Join-Path $pathBase $TestsetRoot)).Path
    $reviewPath = [System.IO.Path]::GetFullPath((Join-Path $pathBase $ReviewDir))
    $pythonCode = @"
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'src'))
from scripts.pdf_diff_review import build_review

summary = build_review(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
print(json.dumps({
    'page_count': summary['page_count'],
    'diff_count': summary['diff_count'],
    'category_counts': summary['category_counts'],
    'scan_errors': summary['scan_errors'],
}, ensure_ascii=False))
"@
    & $pythonExe -c $pythonCode $actualPath $testsetPath $reviewPath
    if ($LASTEXITCODE -ne 0) {
        throw "PDF diff review generation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
