$target = "packages\app\node_modules\@modelcontextprotocol\ext-apps"
if (Test-Path $target) {
  Write-Output "FOUND: $target"
  Get-ChildItem -Path $target -Recurse -Include *.d.ts,*.mjs -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
} else {
  Write-Output "NOT at $target"
  Write-Output "Searching repo for ext-apps package..."
  Get-ChildItem -Path . -Recurse -Filter "package.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "ext-apps" } |
    Select-Object -First 5 -ExpandProperty FullName
}