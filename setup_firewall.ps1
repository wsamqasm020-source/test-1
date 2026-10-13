# يجب تشغيل هذا السكربت كـ Administrator
# Right-click -> Run with PowerShell

$ruleName = "Attendance System LAN"
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

if ($existingRule) {
    Write-Host "[✓] القاعدة موجودة بالفعل: $ruleName"
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 5000 `
        -Action Allow `
        -Profile Private `
        -Description "Allow QR Attendance Flask server on LAN only (port 5000)"
    Write-Host "[✓] تم إضافة قاعدة الفايروول: $ruleName (شبكة خاصة فقط)"
}

Write-Host ""
Write-Host "للتحقق من القاعدة:"
Write-Host "  Get-NetFirewallRule -DisplayName '$ruleName'"
Read-Host "اضغط Enter للإغلاق"
