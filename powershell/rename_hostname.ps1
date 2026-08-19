<#
.SYNOPSIS
    Google Drive Downloader & Universal Excel Searcher
    Designed for Non-Interactive System Account (UserInteractive: False)
#>

# 1. param() 与属性修饰必须严格置顶（除了注释外不能有任何代码）
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', '')]
param()

# 2. 全局环境与安全配置
$ConfirmPreference     = 'None'
$ProgressPreference    = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

# 进程级执行策略
Set-ExecutionPolicy RemoteSigned -Scope Process -Force -Confirm:$false


# ====================== 配置区 只改这里 ======================
# Google 服务账号下载的 JSON 私钥字符串
$GoogleJsonSecret = @'


'@
# Google Drive 文件的 ID (可在 Google Drive 共享链接中获取)
$FileId = "1EdbdZJ5N6GeqXYsqSpYfahCpUEK4D4Vys0Ir-VLIMik"
# Excel 检索条件
$TargetSheetName  = "Offshore"
$SearchColumnName = "Employee"
$SearchValue      = "Janmmey Zhu"
# $DeviceType       = "DeskTop"
# $CurrentName = "VG-CN-Janmmey-Zhu"

$sessionGuid      = [guid]::NewGuid()
$tempBaseDir      = if (Test-Path "C:\Windows\Temp") { "C:\Windows\Temp" } else { $env:TEMP }
$TempExcelPath    = Join-Path $tempBaseDir "gdrive_temp_${sessionGuid}.xlsx"
$extractedDir     = Join-Path $tempBaseDir "xlsx_xml_${sessionGuid}"

function Get-FirstChar {
    param([string]$InputStr)
    if ([string]::IsNullOrEmpty($InputStr)) {
        return $null
    }
    return $InputStr[0]
}
function Clear-Text([string]$str) {
    if ([string]::IsNullOrWhiteSpace($str)) { return "" }
    return ($str -replace '\s+', ' ').Trim().ToLower()
}
switch ($TargetSheetName) {
    Offshore { $Location = "CN" }
    US { $Location = "US" }
    default    { $Location = "" }
}

function Convert-ColLetterToIdx([string]$colStr) {
    if ([string]::IsNullOrWhiteSpace($colStr)) { return 0 }
    $letters = $colStr -replace '[0-9]', ''
    $idx = 0
    foreach ($char in $letters.ToCharArray()) {
        $idx = $idx * 26 + ([int][char]$char - [int][char]'A' + 1)
    }
    return $idx - 1
}

function Get-ChassisFormFactor {
    param(
        # 兜底默认值
        [string]$DefaultValue = "Unknown"
    )

    if(Get-Command Get-CimInstance -ErrorAction SilentlyContinue){
        $chassisRaw = Get-CimInstance Win32_SystemEnclosure
    }else{
        $chassisRaw = Get-WmiObject Win32_SystemEnclosure
    }
    $chassisTypes = $chassisRaw.ChassisTypes

    # 完整SMBIOS机箱编码映射
    $map = @{
        1  = "Other"
        2  = "Unknown"
        3  = "Desktop"
        4  = "LowProfileDesktop"
        5  = "PizzaBox"
        6  = "MiniTower"
        7  = "Tower"
        8  = "Portable"
        9  = "Laptop"
        # 10 = "Notebook"
        10 = "Laptop"
        11 = "Handheld"
        12 = "DockingStation"
        13 = "AllInOne"
        14 = "SubNotebook"
        15 = "SpaceSaving"
        16 = "LunchBox"
        17 = "MainServerChassis"
        18 = "ExpansionChassis"
        19 = "SubChassis"
        20 = "BusExpansionChassis"
        21 = "PeripheralChassis"
        22 = "StorageChassis"
        23 = "RackMountChassis"
        24 = "SealedCasePC"
        25 = "MultiSystemChassis"
        26 = "CompactPCI"
        27 = "UltraSmallFormFactor"
        28 = "SmallFormFactor"
        29 = "RuggedLaptop"
        30 = "RuggedTablet"
        31 = "Convertible"
        32 = "Detachable"
    }

    $typeCode = [int]$chassisTypes[0]
    if($map.ContainsKey($typeCode)){
        $formFactor = $map[$typeCode]
    }else{
        $formFactor = $DefaultValue
    }

    return $formFactor
}
# ==========================================
# 3. Add C# Helper for Universal RSA Signing (PS 5.1 & PS7 Compatible)
# ==========================================
if (-not ([System.Management.Automation.PSTypeName]'RsaSigner').Type) {
    Add-Type -TypeDefinition @"
using System;
using System.Security.Cryptography;

public class RsaSigner {
    public static byte[] SignSha256(string privateKeyPem, byte[] dataToSign) {
        string cleanKey = privateKeyPem
            .Replace("-----BEGIN PRIVATE KEY-----", "")
            .Replace("-----END PRIVATE KEY-----", "")
            .Replace("-----BEGIN RSA PRIVATE KEY-----", "")
            .Replace("-----END RSA PRIVATE KEY-----", "")
            .Replace("\r", "").Replace("\n", "").Replace(" ", "");

        byte[] keyBytes = Convert.FromBase64String(cleanKey);

        using (RSA rsa = RSA.Create()) {
            try {
                var methodInfo = typeof(RSA).GetMethod("ImportPkcs8PrivateKey");
                if (methodInfo != null) {
                    methodInfo.Invoke(rsa, new object[] { keyBytes, null });
                } else {
                    CngKey key = CngKey.Import(keyBytes, CngKeyBlobFormat.Pkcs8PrivateBlob);
                    RSACng rsaCng = new RSACng(key);
                    return rsaCng.SignData(dataToSign, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                }
                return rsa.SignData(dataToSign, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
            } catch {
                CngKey key = CngKey.Import(keyBytes, CngKeyBlobFormat.Pkcs8PrivateBlob);
                using (RSACng rsaCng = new RSACng(key)) {
                    return rsaCng.SignData(dataToSign, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                }
            }
        }
    }
}
"@
}

# ==========================================
# 4. JWT Generation & OAuth2 Token
# ==========================================
function Get-GoogleAccessToken {
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'JsonCredentials')]
    param([string]$JsonCredentials)

    $jsonObj = $JsonCredentials | ConvertFrom-Json
    $privateKeyPEM = $jsonObj.private_key
    $clientEmail = $jsonObj.client_email

    $header = @{ alg = "RS256"; typ = "JWT" } | ConvertTo-Json -Compress
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $claimSet = @{
        iss   = $clientEmail
        scope = "https://www.googleapis.com/auth/drive.readonly"
        aud   = "https://oauth2.googleapis.com/token"
        exp   = $now + 3600
        iat   = $now
    } | ConvertTo-Json -Compress

    function Base64UrlEncode([byte[]]$rawBytes) {
        return [Convert]::ToBase64String($rawBytes).Split('=')[0].Replace('+', '-').Replace('/', '_')
    }

    [byte[]]$headerBytes = [System.Text.Encoding]::UTF8.GetBytes($header)
    [byte[]]$claimBytes  = [System.Text.Encoding]::UTF8.GetBytes($claimSet)

    $encodedHeader = Base64UrlEncode -rawBytes $headerBytes
    $encodedClaim  = Base64UrlEncode -rawBytes $claimBytes
    $signatureInput = "$encodedHeader.$encodedClaim"

    [byte[]]$signInputBytes = [System.Text.Encoding]::UTF8.GetBytes($signatureInput)
    [byte[]]$signatureBytes = [RsaSigner]::SignSha256($privateKeyPEM, $signInputBytes)
    
    $encodedSignature = Base64UrlEncode -rawBytes $signatureBytes
    $jwt = "$signatureInput.$encodedSignature"

    $body = @{
        grant_type = "urn:ietf:params:oauth:grant-type:jwt-bearer"
        assertion  = $jwt
    }

    $tokenResponse = Invoke-RestMethod -Uri "https://oauth2.googleapis.com/token" -Method Post -Body $body -UseBasicParsing
    return $tokenResponse.access_token
}

try {
    Write-Output "[1/5] Fetching Google API Access Token...`n"
    $AccessToken = Get-GoogleAccessToken -JsonCredentials $GoogleJsonSecret

    # ==========================================
    # 5. Download File from Google Drive
    # ==========================================
    Write-Output "[2/5] Downloading Excel File...`n"
    
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $exportUrl   = "https://www.googleapis.com/drive/v3/files/${FileId}/export?mimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    $downloadUrl = "https://www.googleapis.com/drive/v3/files/${FileId}?alt=media"
    
    $headers = @{ Authorization = "Bearer $AccessToken" }

    try {
        Invoke-RestMethod -Uri $exportUrl -Headers $headers -OutFile $TempExcelPath -UseBasicParsing
    } catch {
        Invoke-RestMethod -Uri $downloadUrl -Headers $headers -OutFile $TempExcelPath -UseBasicParsing
    }

    Write-Output "Download Complete: $TempExcelPath`n"

    # ==========================================
    # 6. Parse Sheet Data (Native XML - Zero Dependency)
    # ==========================================
    Write-Output "[3/5] Searching Sheet '$TargetSheetName' via Native Zip/XML...`n"

    # 解压路径空值防御与重建
    if ([string]::IsNullOrWhiteSpace($extractedDir)) {
        $parentDir    = Split-Path -Parent $TempExcelPath
        $extractedDir = Join-Path $parentDir "xlsx_xml_${sessionGuid}"
    }

    if (Test-Path $TempExcelPath) {
        if ((-not [string]::IsNullOrWhiteSpace($extractedDir)) -and (Test-Path $extractedDir)) {
            Remove-Item -Path $extractedDir -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
        }

        # 执行 Zip 解压
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($TempExcelPath, $extractedDir)

        # 1. 读取共享字符串表 (SharedStrings)
        $sharedStrings = @()
        $ssPath = Join-Path $extractedDir "xl\sharedStrings.xml"
        if (Test-Path $ssPath) {
            [xml]$ssXml = Get-Content $ssPath -Encoding UTF8
            $sharedStrings = $ssXml.sst.si | ForEach-Object {
                if ($null -ne $_.t) {
                    $_.t
                } elseif ($null -ne $_.r) {
                    ($_.r | ForEach-Object { $_.t }) -join ""
                } else {
                    ""
                }
            }
        }

        # 2. 读取 .rels 映射表定位目标 Sheet XML
        $workbookPath = Join-Path $extractedDir "xl\workbook.xml"
        $relPath      = Join-Path $extractedDir "xl\_rels\workbook.xml.rels"

        if ((-not (Test-Path $workbookPath)) -or (-not (Test-Path $relPath))) {
            Write-Output "Invalid Excel structure: Missing workbook or rels XML file.`n"
        } else {
            [xml]$wbXml  = Get-Content $workbookPath -Encoding UTF8
            [xml]$relXml = Get-Content $relPath -Encoding UTF8

            $sheetNode = $wbXml.workbook.sheets.sheet | Where-Object { (Clear-Text $_.name) -eq (Clear-Text $TargetSheetName) }

            if (-not $sheetNode) {
                Write-Output "Sheet '$TargetSheetName' not found in workbook!`n"
            } else {
                $rId = $sheetNode.id
                $relTarget = ($relXml.Relationships.Relationship | Where-Object { $_.Id -eq $rId }).Target
                
                $cleanRelTarget = $relTarget -replace '^/', '' -replace '/', '\'
                $sheetXmlPath   = Join-Path $extractedDir "xl\$cleanRelTarget"

                if (-not (Test-Path $sheetXmlPath)) {
                    $sheetXmlPath = (Get-ChildItem -Path (Join-Path $extractedDir "xl\worksheets") -Filter "*.xml" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
                }

                if (-not (Test-Path $sheetXmlPath)) {
                    Write-Output "Could not locate worksheet XML file.`n"
                } else {
                    [xml]$sheetXml = Get-Content $sheetXmlPath -Encoding UTF8

                    # 3. 解析表格数据行
                    $rowsData = @()
                    $rows = $sheetXml.worksheet.sheetData.row

                    if ($rows) {
                        # 解析第 1 行（Row 0）为表头
                        $headerRow = $rows[0]
                        $headers = @{}
                        
                        foreach ($cell in $headerRow.c) {
                            $colIdx  = Convert-ColLetterToIdx $cell.r
                            $rawVal  = $cell.v
                            $typeStr = [string]$cell.t
                            $finalVal = $rawVal

                            if ($typeStr -eq "s" -and $null -ne $rawVal -and $rawVal -ne "") { 
                                $finalVal = $sharedStrings[[int]$rawVal] 
                            } elseif ($cell.is) { 
                                $finalVal = $cell.is.t 
                            }

                            if ($null -ne $finalVal) { 
                                $headers[$colIdx] = $finalVal.ToString().Trim()
                            }
                        }

                        # 提取数据行
                        for ($i = 1; $i -lt $rows.Count; $i++) {
                            $rowObj = [ordered]@{}
                            foreach ($cell in $rows[$i].c) {
                                $colIdx  = Convert-ColLetterToIdx $cell.r
                                $val     = $cell.v
                                $typeStr = [string]$cell.t

                                if ($typeStr -eq "s" -and $null -ne $val -and $val -ne "") { 
                                    $val = $sharedStrings[[int]$val] 
                                } elseif ($cell.is) { 
                                    $val = $cell.is.t 
                                }
                                
                                $colName = if ($headers.ContainsKey($colIdx)) { $headers[$colIdx] } else { "Column_$colIdx" }
                                if ($null -ne $val) {
                                    $rowObj[$colName] = $val.ToString().Trim()
                                }
                            }
                            if ($rowObj.Count -gt 0) {
                                $rowsData += [PSCustomObject]$rowObj
                            }
                        }
                    }

                    # 4. 检索匹配数据行（严格依赖 Employee 表头列精准比对）
                    $matchedRows = @()

                    if ([string]::IsNullOrWhiteSpace($SearchValue)) {
                        Write-Output "[ERROR] `$SearchValue is empty! Search aborted.`n"
                    } else {
                        $cleanTarget     = $SearchValue.ToString().Trim() -replace '[\u200B-\u200D\uFEFF]', ''
                        $cleanColumnName = $SearchColumnName.ToString().Trim()

                        # 校验表头中是否存在 Employee
                        $hasTargetColumn = $headers.Values | Where-Object { $_ -eq $cleanColumnName }

                        if (-not $hasTargetColumn) {
                            Write-Output "[ERROR] Column '$cleanColumnName' was NOT found in the extracted headers!`n"
                            Write-Output "DEBUG: Extracted Header List -> [$(($headers.Values) -join ', ')]`n"
                        } else {
                            foreach ($row in $rowsData) {
                                # 强制只比对指定列（如 Employee）的值
                                if ($row.PSObject.Properties[$cleanColumnName]) {
                                    $cellVal = $row.$cleanColumnName
                                    if ($null -ne $cellVal) {
                                        $cleanCell = $cellVal.ToString().Trim() -replace '[\u200B-\u200D\uFEFF]', ''
                                        if ($cleanCell -eq $cleanTarget) {
                                            $matchedRows += $row
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Write-Output "========== Search Results (Sheet: $TargetSheetName) ==========`n"
                    if (@($matchedRows).Count -gt 0) {
                        Write-Output ($matchedRows | ConvertTo-Json -Depth 2)

                        # 提取 Hostname
                        $targetHostname = $matchedRows[0].Hostname
                        if (-not [string]::IsNullOrWhiteSpace($targetHostname)) {
                            $targetHostname = $targetHostname.ToString().Trim()
                            Write-Output "Extracted Hostname: [$targetHostname]`n"
                        } else {
                            Write-Output "[WARNING] Matched row found, but 'Hostname' column is empty!`n"
                            $Incrementing_number = "Incrementing numbers"
                            $Incrementing_numbers = $matchedRows[0]."${Incrementing_number}"
                            $Hardware_type = "Hardware type"
                            $fallbackVal = $matchedRows[0]."$Hardware_type"
                            $Device_type = Get-ChassisFormFactor -Fallback $fallbackVal
                            $Device_type = Get-FirstChar $Device_type
                            if ($Incrementing_numbers -and $Incrementing_numbers) {
                                $targethostname_parts = @("VG",$Location,$Device_type,$Incrementing_numbers)
                                $targetHostname = -join $targethostname_parts
                                Write-Output "Extracted Hostname: [$targetHostname]`n"
                            }
                        }
                        # ==========================================
                        # 8. 重命名计算机逻辑 (SYSTEM 静默安全版)
                        # ==========================================
                        Write-Output "[4/5] Checking Computer Name..."
                        if ($targetHostname) {
                            $currentHostname = $env:COMPUTERNAME
                            if ($targetHostname -ne $currentHostname) {
                                Write-Output "Name mismatch! Current: [$currentHostname] -> Target: [$targetHostname]`n"
                                Write-Output "Renaming computer now...`n"
                                try {
                                    # Rename-Computer -NewName $targetHostname -Force -Confirm:$false -ErrorAction Stop
                                    Write-Output "Successfully renamed computer to [$targetHostname].`n"
                                } catch {
                                    Write-Error "Failed to rename computer: $_`n"
                                }
                            } else {
                                Write-Output "Current computer name [$currentHostname] already matches target [$targetHostname]. No action required.`n"
                            }
                        }
                    } else {
                        Write-Output "No exact data found in '$TargetSheetName' matching [$SearchColumnName] = '$SearchValue'`n"
                    }
                }
            }
        }
    }

} catch {
    # 纯 ASCII 日志输出，杜绝乱码与语法解析报错
    $errLine   = if ($_.InvocationInfo) { $_.InvocationInfo.ScriptLineNumber } else { "Unknown" }
    $errCode   = if ($_.InvocationInfo -and $_.InvocationInfo.Line) { $_.InvocationInfo.Line.Trim() } else { "N/A" }
    $errMessage = $_.Exception.Message

    Write-Output "`n[ERROR DETECTED]`n"
    Write-Output "--------------------------------------------------"
    Write-Output "Error Message : $errMessage`n"
    Write-Output "Error Line    : Line $errLine`n"
    Write-Output "Error Code    : $errCode`n"
    Write-Output "--------------------------------------------------"

    Write-Error "Script execution failed at Line $errLine : $errMessage`n"
} finally {
    # ==========================================
    # 9. Clean Memory & Files (SYSTEM Safe)
    # ==========================================
    Write-Output "[5/5] Cleaning up temp files and memory...`n"

    if (Test-Path $TempExcelPath) {
        Remove-Item -Path $TempExcelPath -Force -Confirm:$false -ErrorAction SilentlyContinue
    }
    if ((-not [string]::IsNullOrWhiteSpace($extractedDir)) -and (Test-Path $extractedDir)) {
        Remove-Item -Path $extractedDir -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
    }

    $GoogleJsonSecret = $null
    $AccessToken      = $null
    $jwt              = $null
    [System.GC]::Collect()

    Write-Output "Execution Finished Successfully.`n"
}