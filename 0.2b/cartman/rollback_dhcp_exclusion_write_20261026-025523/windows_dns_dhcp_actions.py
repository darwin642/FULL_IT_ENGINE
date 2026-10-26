"""Allowlisted read/write DNS and DHCP operations for CartmanClient."""
import ipaddress
import json
import platform
import re
import shutil
import subprocess

MARKER = "windows_dns_dhcp_management_v1"
ALLOWED_OPERATIONS = {
    "read_dhcp", "read_dns",
    "read_dhcp_leases", "read_dhcp_reservations", "read_dhcp_exclusions",
    "dhcp_scope_options", "dhcp_scope_lease",
    "dhcp_reservation_add", "dhcp_reservation_delete",
    "dns_a_create", "dns_a_update", "dns_a_delete",
    "dns_cname_create", "dns_cname_update", "dns_cname_delete",
    "dns_zone_create",
}


def _ps(value):
    """Quote a value as a PowerShell single-quoted literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _ipv4(value, label):
    try:
        return str(ipaddress.IPv4Address(str(value)))
    except (ipaddress.AddressValueError, TypeError, ValueError) as exc:
        raise ValueError("{} must be a valid IPv4 address.".format(label)) from exc


def _safe_domain(value, label="DNS name", relative=False):
    value = str(value or "").rstrip(".")
    if relative and value == "@":
        return value
    if not value or len(value) > 253:
        raise ValueError("{} is invalid.".format(label))

    pattern = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if not all(re.fullmatch(pattern, part) for part in value.split(".")):
        raise ValueError("{} is invalid.".format(label))
    return value.lower()


def _run_powershell(module, body, timeout=180):
    if platform.system() != "Windows":
        return "Failed", json.dumps({
            "status": "Failed",
            "error": "DNS/DHCP management requires Windows.",
        })

    exe = (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh.exe")
        or shutil.which("pwsh")
    )
    if not exe:
        return "Failed", json.dumps({
            "status": "Failed", "error": "PowerShell was not found.",
        })

    script = (
        "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
        "$WarningPreference='SilentlyContinue';"
        "try{if(-not(Get-Module -ListAvailable -Name " + _ps(module) + ")){"
        "throw 'Required Windows DNS/DHCP PowerShell module is not installed.'};"
        "Import-Module " + _ps(module) + " -ErrorAction Stop;"
        + body +
        ";if(-not $out){throw 'Operation did not produce a result.'};"
        "[Console]::Out.WriteLine(($out|ConvertTo-Json -Depth 8 -Compress));exit 0"
        "}catch{$failure=[pscustomobject]@{status='Failed';"
        "operation='windows_dns_dhcp_action';server=$env:COMPUTERNAME;"
        "error=$_.Exception.Message};"
        "[Console]::Out.WriteLine(($failure|ConvertTo-Json -Depth 5 -Compress));"
        "exit 1}"
    )

    try:
        completed = subprocess.run(
            [
                exe, "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "Failed", json.dumps({
            "status": "Failed", "error": "PowerShell operation timed out.",
        })
    except OSError as exc:
        return "Failed", json.dumps({"status": "Failed", "error": str(exc)})

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    parsed = None

    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{"):
            try:
                parsed = json.loads(candidate)
                break
            except json.JSONDecodeError:
                pass

    if parsed is None:
        parsed = {
            "status": "Succeeded" if completed.returncode == 0 else "Failed",
            "error": "PowerShell returned no structured result.",
            "stdout": stdout[-2000:],
            "stderr": stderr[-1000:],
        }
    elif completed.returncode != 0:
        parsed["status"] = "Failed"
        if stderr and not parsed.get("error"):
            parsed["error"] = stderr[-1000:]

    success_flag = parsed.get("verified", parsed.get("read_only", False))
    success = (
        completed.returncode == 0
        and parsed.get("status") == "Succeeded"
        and bool(success_flag)
    )
    return (
        "Succeeded" if success else "Failed",
        json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
    )


def execute(payload):
    """Execute only fixed DNS/DHCP operations. Never accept arbitrary commands."""
    if not isinstance(payload, dict) or payload.get("connector_action") != MARKER:
        return "Failed", json.dumps({
            "status": "Failed", "error": "Missing DNS/DHCP capability marker.",
        })

    operation = payload.get("operation")
    if payload.get("confirmed") is not True:
        return "Failed", json.dumps({
            "status": "Failed",
            "error": "The server did not mark this operation as confirmed.",
        })
    if operation not in ALLOWED_OPERATIONS:
        return "Failed", json.dumps({
            "status": "Failed", "error": "Operation is not on the allowlist.",
        })
    if (
        operation not in {"read_dhcp", "read_dns", "read_dhcp_leases", "read_dhcp_reservations", "read_dhcp_exclusions"}
        and not str(payload.get("plan_id") or "").startswith("ndcp-")
    ):
        return "Failed", json.dumps({
            "status": "Failed", "error": "A confirmed change plan ID is required.",
        })

    params = payload.get("parameters") or {}
    if not isinstance(params, dict):
        return "Failed", json.dumps({
            "status": "Failed", "error": "Invalid parameters.",
        })

    try:
        if operation == "read_dhcp":
            body = r"""$server=$env:COMPUTERNAME;$all=@(Get-DhcpServerv4Scope -ComputerName $server -ErrorAction Stop);$shown=@($all|Select-Object -First 8|ForEach-Object{$s=$_;$o=@(Get-DhcpServerv4OptionValue -ComputerName $server -ScopeId $s.ScopeId -ErrorAction SilentlyContinue);[pscustomobject]@{scope_id=$s.ScopeId.ToString();name=$s.Name;start_ip=$s.StartRange.ToString();end_ip=$s.EndRange.ToString();state=$s.State.ToString();lease_duration=$s.LeaseDuration.ToString();gateway=@($o|Where-Object{$_.OptionId -eq 3}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_});dns_servers=@($o|Where-Object{$_.OptionId -eq 6}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_});dns_domain=@($o|Where-Object{$_.OptionId -eq 15}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})}});$out=[pscustomobject]@{status='Succeeded';read_only=$true;verified=$true;operation='read_dhcp';server=$server;scope_count=$all.Count;scopes_truncated=($all.Count -gt 8);scopes=$shown}"""
            return _run_powershell("DhcpServer", body)

        if operation in {"read_dhcp_leases", "read_dhcp_reservations", "read_dhcp_exclusions"}:
            scope = _ipv4(params.get("scope_id"), "DHCP scope ID")
            try:
                offset = int(params.get("offset", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("DHCP detail offset must be a non-negative whole number.") from exc
            if offset < 0 or offset > 100000:
                raise ValueError("DHCP detail offset must be between 0 and 100000.")
            page_size = 8
            common = (
                "$server=$env:COMPUTERNAME;"
                "$scopeId=" + _ps(scope) + ";"
                "$offset=" + str(offset) + ";$pageSize=" + str(page_size) + ";"
            )

            if operation == "read_dhcp_leases":
                body = common + r"""$all=@(Get-DhcpServerv4Lease -ComputerName $server -ScopeId $scopeId -ErrorAction Stop | Sort-Object {$_.IPAddress.ToString()});$items=@($all|Select-Object -Skip $offset -First $pageSize|ForEach-Object{$expiry='';if($_.LeaseExpiryTime){$expiry=$_.LeaseExpiryTime.ToString('o')};[pscustomobject]@{ip_address=$_.IPAddress.ToString();hostname=[string]$_.HostName;mac_address=[string]$_.ClientId;address_state=[string]$_.AddressState;lease_expiry=$expiry}});$out=[pscustomobject]@{status='Succeeded';read_only=$true;verified=$true;operation='read_dhcp_leases';server=$server;scope_id=$scopeId;count=$all.Count;offset=$offset;page_size=$pageSize;has_more=($offset+$items.Count -lt $all.Count);items=$items}"""
                return _run_powershell("DhcpServer", body)

            if operation == "read_dhcp_reservations":
                body = common + r"""$all=@(Get-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -ErrorAction Stop | Sort-Object {$_.IPAddress.ToString()});$items=@($all|Select-Object -Skip $offset -First $pageSize|ForEach-Object{[pscustomobject]@{ip_address=$_.IPAddress.ToString();mac_address=$_.ClientId.ToString().Replace(':','-').ToUpper();name=[string]$_.Name;type=[string]$_.Type}});$out=[pscustomobject]@{status='Succeeded';read_only=$true;verified=$true;operation='read_dhcp_reservations';server=$server;scope_id=$scopeId;count=$all.Count;offset=$offset;page_size=$pageSize;has_more=($offset+$items.Count -lt $all.Count);items=$items}"""
                return _run_powershell("DhcpServer", body)

            body = common + r"""$all=@(Get-DhcpServerv4ExclusionRange -ComputerName $server -ScopeId $scopeId -ErrorAction Stop | Sort-Object {$_.StartRange.ToString()});$items=@($all|Select-Object -Skip $offset -First $pageSize|ForEach-Object{[pscustomobject]@{start_ip=$_.StartRange.ToString();end_ip=$_.EndRange.ToString()}});$out=[pscustomobject]@{status='Succeeded';read_only=$true;verified=$true;operation='read_dhcp_exclusions';server=$server;scope_id=$scopeId;count=$all.Count;offset=$offset;page_size=$pageSize;has_more=($offset+$items.Count -lt $all.Count);items=$items}"""
            return _run_powershell("DhcpServer", body)

        if operation == "read_dns":
            body = r"""$server=$env:COMPUTERNAME;$allZones=@(Get-DnsServerZone -ComputerName $server -ErrorAction Stop);$zones=@($allZones|Select-Object -First 6);$records=@();foreach($z in $zones){$rr=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $z.ZoneName -ErrorAction SilentlyContinue|Select-Object -First 6);foreach($r in $rr){$v=switch($r.RecordType.ToString()){'A'{$r.RecordData.IPv4Address.ToString()}'AAAA'{$r.RecordData.IPv6Address.ToString()}'CNAME'{$r.RecordData.HostNameAlias}'NS'{$r.RecordData.NameServer}'PTR'{$r.RecordData.PtrDomainName}'MX'{$r.RecordData.MailExchange}'TXT'{(@($r.RecordData.DescriptiveText)-join '')}default{'(record data not expanded)'}};$records += [pscustomobject]@{zone=$z.ZoneName;name=$r.HostName;type=$r.RecordType.ToString();value=[string]$v;ttl=$r.TimeToLive.ToString()}}};$out=[pscustomobject]@{status='Succeeded';read_only=$true;verified=$true;operation='read_dns';server=$server;zone_count=$allZones.Count;zones_truncated=($allZones.Count -gt 6);records=$records}"""
            return _run_powershell("DnsServer", body)

        if operation == "dhcp_scope_options":
            scope = _ipv4(params.get("scope_id"), "Scope ID")
            gateway = _ipv4(params["router"], "Gateway") if params.get("router") else ""
            dns = params.get("dns_servers") or []
            if not isinstance(dns, list) or len(dns) > 8:
                raise ValueError("DNS servers must be a list of at most eight IPv4 addresses.")
            dns = [_ipv4(x, "DNS server") for x in dns]
            domain = (
                _safe_domain(params.get("dns_domain"), "DHCP DNS domain")
                if params.get("dns_domain") else ""
            )
            if not gateway and not dns and not domain:
                raise ValueError("Provide at least one DHCP option to change.")

            expected_before = params.get("expected_before")
            if not isinstance(expected_before, dict):
                raise ValueError(
                    "Live DHCP baseline is missing; nothing was changed."
                )
            if any(k not in expected_before for k in ("router", "dns_servers", "dns_domain")):
                raise ValueError("Live DHCP baseline is incomplete; nothing was changed.")

            def _expected_list(key, label, normalizer):
                values = expected_before.get(key, [])
                if isinstance(values, str):
                    values = [values] if values else []
                if not isinstance(values, list) or len(values) > 8:
                    raise ValueError("Invalid live DHCP baseline; nothing was changed.")
                return [normalizer(value, label) for value in values]

            before_router = _expected_list("router", "Expected router", _ipv4)
            before_dns = _expected_list("dns_servers", "Expected DNS server", _ipv4)
            before_domain = _expected_list(
                "dns_domain", "Expected DHCP DNS domain", _safe_domain
            )

            final_router = [gateway] if gateway else before_router
            final_dns = dns if dns else before_dns
            final_domain = [domain] if domain else before_domain

            parts = [
                "$server=$env:COMPUTERNAME",
                "$scopeId=" + _ps(scope),
                "$null=Get-DhcpServerv4Scope -ComputerName $server -ScopeId $scopeId -ErrorAction Stop",
                "$before=@(Get-DhcpServerv4OptionValue -ComputerName $server -ScopeId $scopeId -ErrorAction SilentlyContinue)",
                "$beforeRouter=@($before|Where-Object{$_.OptionId -eq 3}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "$beforeDns=@($before|Where-Object{$_.OptionId -eq 6}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "$beforeDomain=@($before|Where-Object{$_.OptionId -eq 15}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "$expectedBeforeRouter=@(" + ",".join(_ps(x) for x in before_router) + ")",
                "$expectedBeforeDns=@(" + ",".join(_ps(x) for x in before_dns) + ")",
                "$expectedBeforeDomain=@(" + ",".join(_ps(x) for x in before_domain) + ")",
                "if(($beforeRouter -join '|') -cne ($expectedBeforeRouter -join '|')){throw 'DHCP precondition failed: Router option changed since preview; nothing was changed.'}",
                "if(($beforeDns -join '|') -cne ($expectedBeforeDns -join '|')){throw 'DHCP precondition failed: DNS servers changed since preview; nothing was changed.'}",
                "if(($beforeDomain -join '|') -ine ($expectedBeforeDomain -join '|')){throw 'DHCP precondition failed: DNS domain changed since preview; nothing was changed.'}",
                "$expectedFinalRouter=@(" + ",".join(_ps(x) for x in final_router) + ")",
                "$expectedFinalDns=@(" + ",".join(_ps(x) for x in final_dns) + ")",
                "$expectedFinalDomain=@(" + ",".join(_ps(x) for x in final_domain) + ")",
                "$opt=@{ComputerName=$server;ScopeId=$scopeId}",
            ]
            if gateway:
                parts += ["$wantRouter=" + _ps(gateway), "$opt.Router=@(" + _ps(gateway) + ")"]
            if dns:
                parts += ["$wantDns=@(" + ",".join(_ps(x) for x in dns) + ")", "$opt.DnsServer=$wantDns"]
            if domain:
                parts += ["$wantDomain=" + _ps(domain), "$opt.DnsDomain=$wantDomain"]

            parts += [
                "Set-DhcpServerv4OptionValue @opt -ErrorAction Stop | Out-Null",
                "$after=@(Get-DhcpServerv4OptionValue -ComputerName $server -ScopeId $scopeId -ErrorAction Stop)",
                "$gotRouter=@($after|Where-Object{$_.OptionId -eq 3}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "$gotDns=@($after|Where-Object{$_.OptionId -eq 6}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "$gotDomain=@($after|Where-Object{$_.OptionId -eq 15}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_})",
                "if(($gotRouter -join '|') -cne ($expectedFinalRouter -join '|')){throw 'Gateway read-back verification failed: expected exact router list.'}",
                "if(($gotDns -join '|') -cne ($expectedFinalDns -join '|')){throw 'DNS read-back verification failed: expected exact DNS server list.'}",
                "if(($gotDomain -join '|') -ine ($expectedFinalDomain -join '|')){throw 'DNS domain read-back verification failed.'}",
            ]
            parts += [
                "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation='dhcp_scope_options';server=$server;scope_id=$scopeId;previous=$before;current=$after}",
            ]
            return _run_powershell("DhcpServer", ";".join(parts))

        if operation == "dhcp_scope_lease":
            scope = _ipv4(params.get("scope_id"), "Scope ID")
            hours = int(params.get("lease_hours"))
            if not 1 <= hours <= 8760:
                raise ValueError("Lease duration must be from 1 to 8760 hours.")
            body = (
                "$server=$env:COMPUTERNAME;$scopeId=" + _ps(scope) + ";"
                "$before=Get-DhcpServerv4Scope -ComputerName $server -ScopeId $scopeId -ErrorAction Stop;"
                "Set-DhcpServerv4Scope -ComputerName $server -ScopeId $scopeId -LeaseDuration (New-TimeSpan -Hours " + str(hours) + ") -ErrorAction Stop | Out-Null;"
                "$after=Get-DhcpServerv4Scope -ComputerName $server -ScopeId $scopeId -ErrorAction Stop;"
                "if([Math]::Abs($after.LeaseDuration.TotalSeconds-" + str(hours * 3600) + ") -gt 1){throw 'Lease duration read-back verification failed.'};"
                "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation='dhcp_scope_lease';server=$server;scope_id=$scopeId;previous_lease=$before.LeaseDuration.ToString();current_lease=$after.LeaseDuration.ToString()}"
            )
            return _run_powershell("DhcpServer", body)

        if operation in {"dhcp_reservation_add", "dhcp_reservation_delete"}:
            scope = _ipv4(params.get("scope_id"), "Scope ID")
            ip = _ipv4(params.get("ip_address"), "Reservation IP")
            common = (
                "$server=$env:COMPUTERNAME;$scopeId=" + _ps(scope) + ";$addr=" + _ps(ip) + ";"
                "$s=Get-DhcpServerv4Scope -ComputerName $server -ScopeId $scopeId -ErrorAction Stop;"
                "$toNumber={param($v)$b=[System.Net.IPAddress]::Parse($v).GetAddressBytes();[Array]::Reverse($b);[BitConverter]::ToUInt32($b,0)};"
                "if((&$toNumber $addr) -lt (&$toNumber $s.StartRange.ToString()) -or (&$toNumber $addr) -gt (&$toNumber $s.EndRange.ToString())){throw 'IP is outside the DHCP scope range.'};"
            )
            if operation == "dhcp_reservation_add":
                mac = str(params.get("mac_address") or "").upper().replace(":", "-")
                if not re.fullmatch(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){5}", mac):
                    raise ValueError("MAC must look like 00-11-22-33-44-55.")
                name = str(params.get("reservation_name") or "")
                if len(name) > 150 or any(ord(c) < 32 for c in name):
                    raise ValueError("Reservation name is invalid.")

                body = common + (
                    "$clientId=" + _ps(mac) + ";"
                    "$existing=@(Get-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -ErrorAction Stop);"
                    "if($existing|Where-Object{$_.IPAddress.ToString() -eq $addr}){throw 'A reservation already uses this IP.'};"
                    "if($existing|Where-Object{$_.ClientId.ToString().Replace(':','-').ToUpper() -eq $clientId}){throw 'This MAC already has a reservation in this scope.'};"
                    "$lease=Get-DhcpServerv4Lease -ComputerName $server -ScopeId $scopeId -IPAddress $addr -ErrorAction SilentlyContinue;"
                    "if($lease){throw 'This IP already has a DHCP lease.'};"
                    "Add-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -IPAddress $addr -ClientId $clientId"
                )
                if name:
                    body += " -Name " + _ps(name)
                body += (
                    " -ErrorAction Stop | Out-Null;"
                    "$verify=Get-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -IPAddress $addr -ErrorAction Stop;"
                    "if(-not $verify -or $verify.ClientId.ToString().Replace(':','-').ToUpper() -ne $clientId){throw 'Reservation read-back verification failed.'};"
                    "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation='dhcp_reservation_add';server=$server;scope_id=$scopeId;ip_address=$addr;mac_address=$clientId;name=$verify.Name}"
                )
            else:
                mac = str(params.get("mac_address") or "").upper().replace(":", "-")
                if not re.fullmatch(r"[0-9A-F]{2}(?:-[0-9A-F]{2}){5}", mac):
                    raise ValueError("MAC confirmation is required for reservation deletion.")
                body = common + (
                    "$clientId=" + _ps(mac) + ";"
                    "$r=Get-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -IPAddress $addr -ErrorAction SilentlyContinue;"
                    "if(-not $r){throw 'Reservation not found; nothing deleted.'};"
                    "if($r.ClientId.ToString().Replace(':','-').ToUpper() -ne $clientId){throw 'Reservation MAC did not match; nothing deleted.'};"
                    "Remove-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -IPAddress $addr -Confirm:$false -ErrorAction Stop;"
                    "$verify=Get-DhcpServerv4Reservation -ComputerName $server -ScopeId $scopeId -IPAddress $addr -ErrorAction SilentlyContinue;"
                    "if($verify){throw 'Reservation delete read-back verification failed.'};"
                    "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation='dhcp_reservation_delete';server=$server;scope_id=$scopeId;ip_address=$addr;mac_address=$clientId;removed=$true}"
                )
            return _run_powershell("DhcpServer", body)

        if operation == "dns_zone_create":
            zone = _safe_domain(params.get("zone"), "DNS zone")
            body = (
                "$server=$env:COMPUTERNAME;$zone=" + _ps(zone) + ";"
                "$existing=Get-DnsServerZone -ComputerName $server -Name $zone -ErrorAction SilentlyContinue;"
                "if($existing){throw 'DNS zone already exists; nothing created.'};"
                "$zoneFile=$zone + '.dns';"
                "Add-DnsServerPrimaryZone -ComputerName $server -Name $zone -ZoneFile $zoneFile -ErrorAction Stop | Out-Null;"
                "$verify=Get-DnsServerZone -ComputerName $server -Name $zone -ErrorAction Stop;"
                "if(-not $verify -or $verify.ZoneName.TrimEnd('.') -ne $zone){throw 'DNS zone creation read-back verification failed.'};"
                "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation='dns_zone_create';server=$server;zone=$zone;zone_type='StandardPrimary';zone_file=$zoneFile;created=$true}"
            )
            return _run_powershell("DnsServer", body)

        if operation in {
            "dns_a_create", "dns_a_update", "dns_a_delete",
            "dns_cname_create", "dns_cname_update", "dns_cname_delete",
        }:
            zone = _safe_domain(params.get("zone"), "DNS zone")
            name = _safe_domain(params.get("record_name"), "DNS record name", relative=True)
            ttl = int(params.get("ttl") or 3600)
            if not 30 <= ttl <= 604800:
                raise ValueError("TTL must be between 30 and 604800 seconds.")

            record_type = "A" if operation.startswith("dns_a_") else "CNAME"
            old = str(params.get("old_value") or "").rstrip(".")
            new = str(params.get("new_value") or "").rstrip(".")

            if operation.endswith(("_update", "_delete")):
                old = (
                    _ipv4(old, "Current A record value")
                    if record_type == "A"
                    else _safe_domain(old, "Current CNAME target")
                )
            if operation.endswith(("_create", "_update")):
                new = (
                    _ipv4(new, "New A record value")
                    if record_type == "A"
                    else _safe_domain(new, "New CNAME target")
                )

            base = (
                "$server=$env:COMPUTERNAME;$zone=" + _ps(zone) + ";$name=" + _ps(name) + ";"
                "$null=Get-DnsServerZone -ComputerName $server -Name $zone -ErrorAction Stop;"
                "$records=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType " + record_type + " -ErrorAction SilentlyContinue);"
            )

            if operation.endswith("_create"):
                if record_type == "A":
                    change = (
                        "$newValue=" + _ps(new) + ";"
                        "if(@($records|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $newValue}).Count){throw 'This exact A record already exists.'};"
                        "Add-DnsServerResourceRecordA -ComputerName $server -ZoneName $zone -Name $name -IPv4Address $newValue -TimeToLive (New-TimeSpan -Seconds " + str(ttl) + ") -ErrorAction Stop | Out-Null;"
                        "$verify=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType A -ErrorAction Stop|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $newValue});"
                        "if(-not $verify){throw 'DNS A record read-back verification failed.'};"
                    )
                else:
                    change = (
                        "$newValue=" + _ps(new + ".") + ";"
                        "if(@($records|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $newValue.TrimEnd('.')}).Count){throw 'This exact CNAME already exists.'};"
                        "Add-DnsServerResourceRecordCName -ComputerName $server -ZoneName $zone -Name $name -HostNameAlias $newValue -TimeToLive (New-TimeSpan -Seconds " + str(ttl) + ") -ErrorAction Stop | Out-Null;"
                        "$verify=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType CNAME -ErrorAction Stop|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $newValue.TrimEnd('.')});"
                        "if(-not $verify){throw 'DNS CNAME read-back verification failed.'};"
                    )

            elif operation.endswith("_delete"):
                compare = (
                    "$_.RecordData.IPv4Address.ToString() -eq $oldValue"
                    if record_type == "A"
                    else "$_.RecordData.HostNameAlias.TrimEnd('.') -eq $oldValue.TrimEnd('.')"
                )
                change = (
                    "$oldValue=" + _ps(old) + ";"
                    "$matching=@($records|Where-Object{" + compare + "});"
                    "if(-not $matching){throw 'Exact DNS record/value was not found; nothing deleted.'};"
                    "foreach($r in $matching){Remove-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -InputObject $r -Force -ErrorAction Stop};"
                    "$verify=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType " + record_type + " -ErrorAction SilentlyContinue|Where-Object{" + compare + "});"
                    "if($verify){throw 'DNS record delete read-back verification failed.'};"
                )

            else:
                compare = (
                    "$_.RecordData.IPv4Address.ToString() -eq $oldValue"
                    if record_type == "A"
                    else "$_.RecordData.HostNameAlias.TrimEnd('.') -eq $oldValue.TrimEnd('.')"
                )
                if record_type == "A":
                    change = (
                        "$oldValue=" + _ps(old) + ";$newValue=" + _ps(new) + ";"
                        "$matching=@($records|Where-Object{" + compare + "});"
                        "if(@($matching).Count -ne 1){throw 'Exactly one matching A record is required for update.'};"
                        "$oldRecord=$matching[0];$existingNew=@($records|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $newValue});$added=$false;"
                        "if($oldValue -eq $newValue){$replacement=$oldRecord.Clone();$replacement.TimeToLive=New-TimeSpan -Seconds " + str(ttl) + ";Set-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -OldInputObject $oldRecord -NewInputObject $replacement -ErrorAction Stop | Out-Null}"
                        "else{if(-not $existingNew){Add-DnsServerResourceRecordA -ComputerName $server -ZoneName $zone -Name $name -IPv4Address $newValue -TimeToLive (New-TimeSpan -Seconds " + str(ttl) + ") -ErrorAction Stop | Out-Null;$added=$true};try{Remove-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -InputObject $oldRecord -Force -ErrorAction Stop}catch{if($added){Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType A -ErrorAction SilentlyContinue|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $newValue}|ForEach-Object{Remove-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -InputObject $_ -Force -ErrorAction SilentlyContinue}};throw}};"
                        "$verify=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType A -ErrorAction Stop);"
                        "if(-not ($verify|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $newValue})){throw 'New A record read-back verification failed.'};"
                        "if($oldValue -ne $newValue -and ($verify|Where-Object{$_.RecordData.IPv4Address.ToString() -eq $oldValue})){throw 'Old A record still exists after update.'};"
                    )
                else:
                    change = (
                        "$oldValue=" + _ps(old + ".") + ";$newValue=" + _ps(new + ".") + ";"
                        "$matching=@($records|Where-Object{" + compare + "});"
                        "if(@($matching).Count -ne 1){throw 'Exactly one matching CNAME is required for update.'};"
                        "$oldRecord=$matching[0];"
                        "if($oldValue.TrimEnd('.') -eq $newValue.TrimEnd('.')){$replacement=$oldRecord.Clone();$replacement.TimeToLive=New-TimeSpan -Seconds " + str(ttl) + ";Set-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -OldInputObject $oldRecord -NewInputObject $replacement -ErrorAction Stop | Out-Null}"
                        "else{$existingNew=@($records|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $newValue.TrimEnd('.')});$added=$false;if(-not $existingNew){Add-DnsServerResourceRecordCName -ComputerName $server -ZoneName $zone -Name $name -HostNameAlias $newValue -TimeToLive (New-TimeSpan -Seconds " + str(ttl) + ") -ErrorAction Stop | Out-Null;$added=$true};try{Remove-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -InputObject $oldRecord -Force -ErrorAction Stop}catch{if($added){Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType CNAME -ErrorAction SilentlyContinue|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $newValue.TrimEnd('.')}|ForEach-Object{Remove-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -InputObject $_ -Force -ErrorAction SilentlyContinue}};throw}};"
                        "$verify=@(Get-DnsServerResourceRecord -ComputerName $server -ZoneName $zone -Name $name -RRType CNAME -ErrorAction Stop);"
                        "if(-not ($verify|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $newValue.TrimEnd('.')})){throw 'New CNAME read-back verification failed.'};"
                        "if($oldValue.TrimEnd('.') -ne $newValue.TrimEnd('.') -and ($verify|Where-Object{$_.RecordData.HostNameAlias.TrimEnd('.') -eq $oldValue.TrimEnd('.')})){throw 'Old CNAME still exists after update.'};"
                    )

            body = (
                base + change
                + "$out=[pscustomobject]@{status='Succeeded';verified=$true;operation=" + _ps(operation)
                + ";server=$server;zone=$zone;name=$name;record_type=" + _ps(record_type)
                + ";old_value=" + _ps(old) + ";new_value=" + _ps(new)
                + ";ttl=" + str(ttl) + "}"
            )
            return _run_powershell("DnsServer", body)

        return "Failed", json.dumps({
            "status": "Failed", "error": "Unsupported DNS/DHCP operation.",
        })
    except (ValueError, TypeError, KeyError) as exc:
        return "Failed", json.dumps({"status": "Failed", "error": str(exc)})
